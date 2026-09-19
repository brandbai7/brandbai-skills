"""Single-room live recording core for BrandBAI.

The module provides deterministic input validation, privacy-safe Douyin
resolution through StreamGet, FFmpeg segmentation, MP4 remuxing, media
verification, redacted ledgers, bounded runs, and explicit completion states.
The localhost service and Chrome UI are adapters around this core.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, TextIO
from urllib.parse import parse_qs, urlsplit, urlunsplit

from export_naming import export_info
from recording_watchdog import MediaProgress

from room_metrics import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    MAX_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
    RoomMetricsCollector,
    extract_safe_room_metrics,
)


CONTRACT_VERSION = "0.18.0"
TOOL_VERSION = "0.22.16"
REGULAR_SEGMENT_MIN_SECONDS = 60
REGULAR_SEGMENT_MAX_SECONDS = 21_600
TEST_SEGMENT_MIN_SECONDS = 10
MIN_MAX_RUNTIME_SECONDS = 10
MAX_MAX_RUNTIME_SECONDS = 86_400
QUALITY_VALUES = {"SD", "HD", "OD"}
DEFAULT_SEGMENT_SECONDS = 1_800
DEFAULT_MIN_FREE_SPACE_GB = 10.0
VALID_MEDIA_STATUSES = {"valid", "valid_video_only", "short_fragment"}
STARTUP_RETRY_BACKOFF_SECONDS = 1.0
FFMPEG_TIME_LIMIT_WALL_GRACE_SECONDS = 15.0
MAX_STREAM_RECOVERY_ATTEMPTS = 2
STREAM_RECOVERY_BACKOFF_SECONDS = 2.0
MAX_EXPLICIT_SEGMENT_BOUNDARY_CHARS = 16_000
TRANSIENT_FFMPEG_STARTUP_MARKERS = (
    "error reading http response",
    "error opening input: end of file",
    "connection reset",
    "connection timed out",
    "http error 502",
    "http error 503",
    "server returned 5",
)


def _windows_creation_flags(*, process_group: bool = False) -> int:
    """Keep recorder child processes invisible when the service has no console."""

    if os.name != "nt":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def _run_hidden(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        creationflags=_windows_creation_flags(),
        **kwargs,
    )


class RecorderError(RuntimeError):
    """Base error with a stable, non-sensitive reason code."""

    reason_code = "recorder_error"


class InputError(RecorderError):
    """Raised when a task input violates the P0 contract."""

    reason_code = "invalid_input"


class EnvironmentError(RecorderError):
    """Raised when a required local runtime dependency is unavailable."""

    reason_code = "runtime_unavailable"


class ResolveError(RecorderError):
    """Raised when the public room cannot be resolved into stream data."""

    reason_code = "resolver_failed"

    def __init__(self, message: str, *, reason_code: str | None = None):
        super().__init__(message)
        if reason_code:
            self.reason_code = reason_code


class StorageError(RecorderError):
    """Raised when the output directory cannot safely accept a recording."""

    reason_code = "storage_unavailable"


PROXY_ENV_KEYS = ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy")
NETWORK_RESPONSE_MARKERS = (
    "connection refused",
    "connecterror",
    "failed to establish a new connection",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "timed out",
    "timeout",
    "winerror 10060",
    "winerror 10061",
)


def proxy_environment_report(environment: dict[str, str] | None = None) -> dict[str, Any]:
    """Describe proxy presence without returning proxy values or credentials."""

    source = os.environ if environment is None else environment
    present = sorted({key.upper() for key in PROXY_ENV_KEYS if str(source.get(key) or "").strip()})
    return {
        "variables_present": present,
        "configured": bool(present),
        "values_exposed": False,
        "connectivity_checked": False,
    }


def classify_resolver_exception(exc: Exception) -> tuple[str, str]:
    """Map unstable third-party errors to stable, redacted public reasons."""

    if isinstance(exc, json.JSONDecodeError):
        response = str(getattr(exc, "doc", "") or "").strip()
        lowered = response.lower()
        if any(marker in lowered for marker in NETWORK_RESPONSE_MARKERS):
            return (
                "resolver_network_unavailable",
                "The resolver could not reach the public Douyin endpoint; check host network and proxy availability.",
            )
        if not response:
            return (
                "resolver_empty_response",
                "The resolver received an empty response from the public Douyin endpoint.",
            )
        return (
            "resolver_response_changed",
            "The resolver received a non-JSON or changed response from the public Douyin endpoint.",
        )

    lowered = str(exc).lower()
    if any(marker in lowered for marker in NETWORK_RESPONSE_MARKERS):
        return (
            "resolver_network_unavailable",
            "The resolver could not reach the public Douyin endpoint; check host network and proxy availability.",
        )
    if any(marker in lowered for marker in ("risk control", "captcha", "verify", "verification")):
        return (
            "resolver_access_challenge",
            "The public Douyin endpoint requested additional verification; recording was not retried or bypassed.",
        )
    return (
        "resolver_failed",
        "The public Douyin room could not be resolved by the installed StreamGet version.",
    )


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().isoformat(timespec="seconds")


def validate_segment_duration(seconds: int, *, test_mode: bool = False) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise InputError("segment duration must be a whole number of seconds")
    minimum = TEST_SEGMENT_MIN_SECONDS if test_mode else REGULAR_SEGMENT_MIN_SECONDS
    if seconds < minimum or seconds > REGULAR_SEGMENT_MAX_SECONDS:
        if test_mode:
            raise InputError("test-mode segment duration must be between 10 and 21600 seconds")
        raise InputError("segment duration must be between 60 and 21600 seconds")
    return seconds


def normalize_segment_duration(
    value: int | None,
    *,
    unit: str = "seconds",
    test_mode: bool = False,
) -> int:
    if value is None:
        return DEFAULT_SEGMENT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError("segment duration must be a whole number")
    if unit == "minutes":
        seconds = value * 60
    elif unit == "seconds":
        seconds = value
    else:
        raise InputError("segment duration unit must be minutes or seconds")
    return validate_segment_duration(seconds, test_mode=test_mode)


def normalize_douyin_room_url(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise InputError("a Douyin live-room URL is required")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise InputError("P0 requires an https://live.douyin.com/ room URL")
    if parts.username or parts.password or parts.port:
        raise InputError("credentials and custom ports are not allowed in the room URL")
    host = (parts.hostname or "").lower()
    if host != "live.douyin.com":
        raise InputError("P0 only accepts live.douyin.com room URLs")
    path = "/" + "/".join(part for part in parts.path.split("/") if part)
    if path == "/":
        raise InputError("the room URL must contain a room identifier")
    room_id = path.strip("/").split("/", maxsplit=1)[0]
    canonical = urlunsplit(("https", host, path.rstrip("/"), "", ""))
    return canonical, room_id


def stable_task_id(canonical_room_url: str) -> str:
    digest = hashlib.sha256(canonical_room_url.encode("utf-8")).hexdigest()[:16]
    return f"dy-{digest}"


def sanitize_filename(value: str, *, fallback: str = "直播间", limit: int = 64) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", str(value or ""))
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._")
    return (cleaned[:limit].rstrip(" ._") or fallback)


def create_session_output_root(
    base_root: Path,
    room_id: str,
    *,
    now: datetime | None = None,
    run_token: str | None = None,
) -> Path:
    """Return a unique, human-browsable directory for one recording session."""

    observed_at = now or local_now()
    batch = uuid.uuid5(uuid.NAMESPACE_OID, run_token) if run_token else uuid.uuid4()
    info = export_info('recording', observed_at=observed_at,
        room_url=f'https://live.douyin.com/{room_id}', batch_id=batch)
    # The folder is frozen before probing; never rename an active task's files.
    return base_root.expanduser().resolve() / '直播录制' / info['package_name']


URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?i)\b(token|sign|signature|cookie|authorization|auth|session|key)\s*[:=]\s*([^\s,;&]+)"
)


def redact_text(value: str, *, secrets: Iterable[str] = ()) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    text = URL_RE.sub("[URL_REDACTED]", text)
    text = SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StorageError(f"invalid JSONL at {path.name}:{line_number}") from exc
            if not isinstance(value, dict):
                raise StorageError(f"JSONL records must be objects: {path.name}:{line_number}")
            rows.append(value)
    return rows


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def relative_posix(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        return resolved.relative_to(root_resolved).as_posix()
    except ValueError as exc:
        raise StorageError("manifest paths must stay inside the output directory") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def value_from(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


@dataclass(slots=True)
class StreamInfo:
    canonical_room_url: str
    room_id: str
    streamer_name: str
    title: str | None
    is_live: bool
    source_type: str | None
    requested_quality: str
    actual_quality: str | None
    quality_fallback_reason: str | None
    stream_url: str | None
    room_metrics: dict[str, Any] | None = None

    def public_summary(self) -> dict[str, Any]:
        summary = {
            "canonical_room_url": self.canonical_room_url,
            "room_id": self.room_id,
            "streamer_name": self.streamer_name,
            "title": self.title,
            "is_live": self.is_live,
            "source_type": self.source_type,
            "requested_quality": self.requested_quality,
            "actual_quality": self.actual_quality,
            "quality_fallback_reason": self.quality_fallback_reason,
        }
        if self.room_metrics is not None:
            summary["room_metrics"] = self.room_metrics
        return summary


async def resolve_douyin_room(room_url: str, requested_quality: str = "SD") -> StreamInfo:
    quality = requested_quality.upper()
    if quality not in QUALITY_VALUES:
        raise InputError("quality must be one of SD, HD, or OD")
    canonical, room_id = normalize_douyin_room_url(room_url)
    try:
        from streamget import DouyinLiveStream  # type: ignore[import-not-found]
    except ImportError as exc:
        raise EnvironmentError(
            "StreamGet runtime is unavailable; run the private runtime setup before resolving a real Douyin room"
        ) from exc

    resolver = DouyinLiveStream()
    try:
        page_data = await resolver.fetch_web_stream_data(canonical)
        stream_data = await resolver.fetch_stream_url(page_data, quality)
    except Exception as exc:
        reason_code, message = classify_resolver_exception(exc)
        raise ResolveError(message, reason_code=reason_code) from exc

    if stream_data is None:
        raise ResolveError("Douyin room resolution returned no stream data")

    is_live = bool(value_from(stream_data, "is_live", False))
    anchor_name = str(value_from(stream_data, "anchor_name", "") or room_id)
    title = value_from(stream_data, "title")
    actual_quality_value = value_from(stream_data, "quality")
    actual_quality = str(actual_quality_value) if actual_quality_value else None

    flv_url = value_from(stream_data, "flv_url")
    m3u8_url = value_from(stream_data, "m3u8_url")
    record_url = value_from(stream_data, "record_url")
    chosen_url: str | None = None
    source_type: str | None = None

    if flv_url:
        codec = (parse_qs(urlsplit(str(flv_url)).query).get("codec") or [""])[0].lower()
        if codec != "h265":
            chosen_url = str(flv_url)
            source_type = "FLV"
    if not chosen_url and m3u8_url:
        chosen_url = str(m3u8_url)
        source_type = "HLS"
    if not chosen_url and record_url:
        chosen_url = str(record_url)
        source_type = "resolved"

    if is_live and not chosen_url:
        raise ResolveError("the room is live but no supported stream URL was returned")

    fallback_reason = None
    if actual_quality and actual_quality.upper() != quality:
        fallback_reason = "requested quality was unavailable; resolver returned another observed quality"

    return StreamInfo(
        canonical_room_url=canonical,
        room_id=room_id,
        streamer_name=anchor_name,
        title=str(title) if title else None,
        is_live=is_live,
        source_type=source_type,
        requested_quality=quality,
        actual_quality=actual_quality,
        quality_fallback_reason=fallback_reason,
        stream_url=chosen_url,
        room_metrics=extract_safe_room_metrics(page_data),
    )


def resolve_douyin_room_sync(room_url: str, requested_quality: str = "SD") -> StreamInfo:
    return asyncio.run(resolve_douyin_room(room_url, requested_quality))


def resolve_executable(explicit: str | None, executable_name: str) -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise EnvironmentError(f"{executable_name} does not exist at the provided path")
    found = shutil.which(executable_name)
    if not found:
        raise EnvironmentError(f"{executable_name} was not found on PATH")
    return found


def run_version_command(executable: str) -> list[str]:
    completed = _run_hidden(
        [executable, "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    return (completed.stdout or completed.stderr or "").splitlines()


def installed_package_version(
    package_name: str, *, search_paths: Iterable[str] | None = None
) -> str:
    version = importlib.metadata.version(package_name)
    if version:
        return str(version)
    normalized = package_name.replace("-", "_")
    prefix = f"{normalized}-"
    for raw_path in search_paths if search_paths is not None else sys.path:
        if not raw_path:
            continue
        try:
            candidates = Path(raw_path).glob(f"{normalized}-*.dist-info")
            for candidate in candidates:
                name = candidate.name
                if name.startswith(prefix) and name.endswith(".dist-info"):
                    fallback = name[len(prefix) : -len(".dist-info")]
                    if fallback:
                        return fallback
        except OSError:
            continue
    return "unknown"


def doctor_report(
    *, ffmpeg_path: str | None = None, ffprobe_path: str | None = None
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "tool_version": TOOL_VERSION,
        "python": {
            "version": ".".join(map(str, sys.version_info[:3])),
            "supported": sys.version_info >= (3, 10),
        },
        "ffmpeg": {"available": False},
        "ffprobe": {"available": False},
        "streamget": {"available": False},
        "network_environment": proxy_environment_report(),
        "ready_for_real_douyin": False,
    }
    try:
        ffmpeg = resolve_executable(ffmpeg_path, "ffmpeg")
        version_lines = run_version_command(ffmpeg)
        config_line = next((line for line in version_lines if line.startswith("configuration:")), "")
        report["ffmpeg"] = {
            "available": True,
            "version": version_lines[0] if version_lines else "unknown",
            "gpl_enabled": "--enable-gpl" in config_line,
            "version3_enabled": "--enable-version3" in config_line,
            "distribution_review_required": "--enable-gpl" in config_line,
        }
    except RecorderError as exc:
        report["ffmpeg"] = {"available": False, "error": str(exc)}

    try:
        ffprobe = resolve_executable(ffprobe_path, "ffprobe")
        version_lines = run_version_command(ffprobe)
        report["ffprobe"] = {
            "available": True,
            "version": version_lines[0] if version_lines else "unknown",
        }
    except RecorderError as exc:
        report["ffprobe"] = {"available": False, "error": str(exc)}

    try:
        version = installed_package_version("streamget")
        from streamget import DouyinLiveStream

        if not callable(DouyinLiveStream):
            raise ImportError("DouyinLiveStream is not callable")
        report["streamget"] = {
            "available": True,
            "version": version,
            "douyin_resolver_import": True,
        }
    except (importlib.metadata.PackageNotFoundError, ImportError, OSError) as exc:
        report["streamget"] = {
            "available": False,
            "error": (
                "private runtime discovery could not load DouyinLiveStream: "
                f"{type(exc).__name__}"
            ),
        }

    report["ready_for_real_douyin"] = bool(
        report["python"]["supported"]
        and report["ffmpeg"]["available"]
        and report["streamget"]["available"]
    )
    return report


@dataclass(slots=True)
class RecorderConfig:
    room_url: str
    output_root: Path
    segment_duration_seconds: int = DEFAULT_SEGMENT_SECONDS
    split_enabled: bool = True
    requested_quality: str = "SD"
    retain_original: bool = True
    test_mode: bool = False
    min_free_space_gb: float = DEFAULT_MIN_FREE_SPACE_GB
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    full_read_check: bool = False
    compute_sha256: bool = False
    confirm_eof_as_offline: bool = False
    max_runtime_seconds: int | None = None
    collect_room_metrics: bool = False
    room_metrics_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS

    def validated(self) -> "RecorderConfig":
        canonical, _ = normalize_douyin_room_url(self.room_url)
        self.room_url = canonical
        self.segment_duration_seconds = validate_segment_duration(
            self.segment_duration_seconds, test_mode=self.test_mode
        )
        if not isinstance(self.split_enabled, bool):
            raise InputError("split_enabled must be true or false")
        self.requested_quality = self.requested_quality.upper()
        if self.requested_quality not in QUALITY_VALUES:
            raise InputError("quality must be one of SD, HD, or OD")
        if self.min_free_space_gb < 0:
            raise InputError("minimum free space cannot be negative")
        if self.max_runtime_seconds is not None:
            if isinstance(self.max_runtime_seconds, bool) or not isinstance(
                self.max_runtime_seconds, int
            ):
                raise InputError("maximum runtime must be a whole number of seconds")
            if not MIN_MAX_RUNTIME_SECONDS <= self.max_runtime_seconds <= MAX_MAX_RUNTIME_SECONDS:
                raise InputError("maximum runtime must be between 10 and 86400 seconds")
        if not isinstance(self.collect_room_metrics, bool):
            raise InputError("collect_room_metrics must be true or false")
        if isinstance(self.room_metrics_interval_seconds, bool) or not isinstance(
            self.room_metrics_interval_seconds, int
        ):
            raise InputError("room metric interval must be a whole number of seconds")
        if not (
            MIN_POLL_INTERVAL_SECONDS
            <= self.room_metrics_interval_seconds
            <= MAX_POLL_INTERVAL_SECONDS
        ):
            raise InputError("room metric interval must be between 10 and 300 seconds")
        self.output_root = self.output_root.expanduser().resolve()
        return self


@dataclass(slots=True)
class MediaProbe:
    duration_seconds: float | None
    container: str | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool
    sustained_read_ok: bool | None
    error: str | None


@dataclass(slots=True)
class RecordingResult:
    task_id: str
    session_id: str | None
    outcome: str
    completion_status: str | None
    valid_mp4_count: int
    segment_count: int
    actual_media_duration_seconds: float
    output_root: str
    test_only: bool
    retryable_startup_failure: bool = False
    retryable_stream_failure: bool = False


def is_retryable_ffmpeg_startup_failure(
    stderr_tail: str,
    *,
    has_media: bool,
    manual_stop: bool,
    service_stop: bool,
    time_limit_stop: bool,
) -> bool:
    """Return true only for a zero-media transient FFmpeg input failure."""

    if has_media or manual_stop or service_stop or time_limit_stop:
        return False
    lowered = stderr_tail.lower()
    return any(marker in lowered for marker in TRANSIENT_FFMPEG_STARTUP_MARKERS)


class RedactedStderrCollector:
    def __init__(self, stream: TextIO | None, *, secrets: Iterable[str], max_lines: int = 120):
        self.stream = stream
        self.secrets = tuple(str(value) for value in secrets if value)
        self.lines: deque[str] = deque(maxlen=max_lines)
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def _drain(self) -> None:
        if self.stream is None:
            return
        for line in iter(self.stream.readline, ""):
            cleaned = redact_text(line.strip(), secrets=self.secrets)
            if cleaned:
                self.lines.append(cleaned)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: float = 5.0) -> None:
        self.thread.join(timeout=timeout)

    def tail(self) -> str:
        return "\n".join(self.lines)


class RunLedger:
    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()
        self.data_dir = self.output_root / "data"
        self.logs_dir = self.output_root / "logs"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def append(self, filename: str, record: dict[str, Any]) -> None:
        append_jsonl(self.data_dir / filename, record)

    def event(
        self,
        event_type: str,
        *,
        task_id: str,
        session_id: str | None = None,
        message: str,
        detail: str | None = None,
    ) -> None:
        timestamp = iso_time(local_now())
        record = {
            "event_id": f"evt-{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "timestamp": timestamp,
            "task_id": task_id,
            "session_id": session_id,
            "message": message,
            "detail": detail,
        }
        self.append("events.jsonl", record)
        log_line = f"{timestamp} | {event_type} | {task_id} | {message}"
        if detail:
            log_line += f" | {detail}"
        with (self.logs_dir / "runtime_redacted.log").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(log_line + "\n")

    def task_snapshot(self, record: dict[str, Any]) -> None:
        self.append("tasks.jsonl", record)

    def session(self, record: dict[str, Any]) -> None:
        self.append("sessions.jsonl", record)

    def segment(self, record: dict[str, Any]) -> None:
        self.append("segments.jsonl", record)

    def gap(self, record: dict[str, Any]) -> None:
        self.append("gaps.jsonl", record)

    def rebuild_project_manifest(self) -> dict[str, Any]:
        task_snapshots = read_jsonl(self.data_dir / "tasks.jsonl")
        latest_tasks: dict[str, dict[str, Any]] = {}
        for task in task_snapshots:
            task_id = str(task.get("task_id") or "")
            if task_id:
                latest_tasks[task_id] = task
        sessions = read_jsonl(self.data_dir / "sessions.jsonl")
        segments = read_jsonl(self.data_dir / "segments.jsonl")
        gaps = read_jsonl(self.data_dir / "gaps.jsonl")
        room_metric_events = read_jsonl(self.data_dir / "room_metrics.jsonl")
        room_metric_snapshots = [
            row for row in room_metric_events if row.get("event_type") == "room_snapshot"
        ]

        valid_mp4 = [
            row
            for row in segments
            if row.get("relative_mp4_path")
            and row.get("media_validation_status") in VALID_MEDIA_STATUSES
        ]
        retained_originals = [row for row in segments if row.get("relative_original_path")]
        total_duration = sum(
            float(row["actual_duration_seconds"])
            for row in valid_mp4
            if isinstance(row.get("actual_duration_seconds"), (int, float))
        )
        total_size = sum(
            int(row["file_size_bytes"])
            for row in valid_mp4
            if isinstance(row.get("file_size_bytes"), int)
        )
        status_counts = Counter(str(row.get("completion_status") or "unknown") for row in sessions)
        known_gaps = sum(1 for row in gaps if row.get("duration_status") == "known")
        unknown_gaps = sum(1 for row in gaps if row.get("duration_status") != "known")

        manifest = {
            "contract_version": CONTRACT_VERSION,
            "tool_version": TOOL_VERSION,
            "prototype_scope": "single-room immediate recording with optional localhost control",
            "platform": "douyin",
            "generated_at": iso_time(local_now()),
            "task_count": len(latest_tasks),
            "session_count": len(sessions),
            "valid_mp4_count": len(valid_mp4),
            "retained_original_count": len(retained_originals),
            "actual_media_duration_seconds": round(total_duration, 3),
            "valid_mp4_size_bytes": total_size,
            "known_gap_count": known_gaps,
            "unknown_gap_count": unknown_gaps,
            "room_metric_snapshot_count": len(room_metric_snapshots),
            "completion_status_counts": dict(sorted(status_counts.items())),
            "evidence_boundary": (
                "Completion describes the tool's observed recording window only; it does not prove "
                "coverage of the platform-defined full broadcast."
            ),
            "not_in_prototype": [
                "loop monitoring service",
                "Excel delivery",
                "unbounded automatic reconnection",
                "long-duration real-room acceptance",
            ],
        }
        write_json_atomic(self.data_dir / "project_manifest.json", manifest)
        self._write_human_summary(manifest)
        return manifest

    def _write_human_summary(self, manifest: dict[str, Any]) -> None:
        status_lines = [
            f"- `{key}`：{value} 场"
            for key, value in manifest.get("completion_status_counts", {}).items()
        ] or ["- 当前没有观察场次。"]
        body = "\n".join(
            [
                "# 录屏说明与完整性",
                "",
                f"- 工具版本：{manifest['tool_version']}",
                f"- 直播间任务：{manifest['task_count']}",
                f"- 观察场次：{manifest['session_count']}",
                f"- 有效 MP4：{manifest['valid_mp4_count']}",
                f"- 有效媒体总时长：{manifest['actual_media_duration_seconds']} 秒",
                f"- 已知中断：{manifest['known_gap_count']}",
                f"- 时长未知的中断：{manifest['unknown_gap_count']}",
                f"- 无浏览器房间指标快照：{manifest['room_metric_snapshot_count']}",
                "",
                "## 完成状态",
                "",
                *status_lines,
                "",
                "## 当前边界",
                "",
                "本文件只描述工具实际观察到的录制窗口，不证明覆盖平台定义的完整直播。",
                "当前版本支持单直播间探测、立即录制和限时停止；本机服务与插件仍为实验适配器。",
                "断流仅在原截止时间内有限重试；尚未包含循环监控、无限重连和 Excel 交付。",
                "",
            ]
        )
        (self.output_root / "02_录屏说明与完整性.md").write_text(body, encoding="utf-8")


def check_free_space(output_root: Path, threshold_gb: float) -> float:
    output_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(output_root)
    free_gb = usage.free / (1024**3)
    if free_gb < threshold_gb:
        raise StorageError(
            f"free disk space is below the configured {threshold_gb:g} GB safety threshold"
        )
    return free_gb


def build_ffmpeg_segment_command(
    *, ffmpeg: str, stream_url: str, output_pattern: Path, segment_seconds: int
) -> list[str]:
    return build_ffmpeg_record_command(
        ffmpeg=ffmpeg,
        stream_url=stream_url,
        output_pattern=output_pattern,
        segment_seconds=segment_seconds,
        split_enabled=True,
    )


def _bounded_segment_times(
    *, max_runtime_seconds: float, segment_seconds: int
) -> str | None:
    """Return split points before the terminal recording boundary.

    FFmpeg's repeating ``segment_time`` can open a new file exactly when ``-t``
    ends, leaving a few packets in an extra near-empty tail segment.  A bounded
    task already knows every intended split point, so list only the boundaries
    that occur strictly before the requested end time.  Very large test-only
    lists fall back to the repeating segment mode to stay within Windows command
    line limits.
    """

    boundaries: list[str] = []
    boundary = segment_seconds
    while boundary < max_runtime_seconds:
        boundaries.append(str(boundary))
        boundary += segment_seconds
    serialized = ",".join(boundaries)
    if len(serialized) > MAX_EXPLICIT_SEGMENT_BOUNDARY_CHARS:
        return None
    return serialized


def build_ffmpeg_record_command(
    *,
    ffmpeg: str,
    stream_url: str,
    output_pattern: Path,
    segment_seconds: int,
    split_enabled: bool,
    max_runtime_seconds: float | None = None,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-stats_period",
        "1",
        "-y",
        "-i",
        stream_url,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
    ]
    if max_runtime_seconds is not None:
        command.extend(["-t", f"{max_runtime_seconds:g}"])
    if split_enabled:
        segment_option = ["-segment_time", str(segment_seconds)]
        if max_runtime_seconds is not None:
            segment_times = _bounded_segment_times(
                max_runtime_seconds=max_runtime_seconds,
                segment_seconds=segment_seconds,
            )
            if segment_times == "":
                single_output = Path(str(output_pattern).replace("%03d", "001"))
                return command + ["-f", "mpegts", str(single_output)]
            if segment_times is not None:
                segment_option = ["-segment_times", segment_times]
        return command + [
            "-f",
            "segment",
            *segment_option,
            "-segment_start_number",
            "1",
            "-reset_timestamps",
            "1",
            "-segment_format",
            "mpegts",
            str(output_pattern),
        ]
    single_output = Path(str(output_pattern).replace("%03d", "001"))
    return command + ["-f", "mpegts", str(single_output)]


def build_ffmpeg_remux_command(*, ffmpeg: str, source: Path, destination: Path) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(destination),
    ]


def _run_full_read_check(ffmpeg: str, path: Path) -> tuple[bool, str | None]:
    null_device = "NUL" if os.name == "nt" else "/dev/null"
    completed = _run_hidden(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", null_device],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return True, None
    return False, redact_text(completed.stderr, secrets=(str(path),))[-2_000:]


def _probe_with_ffprobe(ffprobe: str, path: Path) -> MediaProbe:
    completed = _run_hidden(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return MediaProbe(None, None, None, None, None, None, False, False, None, "probe_failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return MediaProbe(None, None, None, None, None, None, False, False, None, "invalid_probe_json")
    streams = payload.get("streams") if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
    format_info = payload.get("format", {}) if isinstance(payload, dict) else {}
    duration_value = format_info.get("duration") if isinstance(format_info, dict) else None
    try:
        duration = float(duration_value) if duration_value not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None
    return MediaProbe(
        duration_seconds=duration,
        container=str(format_info.get("format_name")) if format_info.get("format_name") else None,
        video_codec=str(video.get("codec_name")) if video else None,
        audio_codec=str(audio.get("codec_name")) if audio else None,
        width=int(video["width"]) if video and isinstance(video.get("width"), int) else None,
        height=int(video["height"]) if video and isinstance(video.get("height"), int) else None,
        has_video=bool(video),
        has_audio=bool(audio),
        sustained_read_ok=None,
        error=None,
    )


def _probe_with_ffmpeg(ffmpeg: str, path: Path) -> MediaProbe:
    completed = _run_hidden(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stderr or completed.stdout or ""
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    duration = None
    if duration_match:
        duration = (
            int(duration_match.group(1)) * 3600
            + int(duration_match.group(2)) * 60
            + float(duration_match.group(3))
        )
    video_match = re.search(r"Video:\s*([^,]+).*?(\d{2,5})x(\d{2,5})", output)
    audio_match = re.search(r"Audio:\s*([^,]+)", output)
    return MediaProbe(
        duration_seconds=duration,
        container=path.suffix.lower().lstrip(".") or None,
        video_codec=video_match.group(1).strip() if video_match else None,
        audio_codec=audio_match.group(1).strip() if audio_match else None,
        width=int(video_match.group(2)) if video_match else None,
        height=int(video_match.group(3)) if video_match else None,
        has_video=bool(video_match),
        has_audio=bool(audio_match),
        sustained_read_ok=None,
        error=None if video_match and duration is not None else "probe_failed",
    )


def probe_media(
    *,
    path: Path,
    ffmpeg: str,
    ffprobe: str | None,
    full_read_check: bool,
) -> MediaProbe:
    if not path.is_file() or path.stat().st_size <= 0:
        return MediaProbe(None, None, None, None, None, None, False, False, None, "missing_or_empty")
    probe = _probe_with_ffprobe(ffprobe, path) if ffprobe else _probe_with_ffmpeg(ffmpeg, path)
    if full_read_check and probe.has_video:
        ok, error = _run_full_read_check(ffmpeg, path)
        probe.sustained_read_ok = ok
        if not ok:
            probe.error = error or "sustained_read_failed"
    return probe


def media_validation_status(probe: MediaProbe, *, target_seconds: int) -> tuple[str, bool]:
    if not probe.has_video or probe.duration_seconds is None or probe.error:
        return "invalid_media", False
    short = probe.duration_seconds < min(target_seconds, REGULAR_SEGMENT_MIN_SECONDS)
    if short:
        return "short_fragment", True
    if not probe.has_audio:
        return "valid_video_only", False
    return "valid", False


def select_completion_status(
    *,
    has_media: bool,
    storage_failed: bool,
    conversion_failed: bool,
    ffmpeg_return_code: int | None,
    manual_stop: bool,
    service_stop: bool,
    time_limit_stop: bool = False,
    offline_confirmed: bool,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if storage_failed:
        return "failed_storage", ["storage_failure"]
    if not has_media:
        return "failed_no_media", ["no_valid_media"]
    if conversion_failed:
        issues.append("conversion_failed")
    if ffmpeg_return_code not in (0, None):
        issues.append("ffmpeg_nonzero_exit")
    if manual_stop:
        issues.append("manual_stop")
    if service_stop:
        issues.append("service_stop")
    if time_limit_stop:
        issues.append("time_limit_stop")
    if (
        ffmpeg_return_code == 0
        and not offline_confirmed
        and not manual_stop
        and not service_stop
        and not time_limit_stop
    ):
        issues.append("source_ended_without_offline_confirmation")

    if conversion_failed:
        return "partial_conversion", issues
    if ffmpeg_return_code not in (0, None) or (
        ffmpeg_return_code == 0
        and not offline_confirmed
        and not manual_stop
        and not service_stop
        and not time_limit_stop
    ):
        return "partial_disconnect", issues
    if manual_stop:
        return "partial_manual_stop", issues
    if service_stop:
        return "partial_service_stop", issues
    if time_limit_stop:
        return "partial_time_limit", issues
    return "complete_observed_session", issues


def _task_snapshot(
    *,
    task_id: str,
    stream: StreamInfo,
    config: RecorderConfig,
    task_state: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "record_type": "task_snapshot",
        "task_id": task_id,
        "platform": "douyin",
        "room_id": stream.room_id,
        "canonical_room_url": stream.canonical_room_url,
        "streamer_name": stream.streamer_name,
        "mode": "immediate",
        "requested_quality": config.requested_quality,
        "split_enabled": config.split_enabled,
        "segment_duration_seconds": config.segment_duration_seconds,
        "max_runtime_seconds": config.max_runtime_seconds,
        "retain_original": config.retain_original,
        "test_only": config.test_mode,
        "collect_room_metrics": config.collect_room_metrics,
        "room_metrics_interval_seconds": config.room_metrics_interval_seconds,
        "created_at": iso_time(created_at),
        "updated_at": iso_time(local_now()),
        "monitor_started_at": None,
        "monitor_stopped_at": None,
        "task_state": task_state,
    }


def _run_ffmpeg_process(
    command: list[str],
    *,
    secrets: Iterable[str],
    stop_event: threading.Event | None = None,
    stop_event_kind: str = "service",
    max_runtime_seconds: float | None = None,
    wall_clock_grace_seconds: float = 0.0,
    watch_progress: bool = False,
    progress_callback=None,
    startup_timeout_seconds: float = 45.0,
    stall_timeout_seconds: float = 30.0,
) -> tuple[int | None, bool, bool, bool, str]:
    if stop_event_kind not in {"service", "manual"}:
        raise ValueError("stop_event_kind must be service or manual")
    creationflags = _windows_creation_flags(process_group=True)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if watch_progress else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=creationflags,
    )
    collector = RedactedStderrCollector(process.stderr, secrets=secrets)
    collector.start()
    progress = MediaProgress(process.stdout) if watch_progress else None
    if progress is not None:
        progress.start()
    stalled = False
    last_report = float('-inf')
    manual_stop = False
    service_stop = False
    time_limit_stop = False
    started_monotonic = time.monotonic()

    def request_graceful_stop() -> None:
        if process.stdin:
            try:
                process.stdin.write("q\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

    try:
        while process.poll() is None:
            if stop_event is not None and stop_event.wait(timeout=0.25):
                if stop_event_kind == "manual" or getattr(stop_event, "recording_stop_kind", None) == "manual":
                    manual_stop = True
                else:
                    service_stop = True
                request_graceful_stop()
                break
            if progress is not None:
                snapshot = progress.snapshot(startup_timeout=startup_timeout_seconds, stall_timeout=stall_timeout_seconds)
                if progress_callback is not None and time.monotonic() - last_report >= 2:
                    progress_callback(snapshot)
                    last_report = time.monotonic()
                if snapshot['state'] == 'stalled':
                    stalled = True
                    request_graceful_stop()
                    break
            if stop_event is None:
                time.sleep(0.25)
            if (
                max_runtime_seconds is not None
                and time.monotonic() - started_monotonic
                >= max_runtime_seconds + max(0.0, wall_clock_grace_seconds)
            ):
                time_limit_stop = True
                request_graceful_stop()
                break
        if process.poll() is None:
            try:
                return_code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=10)
        else:
            return_code = process.returncode
    except KeyboardInterrupt:
        manual_stop = True
        request_graceful_stop()
        try:
            return_code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait(timeout=10)
    finally:
        if process.stdin:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        collector.join()
        if progress is not None:
            progress.close()
            if process.stdout:
                process.stdout.close()
        if process.stderr:
            process.stderr.close()
    tail = collector.tail()
    if stalled:
        return_code = return_code or -1
        tail += '\nmedia_progress_stalled: input stopped producing advancing media.'
    return return_code, manual_stop, service_stop, time_limit_stop, tail


def _record_single_room_once(
    config: RecorderConfig,
    *,
    stream_info: StreamInfo | None = None,
    stop_event: threading.Event | None = None,
    stop_event_kind: str = "service",
    deadline_monotonic: float | None = None,
) -> RecordingResult:
    config = config.validated()
    ffmpeg = resolve_executable(config.ffmpeg_path, "ffmpeg")
    try:
        ffprobe = resolve_executable(config.ffprobe_path, "ffprobe")
    except EnvironmentError:
        ffprobe = None

    check_free_space(config.output_root, config.min_free_space_gb)
    ledger = RunLedger(config.output_root)
    created_at = local_now()

    stream = stream_info or resolve_douyin_room_sync(config.room_url, config.requested_quality)
    canonical, room_id = normalize_douyin_room_url(stream.canonical_room_url)
    stream.canonical_room_url = canonical
    stream.room_id = room_id
    task_id = stable_task_id(canonical)

    ledger.task_snapshot(
        _task_snapshot(
            task_id=task_id,
            stream=stream,
            config=config,
            task_state="checking",
            created_at=created_at,
        )
    )
    ledger.event("room_checked", task_id=task_id, message="Public room status was checked.")

    if not stream.is_live:
        ledger.task_snapshot(
            _task_snapshot(
                task_id=task_id,
                stream=stream,
                config=config,
                task_state="stopped",
                created_at=created_at,
            )
        )
        ledger.event("not_live", task_id=task_id, message="The room was not live at the observation time.")
        ledger.rebuild_project_manifest()
        return RecordingResult(
            task_id=task_id,
            session_id=None,
            outcome="not_live",
            completion_status=None,
            valid_mp4_count=0,
            segment_count=0,
            actual_media_duration_seconds=0.0,
            output_root=str(config.output_root),
            test_only=config.test_mode,
        )

    if not stream.stream_url:
        raise ResolveError("live stream data did not include a usable media URL")

    session_id = f"ses-{uuid.uuid4().hex}"
    first_live_observed_at = local_now()
    naming = export_info('recording', observed_at=first_live_observed_at, shop=stream.streamer_name,
        room_url=stream.canonical_room_url, batch_id=session_id[4:])
    naming['session_id'] = session_id
    media_dir = config.output_root / "03_直播录屏"
    media_dir.mkdir(parents=True, exist_ok=True)
    base_name = naming['package_name'] + '_片段'
    output_pattern = media_dir / f"{base_name}_%03d.ts"
    write_json_atomic(ledger.data_dir / f'export_{session_id}.json', naming)

    ledger.task_snapshot(
        _task_snapshot(
            task_id=task_id,
            stream=stream,
            config=config,
            task_state="recording",
            created_at=created_at,
        )
    )
    ledger.event(
        "recording_started",
        task_id=task_id,
        session_id=session_id,
        message="FFmpeg recording started.",
    )

    metrics_collector: RoomMetricsCollector | None = None
    if config.collect_room_metrics:
        metrics_collector = RoomMetricsCollector(
            room_url=stream.canonical_room_url,
            output_path=ledger.data_dir / "room_metrics.jsonl",
            recording_started_epoch_ms=int(first_live_observed_at.timestamp() * 1000),
            interval_seconds=config.room_metrics_interval_seconds,
        )
        metrics_collector.start()
        ledger.event(
            "room_metrics_started",
            task_id=task_id,
            session_id=session_id,
            message="Browser-free room metric polling started.",
        )

    command = build_ffmpeg_record_command(
        ffmpeg=ffmpeg,
        stream_url=stream.stream_url,
        output_pattern=output_pattern,
        segment_seconds=config.segment_duration_seconds,
        split_enabled=config.split_enabled,
        max_runtime_seconds=config.max_runtime_seconds,
    )
    return_code: int | None = None
    manual_stop = False
    service_stop = False
    time_limit_stop = False
    stderr_tail = ""
    start_failed = False
    def report_progress(snapshot):
        try:
            write_json_atomic(ledger.data_dir / 'recording_progress.json', {
                **snapshot, 'updated_at': iso_time(local_now()), 'session_id': session_id,
                'task_id': task_id,
            })
        except OSError:
            pass  # A status readout must never terminate an otherwise writable recording.
    try:
        budget = config.max_runtime_seconds if deadline_monotonic is None else max(0.0, deadline_monotonic - time.monotonic())
        if budget is not None and budget <= 0:
            return_code, time_limit_stop = 0, True
        else:
            return_code, manual_stop, service_stop, time_limit_stop, stderr_tail = _run_ffmpeg_process(
                command,
                secrets=(stream.stream_url, str(config.output_root), str(media_dir)),
                stop_event=stop_event,
                stop_event_kind=stop_event_kind,
                max_runtime_seconds=budget,
                wall_clock_grace_seconds=FFMPEG_TIME_LIMIT_WALL_GRACE_SECONDS if deadline_monotonic is None else 0,
                watch_progress=True,
                progress_callback=report_progress,
            )
    except OSError as exc:
        start_failed = True
        stderr_tail = redact_text(str(exc), secrets=(str(config.output_root), str(media_dir)))
    finally:
        if metrics_collector is not None:
            metrics_collector.stop()
            ledger.event(
                "room_metrics_stopped",
                task_id=task_id,
                session_id=session_id,
                message=(
                    "Browser-free room metric polling stopped with "
                    f"{metrics_collector.sample_count} snapshot(s)."
                ),
            )

    recording_ended_at = local_now()
    raw_segments = sorted(media_dir.glob(f"{base_name}_*.ts"))
    segment_records: list[dict[str, Any]] = []
    conversion_failed = False
    timeline_cursor = first_live_observed_at

    for sequence, raw_path in enumerate(raw_segments, start=1):
        mp4_path = raw_path.with_suffix(".mp4")
        remux = _run_hidden(
            build_ffmpeg_remux_command(ffmpeg=ffmpeg, source=raw_path, destination=mp4_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        conversion_status = "converted" if remux.returncode == 0 else "failed"
        if remux.returncode != 0:
            conversion_failed = True
            ledger.event(
                "conversion_failed",
                task_id=task_id,
                session_id=session_id,
                message=f"Segment {sequence} could not be remuxed to MP4.",
                detail=redact_text(
                    remux.stderr[-2_000:],
                    secrets=(stream.stream_url, str(config.output_root), str(raw_path), str(mp4_path)),
                ),
            )

        probe_target = mp4_path if mp4_path.is_file() and mp4_path.stat().st_size > 0 else raw_path
        probe = probe_media(
            path=probe_target,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            full_read_check=config.full_read_check,
        )
        validation_status, short_fragment = media_validation_status(
            probe, target_seconds=config.segment_duration_seconds
        )
        if probe_target == raw_path and conversion_status == "failed" and validation_status in VALID_MEDIA_STATUSES:
            conversion_failed = True

        duration = probe.duration_seconds
        segment_started_at = timeline_cursor if duration is not None else None
        segment_ended_at = (
            timeline_cursor + timedelta(seconds=duration) if duration is not None else None
        )
        if segment_ended_at is not None:
            timeline_cursor = segment_ended_at

        original_path: Path | None = raw_path
        if conversion_status == "converted" and validation_status in VALID_MEDIA_STATUSES:
            if config.retain_original:
                original_dir = media_dir / "original"
                original_dir.mkdir(parents=True, exist_ok=True)
                destination = original_dir / raw_path.name
                shutil.move(str(raw_path), str(destination))
                original_path = destination
            else:
                raw_path.unlink()
                original_path = None

        media_path = mp4_path if mp4_path.is_file() else probe_target
        record = {
            "segment_id": f"seg-{uuid.uuid4().hex}",
            "session_id": session_id,
            "sequence": sequence,
            "started_at": iso_time(segment_started_at),
            "ended_at": iso_time(segment_ended_at),
            "timeline_basis": "media_duration_from_first_observed_recording_start",
            "target_duration_seconds": config.segment_duration_seconds,
            "actual_duration_seconds": round(duration, 3) if duration is not None else None,
            "relative_mp4_path": relative_posix(mp4_path, config.output_root)
            if mp4_path.is_file()
            else None,
            "relative_original_path": relative_posix(original_path, config.output_root)
            if original_path and original_path.is_file()
            else None,
            "file_size_bytes": media_path.stat().st_size if media_path.is_file() else None,
            "container": probe.container,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "width": probe.width,
            "height": probe.height,
            "requested_quality": stream.requested_quality,
            "actual_quality": stream.actual_quality,
            "short_fragment": short_fragment,
            "media_validation_status": validation_status,
            "conversion_status": conversion_status,
            "sustained_read_ok": probe.sustained_read_ok,
            "sha256": file_sha256(media_path)
            if config.compute_sha256 and media_path.is_file()
            else None,
            "test_only": config.test_mode,
        }
        ledger.segment(record)
        segment_records.append(record)
        ledger.event(
            "segment_finalized",
            task_id=task_id,
            session_id=session_id,
            message=f"Segment {sequence} finalized with status {validation_status}.",
        )

    valid_records = [
        row
        for row in segment_records
        if row.get("media_validation_status") in VALID_MEDIA_STATUSES
        and (row.get("relative_mp4_path") or row.get("relative_original_path"))
    ]
    valid_mp4_count = sum(
        1
        for row in segment_records
        if row.get("relative_mp4_path")
        and row.get("media_validation_status") in VALID_MEDIA_STATUSES
    )
    has_media = bool(valid_records)
    actual_media_duration = sum(
        float(row["actual_duration_seconds"])
        for row in valid_records
        if isinstance(row.get("actual_duration_seconds"), (int, float))
    )
    if (
        config.max_runtime_seconds is not None
        and not manual_stop
        and not service_stop
        and actual_media_duration >= config.max_runtime_seconds
    ):
        time_limit_stop = True
    completion_status, issue_codes = select_completion_status(
        has_media=has_media,
        storage_failed=False,
        conversion_failed=conversion_failed,
        ffmpeg_return_code=return_code,
        manual_stop=manual_stop,
        service_stop=service_stop,
        time_limit_stop=time_limit_stop,
        offline_confirmed=config.confirm_eof_as_offline,
    )
    if start_failed:
        completion_status = "failed_no_media"
        issue_codes = ["ffmpeg_start_failed"]

    unknown_gap_count = 0
    if completion_status == "partial_disconnect":
        unknown_gap_count = 1
        ledger.gap(
            {
                "gap_id": f"gap-{uuid.uuid4().hex}",
                "session_id": session_id,
                "started_at": iso_time(recording_ended_at),
                "recovered_at": None,
                "gap_seconds": None,
                "duration_status": "unknown",
                "error_category": "source_or_process_ended",
                "recovery_status": "gap_not_recovered_at_session_end",
                "test_only": config.test_mode,
            }
        )

    end_reason = (
        "manual_stop"
        if manual_stop
        else "service_stop"
        if service_stop
        else "time_limit"
        if time_limit_stop
        else "confirmed_source_end"
        if config.confirm_eof_as_offline and return_code == 0
        else "source_or_process_ended"
    )
    session_record = {
        "session_id": session_id,
        "task_id": task_id,
        "first_live_observed_at": iso_time(first_live_observed_at),
        "recording_started_at": iso_time(first_live_observed_at),
        "last_live_observed_at": iso_time(first_live_observed_at),
        "recording_ended_at": iso_time(recording_ended_at),
        "end_reason": end_reason,
        "completion_status": completion_status,
        "issue_codes": issue_codes,
        "segment_count": len(segment_records),
        "valid_mp4_count": valid_mp4_count,
        "known_gap_count": 0,
        "unknown_gap_count": unknown_gap_count,
        "actual_media_duration_seconds": round(actual_media_duration, 3),
        "requested_quality": stream.requested_quality,
        "actual_quality": stream.actual_quality,
        "source_type": stream.source_type,
        "max_runtime_seconds": config.max_runtime_seconds,
        "room_metric_sample_count": (
            metrics_collector.sample_count if metrics_collector is not None else 0
        ),
        "room_metric_failure_count": (
            metrics_collector.failure_count if metrics_collector is not None else 0
        ),
        "test_only": config.test_mode,
    }
    ledger.session(session_record)
    ledger.task_snapshot(
        _task_snapshot(
            task_id=task_id,
            stream=stream,
            config=config,
            task_state="stopped" if has_media else "error",
            created_at=created_at,
        )
    )
    ledger.event(
        "recording_finished",
        task_id=task_id,
        session_id=session_id,
        message=f"Recording finished with status {completion_status}.",
        detail=stderr_tail[-2_000:] if stderr_tail else None,
    )
    ledger.rebuild_project_manifest()

    retryable_startup_failure = is_retryable_ffmpeg_startup_failure(
        stderr_tail,
        has_media=has_media,
        manual_stop=manual_stop,
        service_stop=service_stop,
        time_limit_stop=time_limit_stop,
    )

    return RecordingResult(
        task_id=task_id,
        session_id=session_id,
        outcome="recorded" if has_media else "failed",
        completion_status=completion_status,
        valid_mp4_count=valid_mp4_count,
        segment_count=len(segment_records),
        actual_media_duration_seconds=round(actual_media_duration, 3),
        output_root=str(config.output_root),
        test_only=config.test_mode,
        retryable_startup_failure=retryable_startup_failure,
        retryable_stream_failure=(
            not manual_stop and not service_stop and not time_limit_stop and not conversion_failed
            and (has_media or 'media_progress_stalled' in stderr_tail.lower())
            and any(marker in stderr_tail.lower() for marker in (
                'media_progress_stalled', 'stream ends prematurely', 'connection reset',
                'connection timed out', 'error during demuxing: i/o error',
            ))
        ),
    )


def _record_with_startup_retry(
    config: RecorderConfig,
    *,
    stream_info: StreamInfo | None = None,
    stop_event: threading.Event | None = None,
    stop_event_kind: str = "service",
    deadline_monotonic: float | None = None,
) -> RecordingResult:
    """Record once, with one bounded fresh-resolution retry for startup EOF."""

    config = config.validated()
    first_result = _record_single_room_once(
        config,
        stream_info=stream_info,
        stop_event=stop_event,
        stop_event_kind=stop_event_kind,
        deadline_monotonic=deadline_monotonic,
    )
    if not first_result.retryable_startup_failure:
        return first_result
    if deadline_monotonic is not None and deadline_monotonic - time.monotonic() <= STARTUP_RETRY_BACKOFF_SECONDS:
        return first_result

    ledger = RunLedger(config.output_root)
    ledger.event(
        "startup_retry_scheduled",
        task_id=first_result.task_id,
        session_id=first_result.session_id,
        message="A zero-media transient input failure triggered one bounded fresh-resolution retry.",
    )
    if stop_event is not None:
        if stop_event.wait(timeout=STARTUP_RETRY_BACKOFF_SECONDS):
            ledger.event(
                "startup_retry_cancelled",
                task_id=first_result.task_id,
                session_id=first_result.session_id,
                message="The bounded startup retry was cancelled by a stop request.",
            )
            ledger.rebuild_project_manifest()
            return first_result
    elif STARTUP_RETRY_BACKOFF_SECONDS > 0:
        time.sleep(STARTUP_RETRY_BACKOFF_SECONDS)

    ledger.event(
        "startup_retry_started",
        task_id=first_result.task_id,
        session_id=first_result.session_id,
        message="The room is being resolved again before the final startup attempt.",
    )
    try:
        retry_result = _record_single_room_once(
            config,
            stream_info=None,
            stop_event=stop_event,
            stop_event_kind=stop_event_kind,
            deadline_monotonic=deadline_monotonic,
        )
    except (RecorderError, OSError, ValueError) as exc:
        ledger.event(
            "startup_retry_resolve_failed",
            task_id=first_result.task_id,
            session_id=first_result.session_id,
            message="The final startup attempt could not resolve or start the public room.",
            detail=getattr(exc, "reason_code", "startup_retry_failed"),
        )
        ledger.rebuild_project_manifest()
        return first_result

    ledger.event(
        "startup_retry_succeeded" if retry_result.valid_mp4_count else "startup_retry_exhausted",
        task_id=retry_result.task_id,
        session_id=retry_result.session_id,
        message=(
            "The final startup attempt produced verified media."
            if retry_result.valid_mp4_count
            else "The single bounded startup retry ended without verified media."
        ),
    )
    ledger.rebuild_project_manifest()
    return retry_result


def record_single_room(config: RecorderConfig, *, stream_info: StreamInfo | None = None,
                       stop_event: threading.Event | None = None, stop_event_kind: str = 'service') -> RecordingResult:
    """Keep one original wall-clock deadline; preserve every interrupted attempt."""
    config = config.validated()
    deadline = time.monotonic() + config.max_runtime_seconds if config.max_runtime_seconds else None
    result = _record_with_startup_retry(config, stream_info=stream_info, stop_event=stop_event,
        stop_event_kind=stop_event_kind, deadline_monotonic=deadline)
    attempts = [result]
    ledger = RunLedger(config.output_root)
    for retry_index in range(1, MAX_STREAM_RECOVERY_ATTEMPTS + 1):
        if not result.retryable_stream_failure or deadline is None or (stop_event and stop_event.is_set()):
            break
        remaining = int(deadline - time.monotonic() - STREAM_RECOVERY_BACKOFF_SECONDS)
        if remaining < MIN_MAX_RUNTIME_SECONDS:
            break
        ledger.event('stream_recovery_scheduled', task_id=result.task_id, session_id=result.session_id,
                     message=f'Bounded stream recovery {retry_index}/{MAX_STREAM_RECOVERY_ATTEMPTS}; original deadline unchanged.')
        write_json_atomic(ledger.data_dir / 'recording_progress.json', {
            'state': 'reconnecting', 'retry_index': retry_index, 'retry_limit': MAX_STREAM_RECOVERY_ATTEMPTS,
            'updated_at': iso_time(local_now()), 'task_id': result.task_id,
            'saved_media_seconds': round(sum(a.actual_media_duration_seconds for a in attempts), 3),
        })
        if stop_event is not None:
            if stop_event.wait(timeout=STREAM_RECOVERY_BACKOFF_SECONDS):
                break
        elif STREAM_RECOVERY_BACKOFF_SECONDS:
            time.sleep(STREAM_RECOVERY_BACKOFF_SECONDS)
        remaining = int(deadline - time.monotonic())
        if remaining < MIN_MAX_RUNTIME_SECONDS or (stop_event and stop_event.is_set()):
            break
        try:
            # Resolve the same public room afresh, no cookie/session takeover and no stale URL replay.
            result = _record_single_room_once(config,
                stream_info=None, stop_event=stop_event, stop_event_kind=stop_event_kind, deadline_monotonic=deadline)
        except (RecorderError, OSError, ValueError) as error:
            ledger.event('stream_recovery_failed', task_id=result.task_id, session_id=result.session_id,
                         message='Recovery could not resolve or start the same public room.',
                         detail=getattr(error, 'reason_code', 'stream_recovery_failed'))
            break
        attempts.append(result)
        ledger.event('stream_recovery_attempt_finished', task_id=result.task_id, session_id=result.session_id,
                     message=f'Recovery attempt finished: {result.completion_status or result.outcome}.')
    ledger.rebuild_project_manifest()
    if len(attempts) == 1:
        return result
    valid_count = sum(a.valid_mp4_count for a in attempts)
    return replace(attempts[-1], outcome='recorded' if valid_count else 'failed',
        session_id=next((a.session_id for a in reversed(attempts) if a.session_id), None),
        completion_status='partial_disconnect' if valid_count else 'failed_no_media',
        segment_count=sum(a.segment_count for a in attempts), valid_mp4_count=valid_count,
        actual_media_duration_seconds=round(sum(a.actual_media_duration_seconds for a in attempts), 3),
        retryable_startup_failure=False, retryable_stream_failure=False)


def result_as_dict(result: RecordingResult) -> dict[str, Any]:
    return asdict(result)
