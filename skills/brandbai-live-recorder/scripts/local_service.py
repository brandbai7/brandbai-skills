"""Loopback-only task service for the BrandBAI live recorder prototype."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, quote

from recorder_core import (
    TOOL_VERSION,
    create_session_output_root,
    InputError,
    RecorderConfig,
    RecorderError,
    RecordingResult,
    iso_time,
    local_now,
    normalize_douyin_room_url,
    record_single_room,
    redact_text,
    stable_task_id,
    validate_segment_duration,
)
from runtime_support import RuntimeSetupError
from product_evidence import validate_snapshot, card_id, check_detail_binding, write_product_evidence
from material_contract import validate_catalog
from product_downloads import ProductDownloadJobs, DownloadError, observed_products
from product_reviews import ProductReviewJobs
from interaction_export import write_interaction_export
from browser_delivery import BrowserDeliveries, DeliveryError


SERVICE_VERSION = TOOL_VERSION
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
EXTENSION_SESSION_TTL_SECONDS = 900
MAX_EXTENSION_SESSIONS = 4
EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")
PAIR_ACTIONS = {"extension-popup", "user-click"}
ACTIVE_STATES = {"queued", "checking", "recording", "stopping"}
FINAL_STATES = {"complete", "partial", "not_live", "failed", "stopped"}
ALLOWED_REQUEST_KEYS = {
    "room_url",
    "mode",
    "quality",
    "max_runtime_seconds",
    "split_enabled",
    "segment_duration_seconds",
    "retain_original",
    "test_mode",
    "full_read_check",
    "sha256",
    "authorized_public_content",
    "collect_comments",
    "collect_product_cards",
    "collect_room_metrics",
}
COLLECTOR_OPTION_KEYS = {
    "collect_comments",
    "collect_product_cards",
    "collect_room_metrics",
}
VISIBLE_EVENT_TYPES = {
    "comment_visible",
    "product_state",
    "product_detail",
    "product_list_item",
    "room_snapshot",
    "collector_status",
}
COLLECTOR_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_VISIBLE_EVENTS_PER_BATCH = 50
VISIBLE_EVENT_KEYS = {
    "sequence",
    "event_type",
    "observed_at_epoch_ms",
    "room_url",
    "payload",
}
CONTROL_TEXT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ServiceError(RuntimeError):
    """Base service error with an HTTP-friendly status code."""

    status_code = 500


class ServiceInputError(ServiceError):
    status_code = 400


class ServiceConflictError(ServiceError):
    status_code = 409


class ServiceNotFoundError(ServiceError):
    status_code = 404


class ServiceUnauthorizedError(ServiceError):
    status_code = 401


class ServiceOriginError(ServiceError):
    status_code = 403


def is_extension_origin(origin: str | None) -> bool:
    if not origin:
        return False
    parts = urlsplit(origin)
    return (
        parts.scheme == "chrome-extension"
        and bool(EXTENSION_ID_RE.fullmatch(parts.netloc))
        and not parts.path.strip("/")
    )


def extension_id_from_origin(origin: str | None) -> str | None:
    if not is_extension_origin(origin):
        return None
    return urlsplit(str(origin)).netloc


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def load_or_create_token(state_dir: Path) -> tuple[str, bool]:
    state_dir = state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    token_path = state_dir / "auth_token.txt"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ServiceInputError("the existing service token is invalid")
        return token, False
    token = secrets.token_urlsafe(32)
    try:
        with token_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(token + "\n")
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
    except FileExistsError:
        token = token_path.read_text(encoding="utf-8").strip()
    return token, True


def select_output_directory(initial_directory: Path) -> Path | None:
    """Open the user-initiated native folder picker without exposing a path input API."""

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise ServiceError("native folder selection is unavailable") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update_idletasks()
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=str(initial_directory),
            mustexist=False,
            title="选择 BrandBAI 直播录屏保存位置",
        )
    finally:
        root.destroy()
    return Path(selected) if selected else None


class RecordingSettings:
    """Persist the customer-selected output root outside every recording delivery."""

    def __init__(
        self,
        settings_path: Path,
        *,
        default_output_root: Path,
        disallowed_roots: tuple[Path, ...] = (),
        directory_selector: Callable[[Path], Path | None] = select_output_directory,
    ):
        self.settings_path = settings_path.expanduser().resolve()
        self.default_output_root = default_output_root.expanduser().resolve()
        self.disallowed_roots = tuple(path.expanduser().resolve() for path in disallowed_roots)
        self.directory_selector = directory_selector
        self._lock = threading.RLock()

    def _read(self) -> tuple[Path, bool]:
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            value = payload.get("output_root")
            confirmed = payload.get("output_root_confirmed") is True
            if not isinstance(value, str) or not value.strip() or not confirmed:
                return self.default_output_root, False
            return self._validated_root(Path(value)), True
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return self.default_output_root, False

    def _validated_root(self, value: Path) -> Path:
        candidate = value.expanduser().resolve()
        for blocked in self.disallowed_roots:
            if candidate == blocked or blocked in candidate.parents:
                raise ServiceInputError("recordings cannot be saved inside the private state directory")
        candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.is_dir():
            raise ServiceInputError("the selected recording location is not a directory")
        return candidate

    def _write(self, output_root: Path) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        staged.write_text(
            json.dumps(
                {
                    "schema_version": "brandbai-live-recorder/settings/1",
                    "output_root": str(output_root),
                    "output_root_confirmed": True,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(staged, self.settings_path)

    @staticmethod
    def _display_path(path: Path) -> str:
        parts = [part for part in path.parts if part not in {path.anchor, "\\"}]
        return "\\".join(parts[-2:]) if parts else path.name

    def current_output_root(self) -> Path:
        with self._lock:
            output_root, _confirmed = self._read()
            return output_root

    def public(self) -> dict[str, Any]:
        with self._lock:
            output_root, confirmed = self._read()
            return {
                "configured": confirmed,
                "output_root": str(output_root),
                "display_path": self._display_path(output_root),
                "using_default": output_root == self.default_output_root,
                "applies_to_new_recordings_only": True,
            }

    def confirm_default(self) -> dict[str, Any]:
        with self._lock:
            output_root = self._validated_root(self.default_output_root)
            self._write(output_root)
            return self.public()

    def choose(self) -> tuple[dict[str, Any], bool]:
        with self._lock:
            initial = self.current_output_root()
            try:
                selected = self.directory_selector(initial)
            except Exception as exc:
                raise ServiceError("native folder selection failed") from exc
            if selected is None:
                return self.public(), True
            output_root = self._validated_root(selected)
            self._write(output_root)
            return self.public(), False


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    return is_extension_origin(origin)


class ExtensionSessionManager:
    """Issue short-lived, origin-bound tokens while storing token hashes only."""

    def __init__(
        self,
        *,
        ttl_seconds: int = EXTENSION_SESSION_TTL_SECONDS,
        max_sessions: int = MAX_EXTENSION_SESSIONS,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl_seconds <= 0:
            raise ServiceInputError("extension session TTL must be positive")
        if max_sessions <= 0:
            raise ServiceInputError("maximum extension sessions must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._lock = threading.RLock()
        self._bound_origin: str | None = None
        self._sessions: dict[str, tuple[str, str, float]] = {}

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _purge_expired(self, now: float) -> None:
        expired = [
            digest
            for digest, (_origin, _client_id, expiry) in self._sessions.items()
            if expiry <= now
        ]
        for digest in expired:
            self._sessions.pop(digest, None)

    def issue(self, origin: str | None, client_id: str | None) -> tuple[str, int]:
        if not is_extension_origin(origin):
            raise ServiceOriginError("one-click pairing requires a Chrome extension origin")
        assert origin is not None
        expected_client_id = extension_id_from_origin(origin)
        if not client_id or not expected_client_id or not hmac.compare_digest(client_id, expected_client_id):
            raise ServiceOriginError("extension client ID does not match the pairing origin")
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if self._bound_origin is None:
                self._bound_origin = origin
            elif not hmac.compare_digest(self._bound_origin, origin):
                raise ServiceOriginError(
                    "the service is already paired with another extension; restart it to change origin"
                )
            if len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions, key=lambda digest: self._sessions[digest][2])
                self._sessions.pop(oldest, None)
            token = secrets.token_urlsafe(32)
            self._sessions[self._digest(token)] = (origin, client_id, now + self.ttl_seconds)
            return token, self.ttl_seconds

    def validate(self, token: str, origin: str | None, client_id: str | None) -> bool:
        if not token or not client_id or not EXTENSION_ID_RE.fullmatch(client_id):
            return False
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            record = self._sessions.get(self._digest(token))
            if record is None:
                return False
            expected_origin, expected_client_id, expiry = record
            if not hmac.compare_digest(expected_client_id, client_id):
                return False
            if origin is not None and not (
                is_extension_origin(origin) and hmac.compare_digest(expected_origin, origin)
            ):
                return False
            return expiry > now


def validate_create_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceInputError("request body must be a JSON object")
    unknown = sorted(set(payload) - ALLOWED_REQUEST_KEYS)
    if unknown:
        raise ServiceInputError(f"unsupported request fields: {', '.join(unknown)}")
    if payload.get("authorized_public_content") is not True:
        raise ServiceInputError("authorized_public_content=true is required")
    if payload.get("mode", "immediate") != "immediate":
        raise ServiceInputError("this prototype only supports mode=immediate")

    try:
        canonical, room_id = normalize_douyin_room_url(str(payload.get("room_url") or ""))
    except InputError as exc:
        raise ServiceInputError(str(exc)) from exc
    quality = str(payload.get("quality", "SD")).upper()
    if quality not in {"SD", "HD", "OD"}:
        raise ServiceInputError("quality must be one of SD, HD, or OD")
    test_mode = payload.get("test_mode", False)
    if not isinstance(test_mode, bool):
        raise ServiceInputError("test_mode must be a boolean")
    split_enabled = payload.get("split_enabled", False)
    if not isinstance(split_enabled, bool):
        raise ServiceInputError("split_enabled must be a boolean")
    max_runtime_seconds = payload.get("max_runtime_seconds", 1800)
    if (
        isinstance(max_runtime_seconds, bool)
        or not isinstance(max_runtime_seconds, int)
    ):
        raise ServiceInputError("max_runtime_seconds must be a whole number of seconds")
    minimum_runtime = 10 if test_mode else 60
    if not minimum_runtime <= max_runtime_seconds <= 86400:
        if test_mode:
            raise ServiceInputError("test-mode recording duration must be between 10 and 86400 seconds")
        raise ServiceInputError("recording duration must be between 60 and 86400 seconds")
    if not split_enabled and max_runtime_seconds > 21600:
        raise ServiceInputError("recordings longer than 360 minutes must enable segmentation")
    duration = payload.get("segment_duration_seconds", 600)
    try:
        duration = validate_segment_duration(duration, test_mode=test_mode)
    except InputError as exc:
        raise ServiceInputError(str(exc)) from exc
    if split_enabled and duration > max_runtime_seconds:
        raise ServiceInputError("segment duration must not exceed total recording duration")
    for key in ("retain_original", "full_read_check", "sha256"):
        if key in payload and not isinstance(payload[key], bool):
            raise ServiceInputError(f"{key} must be a boolean")
    collector_options = validate_collector_options(payload, require_all=False)

    return {
        "room_url": canonical,
        "room_id": room_id,
        "mode": "immediate",
        "quality": quality,
        "max_runtime_seconds": max_runtime_seconds,
        "split_enabled": split_enabled,
        "segment_duration_seconds": duration,
        "retain_original": payload.get("retain_original", True),
        "test_mode": test_mode,
        "full_read_check": payload.get("full_read_check", False),
        "sha256": payload.get("sha256", False),
        **collector_options,
    }


def validate_collector_options(
    payload: Any,
    *,
    require_all: bool = True,
) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise ServiceInputError("collector options must be a JSON object")
    if require_all and set(payload) != COLLECTOR_OPTION_KEYS:
        raise ServiceInputError("collector options must include exactly three boolean fields")
    options: dict[str, bool] = {}
    for key in COLLECTOR_OPTION_KEYS:
        value = payload.get(key, False)
        if not isinstance(value, bool):
            raise ServiceInputError(f"{key} must be a boolean")
        options[key] = value
    return options


def _visible_text(
    value: Any,
    field: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ServiceInputError(f"{field} must be a string")
    text = value.strip()
    if not allow_empty and not text:
        raise ServiceInputError(f"{field} must not be empty")
    if len(text) > max_length:
        raise ServiceInputError(f"{field} is too long")
    if CONTROL_TEXT_RE.search(text):
        raise ServiceInputError(f"{field} contains control characters")
    if "http://" in text.lower() or "https://" in text.lower():
        raise ServiceInputError(f"{field} must not contain a URL")
    return text


def _optional_visible_text(value: Any, field: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    return _visible_text(value, field, max_length=max_length, allow_empty=True) or None


def _validate_event_payload(event_type: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceInputError("visible event payload must be a JSON object")
    if event_type == "comment_visible":
        allowed = {"masked_user", "text", "observation_kind"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ServiceInputError(f"unsupported comment fields: {', '.join(unknown)}")
        observation_kind = _visible_text(
            payload.get("observation_kind"), "observation_kind", max_length=32
        )
        if observation_kind not in {"baseline_visible", "new_visible"}:
            raise ServiceInputError("unsupported comment observation_kind")
        return {
            "masked_user": _visible_text(
                payload.get("masked_user"), "masked_user", max_length=80
            ),
            "text": _visible_text(payload.get("text"), "comment text", max_length=500),
            "observation_kind": observation_kind,
        }
    if event_type == "product_state":
        allowed = {"visible", "product_title", "display_price", "change_kind", "card_observation_id",
                   "product_url", "shop_name", "offer_texts", "images", "identity_status", "source", "fields_limited"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ServiceInputError(f"unsupported product fields: {', '.join(unknown)}")
        if not isinstance(payload.get("visible"), bool):
            raise ServiceInputError("product visible must be a boolean")
        change_kind = _visible_text(payload.get("change_kind"), "change_kind", max_length=40)
        if change_kind not in {
            "baseline_visible",
            "visible_product_changed",
            "visible_info_changed",
            "temporarily_not_visible",
            "restored_visible",
        }:
            raise ServiceInputError("unsupported product change_kind")
        title = _optional_visible_text(payload.get("product_title"), "product_title", max_length=300)
        price = _optional_visible_text(payload.get("display_price"), "display_price", max_length=80)
        if payload["visible"] and not title and not price:
            raise ServiceInputError("a visible product requires title or display price")
        result = {
            "visible": payload["visible"],
            "product_title": title,
            "display_price": price,
            "change_kind": change_kind,
        }
        if payload.get("card_observation_id") is not None:
            try:
                if payload["visible"]:
                    result.update(validate_snapshot(payload))
                else:
                    if set(payload) - {"visible", "product_title", "display_price", "change_kind", "card_observation_id"}:
                        raise ValueError("hidden card must not include product details")
                    result["card_observation_id"] = card_id(payload["card_observation_id"])
            except ValueError as exc:
                raise ServiceInputError(str(exc)) from exc
        elif set(payload) - {"visible", "product_title", "display_price", "change_kind"}:
            raise ServiceInputError("enhanced product fields require a card observation id")
        return result
    if event_type in {"product_detail", "product_list_item"}:
        try:
            return validate_snapshot(payload, detail=event_type == "product_detail", listing=event_type == "product_list_item")
        except ValueError as exc:
            raise ServiceInputError(str(exc)) from exc
    if event_type == "room_snapshot":
        allowed = {
            "account_name",
            "online_viewers",
            "likes_display",
            "hour_rank",
            "visible_comment_pairs",
            "product_card_visible",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ServiceInputError(f"unsupported room snapshot fields: {', '.join(unknown)}")
        for field in ("online_viewers", "visible_comment_pairs"):
            value = payload.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ServiceInputError(f"{field} must be a non-negative integer or null")
        card_visible = payload.get("product_card_visible")
        if card_visible is not None and not isinstance(card_visible, bool):
            raise ServiceInputError("product_card_visible must be a boolean or null")
        return {
            "account_name": _optional_visible_text(
                payload.get("account_name"), "account_name", max_length=120
            ),
            "online_viewers": payload.get("online_viewers"),
            "likes_display": _optional_visible_text(
                payload.get("likes_display"), "likes_display", max_length=80
            ),
            "hour_rank": _optional_visible_text(
                payload.get("hour_rank"), "hour_rank", max_length=80
            ),
            "visible_comment_pairs": payload.get("visible_comment_pairs"),
            "product_card_visible": card_visible,
        }
    if event_type == "collector_status":
        allowed = {
            "status",
            "reason",
            "collect_comments",
            "collect_product_cards",
            "collect_room_metrics",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ServiceInputError(f"unsupported collector status fields: {', '.join(unknown)}")
        status = _visible_text(payload.get("status"), "collector status", max_length=40)
        if status not in {
            "started",
            "stopped",
            "page_reloaded",
            "options_changed",
            "playback_paused",
            "playback_resume_requested",
            "playback_resumed",
            "playback_resume_failed",
            "interaction_interrupted", "interaction_resumed", "comment_stream_stale", "comment_stream_resumed",
            "popup_observation_paused", "popup_observation_resumed",
            "failed",
        }:
            raise ServiceInputError("unsupported collector status")
        collector_flags = {}
        for field in ("collect_comments", "collect_product_cards", "collect_room_metrics"):
            value = payload.get(field)
            if not isinstance(value, bool):
                raise ServiceInputError(f"{field} must be a boolean")
            collector_flags[field] = value
        if status in {
            "started",
            "page_reloaded",
            "options_changed",
            "playback_paused",
            "playback_resume_requested",
            "playback_resumed",
            "playback_resume_failed",
            "interaction_interrupted", "interaction_resumed", "comment_stream_stale", "comment_stream_resumed",
            "popup_observation_paused", "popup_observation_resumed",
        } and not any(
            collector_flags.values()
        ):
            raise ServiceInputError("an active collector status requires at least one enabled collector")
        if status in {'popup_observation_paused','popup_observation_resumed'} and not collector_flags['collect_product_cards']:
            raise ServiceInputError('popup observation status requires product collection')
        return {
            "status": status,
            "reason": _optional_visible_text(payload.get("reason"), "collector reason", max_length=300),
            **collector_flags,
        }
    raise ServiceInputError("unsupported visible event type")


def _parse_task_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def validate_visible_event_batch(
    payload: Any,
    task: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ServiceInputError("visible event batch must be a JSON object")
    unknown = sorted(set(payload) - {"collector_session_id", "events"})
    if unknown:
        raise ServiceInputError(f"unsupported visible batch fields: {', '.join(unknown)}")
    collector_session_id = str(payload.get("collector_session_id") or "")
    if not COLLECTOR_SESSION_RE.fullmatch(collector_session_id):
        raise ServiceInputError("collector_session_id must contain 8-64 safe characters")
    events = payload.get("events")
    if not isinstance(events, list) or not events or len(events) > MAX_VISIBLE_EVENTS_PER_BATCH:
        raise ServiceInputError(
            f"events must contain 1-{MAX_VISIBLE_EVENTS_PER_BATCH} items"
        )
    task_started = _parse_task_time(task.get("started_at"))
    task_ended = _parse_task_time(task.get("ended_at"))
    timezone_value = local_now().tzinfo
    normalized: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    for raw in events:
        if not isinstance(raw, dict):
            raise ServiceInputError("each visible event must be a JSON object")
        unknown_event = sorted(set(raw) - VISIBLE_EVENT_KEYS)
        if unknown_event:
            raise ServiceInputError(
                f"unsupported visible event fields: {', '.join(unknown_event)}"
            )
        sequence = raw.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= 1_000_000_000:
            raise ServiceInputError("event sequence must be a non-negative integer")
        if sequence in seen_sequences:
            raise ServiceInputError("event sequence is duplicated inside the batch")
        seen_sequences.add(sequence)
        event_type = str(raw.get("event_type") or "")
        if event_type not in VISIBLE_EVENT_TYPES:
            raise ServiceInputError("unsupported visible event type")
        observed_ms = raw.get("observed_at_epoch_ms")
        if isinstance(observed_ms, bool) or not isinstance(observed_ms, (int, float)):
            raise ServiceInputError("observed_at_epoch_ms must be a number")
        observed_ms = float(observed_ms)
        if not math.isfinite(observed_ms) or observed_ms <= 0:
            raise ServiceInputError("observed_at_epoch_ms must be a positive finite number")
        try:
            canonical_url, _room_id = normalize_douyin_room_url(str(raw.get("room_url") or ""))
        except InputError as exc:
            raise ServiceInputError(str(exc)) from exc
        if not hmac.compare_digest(canonical_url, str(task["room_url"])):
            raise ServiceConflictError("visible event room does not match the recording task")
        event_payload = _validate_event_payload(event_type, raw.get("payload"))
        observed = datetime.fromtimestamp(observed_ms / 1000.0, tz=timezone_value)
        offset = None
        alignment_status = "task_start_unavailable"
        within_window = False
        if task_started is not None:
            offset = round((observed - task_started).total_seconds(), 3)
            alignment_status = "wall_clock_approximate_uncalibrated"
            within_window = offset >= 0 and (task_ended is None or observed <= task_ended)
        visible_event_id = "vpe-" + hashlib.sha256(
            f"{task['task_id']}:{collector_session_id}:{sequence}".encode("utf-8")
        ).hexdigest()[:20]
        normalized.append(
            {
                "visible_event_id": visible_event_id,
                "task_id": task["task_id"],
                "collector_session_id": collector_session_id,
                "sequence": sequence,
                "event_type": event_type,
                "observed_at_epoch_ms": round(observed_ms, 3),
                "observed_at": observed.isoformat(),
                "received_at": iso_time(local_now()),
                "recording_offset_seconds": offset,
                "within_recording_window": within_window,
                "time_alignment_status": alignment_status,
                "room_url": canonical_url,
                "payload": event_payload,
                "completeness": "page_visible_first_observation_only",
            }
        )
    return collector_session_id, normalized


class TaskStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    room_url TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    max_runtime_seconds INTEGER,
                    split_enabled INTEGER NOT NULL DEFAULT 1,
                    segment_duration_seconds INTEGER NOT NULL,
                    retain_original INTEGER NOT NULL,
                    test_only INTEGER NOT NULL,
                    full_read_check INTEGER NOT NULL,
                    compute_sha256 INTEGER NOT NULL,
                    collect_comments INTEGER NOT NULL DEFAULT 0,
                    collect_product_cards INTEGER NOT NULL DEFAULT 0,
                    collect_room_metrics INTEGER NOT NULL DEFAULT 0,
                    output_dir TEXT,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    outcome TEXT,
                    completion_status TEXT,
                    segment_count INTEGER NOT NULL DEFAULT 0,
                    valid_mp4_count INTEGER NOT NULL DEFAULT 0,
                    actual_media_duration_seconds REAL NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS service_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visible_page_events (
                    visible_event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    collector_session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    observed_at_epoch_ms REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    recording_offset_seconds REAL,
                    within_recording_window INTEGER NOT NULL,
                    time_alignment_status TEXT NOT NULL,
                    room_url TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    UNIQUE(task_id, collector_session_id, sequence),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "max_runtime_seconds" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN max_runtime_seconds INTEGER"
                )
            if "split_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN split_enabled INTEGER NOT NULL DEFAULT 1"
                )
            if "output_dir" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN output_dir TEXT")
            for collector_column in COLLECTOR_OPTION_KEYS:
                if collector_column not in columns:
                    connection.execute(
                        f"ALTER TABLE tasks ADD COLUMN {collector_column} INTEGER NOT NULL DEFAULT 0"
                    )

    @staticmethod
    def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        for key in (
            "retain_original",
            "test_only",
            "full_read_check",
            "compute_sha256",
            "split_enabled",
            "collect_comments",
            "collect_product_cards",
            "collect_room_metrics",
        ):
            value[key] = bool(value.get(key))
        return value

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._public(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC, task_id ASC"
            ).fetchall()
        return [self._public(row) for row in rows]

    def interaction_health(self, task_id: str, started_ms: float) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            rows = connection.execute('''SELECT observed_at,payload_json FROM visible_page_events
                WHERE task_id=? AND observed_at_epoch_ms>=? AND event_type='collector_status'
                ORDER BY observed_at_epoch_ms DESC LIMIT 30''', (task_id, started_ms)).fetchall()
        for row in rows:
            payload = json.loads(row['payload_json'])
            if payload.get('status') == 'interaction_resumed' and payload.get('reason') == 'helper_connection_restored':
                continue  # Control transport recovery does not prove the page's comments resumed.
            if payload.get('status') in {'started', 'page_reloaded'}:
                return None
            if payload.get('status') in {'interaction_interrupted', 'interaction_resumed', 'comment_stream_stale', 'comment_stream_resumed', 'stopped', 'failed'}:
                return {'status': payload['status'], 'reason': payload.get('reason'), 'observed_at': row['observed_at']}
        return None

    def upsert_queued(self, task: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        task_id = stable_task_id(task["room_url"])
        now = iso_time(local_now())
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if existing and existing["state"] in ACTIVE_STATES:
                return self._public(existing), True
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, room_url, room_id, mode, quality,
                    max_runtime_seconds, split_enabled, segment_duration_seconds,
                    retain_original, test_only,
                    full_read_check, compute_sha256,
                    collect_comments, collect_product_cards, collect_room_metrics,
                    output_dir, state, created_at, updated_at,
                    started_at, ended_at, outcome, completion_status,
                    segment_count, valid_mp4_count, actual_media_duration_seconds, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, NULL, NULL, NULL, NULL, 0, 0, 0, NULL)
                ON CONFLICT(task_id) DO UPDATE SET
                    room_url=excluded.room_url,
                    room_id=excluded.room_id,
                    mode=excluded.mode,
                    quality=excluded.quality,
                    max_runtime_seconds=excluded.max_runtime_seconds,
                    split_enabled=excluded.split_enabled,
                    segment_duration_seconds=excluded.segment_duration_seconds,
                    retain_original=excluded.retain_original,
                    test_only=excluded.test_only,
                    full_read_check=excluded.full_read_check,
                    compute_sha256=excluded.compute_sha256,
                    collect_comments=excluded.collect_comments,
                    collect_product_cards=excluded.collect_product_cards,
                    collect_room_metrics=excluded.collect_room_metrics,
                    output_dir=excluded.output_dir,
                    state='queued',
                    updated_at=excluded.updated_at,
                    started_at=NULL,
                    ended_at=NULL,
                    outcome=NULL,
                    completion_status=NULL,
                    segment_count=0,
                    valid_mp4_count=0,
                    actual_media_duration_seconds=0,
                    last_error=NULL
                """,
                (
                    task_id,
                    task["room_url"],
                    task["room_id"],
                    task["mode"],
                    task["quality"],
                    task["max_runtime_seconds"],
                    int(task["split_enabled"]),
                    task["segment_duration_seconds"],
                    int(task["retain_original"]),
                    int(task["test_mode"]),
                    int(task["full_read_check"]),
                    int(task["sha256"]),
                    int(task["collect_comments"]),
                    int(task["collect_product_cards"]),
                    int(task["collect_room_metrics"]),
                    task["output_dir"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO service_events(task_id,event_type,occurred_at,message) VALUES(?,?,?,?)",
                (task_id, "task_queued", now, "Immediate recording task queued."),
            )
        row = self.get(task_id)
        if row is None:
            raise ServiceError("task persistence failed")
        return row, False

    def update_collector_options(
        self,
        task_id: str,
        options: dict[str, bool],
    ) -> dict[str, Any]:
        now = iso_time(local_now())
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ServiceNotFoundError("task not found")
            if row["state"] not in ACTIVE_STATES:
                raise ServiceConflictError("collector options can only change during an active task")
            connection.execute(
                """
                UPDATE tasks
                SET collect_comments = ?, collect_product_cards = ?, collect_room_metrics = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    int(options["collect_comments"]),
                    int(options["collect_product_cards"]),
                    int(options["collect_room_metrics"]),
                    now,
                    task_id,
                ),
            )
            connection.execute(
                "INSERT INTO service_events(task_id,event_type,occurred_at,message) VALUES(?,?,?,?)",
                (task_id, "collector_options_updated", now, "Collector option flags updated."),
            )
        updated = self.get(task_id)
        if updated is None:
            raise ServiceError("task persistence failed")
        return updated

    def update(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "state",
            "updated_at",
            "started_at",
            "ended_at",
            "outcome",
            "completion_status",
            "segment_count",
            "valid_mp4_count",
            "actual_media_duration_seconds",
            "last_error",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported task fields: {sorted(unknown)}")
        fields.setdefault("updated_at", iso_time(local_now()))
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [task_id]
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?", values
            )
            if cursor.rowcount != 1:
                raise ServiceNotFoundError("task not found")
        row = self.get(task_id)
        if row is None:
            raise ServiceNotFoundError("task not found")
        return row

    def event(self, task_id: str, event_type: str, message: str) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO service_events(task_id,event_type,occurred_at,message) VALUES(?,?,?,?)",
                (task_id, event_type, iso_time(local_now()), message),
            )

    @staticmethod
    def _public_visible_event(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        value["within_recording_window"] = bool(value["within_recording_window"])
        payload_value = value.pop("payload_json", "{}")
        value["payload"] = json.loads(payload_value)
        return value

    def add_visible_events(
        self,
        task_id: str,
        events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        inserted: list[dict[str, Any]] = []
        duplicates = 0
        with self._lock, self._connection() as connection:
            for event in events:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO visible_page_events (
                        visible_event_id, task_id, collector_session_id, sequence,
                        event_type, observed_at_epoch_ms, observed_at, received_at,
                        recording_offset_seconds, within_recording_window,
                        time_alignment_status, room_url, payload_json, completeness
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["visible_event_id"],
                        task_id,
                        event["collector_session_id"],
                        event["sequence"],
                        event["event_type"],
                        event["observed_at_epoch_ms"],
                        event["observed_at"],
                        event["received_at"],
                        event["recording_offset_seconds"],
                        int(event["within_recording_window"]),
                        event["time_alignment_status"],
                        event["room_url"],
                        json.dumps(event["payload"], ensure_ascii=False, sort_keys=True),
                        event["completeness"],
                    ),
                )
                if cursor.rowcount == 1:
                    inserted.append(event)
                else:
                    duplicates += 1
        return inserted, duplicates

    def list_visible_events(
        self,
        task_id: str,
        *,
        observed_at_epoch_ms_at_or_after: float | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            if observed_at_epoch_ms_at_or_after is None:
                rows = connection.execute(
                    """
                    SELECT * FROM visible_page_events
                    WHERE task_id = ?
                    ORDER BY observed_at_epoch_ms ASC, collector_session_id ASC, sequence ASC
                    """,
                    (task_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM visible_page_events
                    WHERE task_id = ? AND observed_at_epoch_ms >= ?
                    ORDER BY observed_at_epoch_ms ASC, collector_session_id ASC, sequence ASC
                    """,
                    (task_id, observed_at_epoch_ms_at_or_after),
                ).fetchall()
        return [self._public_visible_event(row) for row in rows]

    def visible_event_count(
        self,
        task_id: str,
        *,
        observed_at_epoch_ms_at_or_after: float | None = None,
    ) -> int:
        with self._lock, self._connection() as connection:
            if observed_at_epoch_ms_at_or_after is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM visible_page_events WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM visible_page_events
                    WHERE task_id = ? AND observed_at_epoch_ms >= ?
                    """,
                    (task_id, observed_at_epoch_ms_at_or_after),
                ).fetchone()
        return int(row["count"] if row else 0)

    def visible_event_counts(self, task_id: str, started_ms: float) -> dict[str, int]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT event_type, COUNT(*) AS n FROM visible_page_events "
                "WHERE task_id = ? AND observed_at_epoch_ms >= ? GROUP BY event_type",
                (task_id, started_ms)).fetchall()
        return {r['event_type']: int(r['n']) for r in rows}

    def recover_interrupted(self) -> int:
        now = iso_time(local_now())
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET state='partial', updated_at=?, ended_at=?, outcome='interrupted',
                    completion_status='partial_service_restart',
                    last_error='service restarted while task was active'
                WHERE state IN ('queued','checking','recording','stopping')
                """,
                (now, now),
            )
            return cursor.rowcount


RecorderCallable = Callable[..., RecordingResult]


@dataclass(slots=True)
class RunningTask:
    thread: threading.Thread
    stop_event: threading.Event


class TaskManager:
    def __init__(
        self,
        *,
        store: TaskStore,
        output_root: Path,
        recorder: RecorderCallable = record_single_room,
        runtime_preparer: Callable[[], object] | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        min_free_space_gb: float = 10.0,
        recording_settings: RecordingSettings | None = None,
    ):
        self.store = store
        self.output_root = output_root.expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.recorder = recorder
        self.runtime_preparer = runtime_preparer
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.min_free_space_gb = min_free_space_gb
        self.recording_settings = recording_settings
        self._running: dict[str, RunningTask] = {}
        self._lock = threading.RLock()
        self._visible_event_file_lock = threading.RLock()
        self.deliveries = BrowserDeliveries(self.store.database_path.parent / 'browser-deliveries')
        self.product_downloads = ProductDownloadJobs()
        self.product_reviews = ProductReviewJobs(auto_expire=True, on_finish=self._review_delivery_finished)
        self._independent_products: dict[str, str] = {}
        self.store.recover_interrupted()

    def _review_delivery_finished(self, ident, result):
        entry = self.deliveries.find('reviews:' + ident)
        if entry:
            self.deliveries.finish_existing(entry['id'], result)

    def _recording_delivery(self, row):
        value = row.get('output_dir')
        if not value:
            return None
        try:
            relative = Path(value).resolve().relative_to(self.deliveries.root.resolve())
            return self.deliveries.public(relative.parts[0])
        except (ValueError, IndexError):
            return None

    def prepare_delivery(self, ident):
        entry = self.deliveries.public(ident)
        if (entry['state'] == 'interrupted' and not entry.get('filename')) or entry.get('late_data_available'):
            return self.deliveries.pack(ident, material_status=entry.get('material_status') or 'partial_recovered',
                                        text_lock=self._visible_event_file_lock)
        return entry

    def _public_task(self, row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        stored_output = value.get("output_dir")
        task_dir = (
            Path(stored_output).expanduser().resolve()
            if stored_output
            else (self.output_root / value["task_id"]).resolve()
        )
        value["output_dir"] = str(task_dir) if task_dir.is_dir() else None
        total_event_count = self.store.visible_event_count(value["task_id"])
        current_started_at = value.get("started_at")
        current_event_count = 0
        if current_started_at:
            current_start_epoch_ms = datetime.fromisoformat(current_started_at).timestamp() * 1000
            current_event_count = self.store.visible_event_count(
                value["task_id"],
                observed_at_epoch_ms_at_or_after=current_start_epoch_ms,
            )
        value["visible_event_count"] = current_event_count
        value["visible_event_count_total"] = total_event_count
        value["visible_event_counts"] = self.store.visible_event_counts(value['task_id'], current_start_epoch_ms) if current_started_at else {}
        value['interaction_health'] = self.store.interaction_health(value['task_id'], current_start_epoch_ms) if current_started_at else None
        value['recording_health'] = None
        if value['state'] in ACTIVE_STATES:
            try:
                progress = json.loads((task_dir / 'data' / 'recording_progress.json').read_text(encoding='utf-8'))
                if progress.get('task_id') == value['task_id'] and progress.get('state') in {'receiving', 'connecting', 'stalled', 'reconnecting'}:
                    value['recording_health'] = progress
            except (OSError, ValueError):
                pass
        value['interaction_export_available'] = False
        value['recording_sections_available'] = False
        if value['state'] not in ACTIVE_STATES:
            try:
                report = json.loads((task_dir / '05_直播互动' / '完整性.json').read_text(encoding='utf-8'))
                value['interaction_export_available'] = (report.get('event_count') == current_event_count
                    and report.get('task_started_at') == current_started_at
                    and (task_dir / '05_直播互动' / '直播互动记录.csv').is_file()
                    and (task_dir / '05_直播互动' / '直播互动记录.md').is_file())
                value['recording_sections_available'] = bool(value['interaction_export_available'] and report.get('classified_sections'))
                if value['recording_sections_available']:
                    value['popup_observation_group_count'] = report.get('popup_observation_group_count', 0)
            except (OSError, ValueError):
                pass
        value["product_download"] = self.product_downloads.status((value["task_id"], current_started_at))
        value['product_download']['delivery'] = self.deliveries.find('recorded_products:' + value['task_id'] + ':' + str(current_started_at))
        value["product_download_available"] = bool(current_event_count and value["state"] not in ACTIVE_STATES and self._visible_event_path(value['task_id']).with_name('product_observations.jsonl').is_file())
        value['delivery'] = self._recording_delivery(row)
        return value

    def download_products(self, task_id: str, body: Any, *, browser_delivery=False) -> dict[str, Any]:
        # Client supplies only the exact recorded session, never paths or URLs.
        if not isinstance(body, dict) or set(body) != {'started_at'}:
            raise ServiceInputError('product download requires the selected recording session')
        with self._lock:
            row = self.store.get(task_id)
            if row is None: raise ServiceNotFoundError('task not found')
            if not row.get('started_at') or body['started_at'] != row['started_at']:
                raise ServiceConflictError('recording session changed; refresh results')
            if row['state'] in ACTIVE_STATES:
                raise ServiceConflictError('finish this recording before downloading its product package')
            started_ms = datetime.fromisoformat(row['started_at']).timestamp() * 1000
            events = self.store.list_visible_events(task_id, observed_at_epoch_ms_at_or_after=started_ms)
            if not observed_products(events):
                raise ServiceInputError('no product material was recorded in this session')
            root = self._visible_event_path(task_id).parent.parent
            entry = self.deliveries.create('recorded_products', 'recorded_products:' + task_id + ':' + row['started_at']) if browser_delivery else None
            if entry: root = self.deliveries.work_root(entry['id'])
            try:
                result = self.product_downloads.start((task_id, row['started_at']), root, events,
                    on_finish=(lambda result: self.deliveries.finish_existing(entry['id'], result)) if entry else None)
                return dict(result, delivery=self.deliveries.public(entry['id']) if entry else None)
            except DownloadError as exc:
                raise ServiceConflictError('a product download is already running or the service is stopping') from exc

    def download_current_product(self, body: Any, *, browser_delivery=False) -> dict[str, Any]:
        """Explicit, bounded current-panel download. Never creates a recording/event."""
        try:
            field = 'catalog' if isinstance(body, dict) and 'catalog' in body else 'snapshot'
            if not isinstance(body, dict) or set(body) != {'request_id', 'room_url', 'observed_at_epoch_ms', field}:
                raise ValueError('invalid product request')
            ident = body['request_id']
            if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}', ident):
                raise ValueError('invalid product request id')
            room, _ = normalize_douyin_room_url(body['room_url'])
            if room != body['room_url']: raise ValueError('canonical room required')
            at = body['observed_at_epoch_ms']
            if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or abs(time.time()*1000 - at) > 120000:
                raise ValueError('stale product observation')
            snapshot = validate_catalog(body[field]) if field == 'catalog' else validate_snapshot(body[field], standalone=True)
            from product_identity import validate_identity
            for item in snapshot['rows'] if field == 'catalog' else [snapshot]:
                if 'product_identity' in item: validate_identity(item['product_identity'], room_url=room)
        except (ValueError, TypeError, InputError) as exc:
            raise ServiceInputError('refresh and select the current public product') from exc
        if not browser_delivery and self.storage_settings().get('configured') is not True:
            raise ServiceConflictError('the recording location must be confirmed first')
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            previous = self._independent_products.get(ident)
            if previous and previous != fingerprint:
                raise ServiceConflictError('product request changed; select again')
            if previous:
                return self.current_product_download(ident)
            if len(self._independent_products) >= 500:
                raise ServiceConflictError('product request capacity reached')
            observation = dict(event_type='product_catalog_material' if field == 'catalog' else 'product_material', material_observation_id=ident,
                room_url=room, observed_at=datetime.fromtimestamp(at/1000).astimezone().isoformat(), payload=snapshot)
            restored = self.deliveries.find('product:' + ident) if browser_delivery else None
            entry = self.deliveries.create('catalog' if field == 'catalog' else 'product', 'product:' + ident,
                                          fingerprint=fingerprint) if browser_delivery else None
            if restored:
                return self.current_product_download(ident)
            root = self.deliveries.work_root(entry['id']) if entry else self._current_output_root().resolve()
            root.mkdir(parents=True, exist_ok=True)
            try:
                result = self.product_downloads.start(('product', ident), root, [observation],
                    on_finish=(lambda result: self.deliveries.finish_existing(entry['id'], result)) if entry else None)
            except DownloadError as exc:
                if entry: self.deliveries.fail(entry['id'], 'collection_not_started')
                raise ServiceConflictError('a product download is already running or the service is stopping') from exc
            self._independent_products[ident] = fingerprint
            return dict(result, request_id=ident, delivery=self.deliveries.public(entry['id']) if entry else None)

    def current_product_download(self, ident: str) -> dict[str, Any]:
        if ident not in self._independent_products:
            entry = self.deliveries.find('product:' + ident)
            if entry:
                return dict(state='unconfirmed', request_id=ident, delivery=entry,
                            message='助手已重启，可在下载与保存中恢复已有资料包。')
            raise ServiceNotFoundError('product download not found')
        return dict(self.product_downloads.status(('product', ident)), request_id=ident, delivery=self.deliveries.find('product:' + ident))

    def review_request(self, body: Any, ident: str | None = None, *, browser_delivery=False) -> dict[str, Any]:
        if not browser_delivery and not (ident and self.deliveries.find('reviews:' + ident)) and self.storage_settings().get('configured') is not True:
            raise ServiceConflictError('confirm the save location first')
        try:
            if ident:
                result = self.product_reviews.accept(ident, body)
            else:
                request_id = self.product_reviews.validate_start(body)[0]
                restored = self.deliveries.find('reviews:' + request_id) if browser_delivery else None
                entry = self.deliveries.create('reviews', 'reviews:' + request_id,
                    fingerprint=hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()) if browser_delivery else None
                if restored and request_id not in self.product_reviews.jobs:
                    raise ServiceConflictError('助手已重启，请在下载与保存中恢复已有评价；不会重新读取。')
                result = self.product_reviews.start(body, self.deliveries.work_root(entry['id']) if entry else self._current_output_root().resolve())
                if entry:
                    self.deliveries.source(entry['id'], result['output_dir'])
                ident = request_id
            return dict(result, delivery=self.deliveries.find('reviews:' + ident))
        except (ValueError, TypeError, KeyError) as exc:
            raise ServiceInputError('review source or request is no longer valid') from exc

    def review_status(self, ident: str) -> dict[str, Any]:
        try:
            return dict(self.product_reviews.status(ident), delivery=self.deliveries.find('reviews:' + ident))
        except ValueError as exc:
            raise ServiceNotFoundError('review download not found') from exc

    def stop_review(self, ident: str, body: Any) -> dict[str, Any]:
        self.review_status(ident)
        try:
            return dict(self.product_reviews.stop(ident, body), delivery=self.deliveries.find('reviews:' + ident))
        except (ValueError, TypeError, KeyError) as exc:
            raise ServiceInputError('review stop source is no longer valid') from exc

    def _visible_event_path(self, task_id: str) -> Path:
        row = self.store.get(task_id)
        if row is None:
            raise ServiceNotFoundError("task not found")
        stored_output = row.get("output_dir")
        task_dir = (
            Path(stored_output).expanduser().resolve()
            if stored_output
            else (self.output_root / task_id).resolve()
        )
        return task_dir / "data" / "visible_page_events.jsonl"

    def storage_settings(self) -> dict[str, Any]:
        if self.recording_settings is None:
            return {
                "configured": True,
                "output_root": str(self.output_root),
                "display_path": RecordingSettings._display_path(self.output_root),
                "using_default": True,
                "applies_to_new_recordings_only": True,
            }
        return self.recording_settings.public()

    def confirm_default_output_root(self) -> dict[str, Any]:
        if self.recording_settings is None:
            return self.storage_settings()
        return self.recording_settings.confirm_default()

    def choose_output_root(self) -> tuple[dict[str, Any], bool]:
        if self.recording_settings is None:
            raise ServiceError("recording location settings are unavailable")
        return self.recording_settings.choose()

    def _current_output_root(self) -> Path:
        if self.recording_settings is None:
            return self.output_root
        return self.recording_settings.current_output_root()

    def _append_visible_events(self, task_id: str, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        path = self._visible_event_path(task_id)
        with self._visible_event_file_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def _materialize_visible_events(self, task_id: str) -> None:
        row = self.store.get(task_id)
        started_at = row.get("started_at") if row else None
        started_epoch_ms = (
            datetime.fromisoformat(started_at).timestamp() * 1000 if started_at else None
        )
        path = self._visible_event_path(task_id)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with self._visible_event_file_lock:
            # Read under the same lock as append, so a simultaneous tail batch
            # cannot be overwritten by an older event snapshot.
            events = self.store.list_visible_events(task_id, observed_at_epoch_ms_at_or_after=started_epoch_ms)
            if not events:
                write_interaction_export(path.parent.parent, [], row or {})
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(temporary, path)
            try:
                write_product_evidence(path.parent.parent, events)
            except OSError:
                self.store.event(task_id, "product_export_failed", "Product summary could not be written; canonical events retained.")
            write_interaction_export(path.parent.parent, events, row or {})

    def _materialize_product_evidence(self, task_id: str) -> None:
        # Do not rewrite the live canonical JSONL on each product batch: a
        # simultaneous comment append must remain independent of this view.
        with self._visible_event_file_lock:
            row = self.store.get(task_id)
            started_at = row.get("started_at") if row else None
            started_ms = datetime.fromisoformat(started_at).timestamp() * 1000 if started_at else None
            events = self.store.list_visible_events(task_id, observed_at_epoch_ms_at_or_after=started_ms)
            try:
                write_product_evidence(self._visible_event_path(task_id).parent.parent, events)
            except OSError:
                self.store.event(task_id, "product_export_failed", "Product summary could not be written; canonical events retained.")

    def ingest_visible_events(self, task_id: str, payload: Any) -> dict[str, Any]:
        row = self.store.get(task_id)
        if row is None:
            raise ServiceNotFoundError("task not found")
        collector_session_id, normalized = validate_visible_event_batch(payload, row)
        if any(e["event_type"] == "product_detail" for e in normalized):
            try:
                check_detail_binding(self.store.list_visible_events(task_id) + normalized)
            except ValueError as exc:
                raise ServiceInputError(str(exc)) from exc
        with self._visible_event_file_lock:
            inserted, duplicates = self.store.add_visible_events(task_id, normalized)
            self._append_visible_events(task_id, inserted)
        if inserted and self.store.get(task_id)['state'] not in ACTIVE_STATES:
            # Late, accepted stop/comment events must also reach the readable view.
            try:
                self._materialize_visible_events(task_id)
            except OSError:
                self.store.event(task_id, 'interaction_export_failed', 'Readable interaction export failed; canonical events retained.')
            entry = self._recording_delivery(row)
            if entry:
                self.deliveries.mark_late_data(entry['id'])
        if any(e["event_type"] in {"product_state", "product_detail", "product_list_item"} for e in inserted):
            # Same materialization lock as the canonical event ledger; these
            # are collection deliverables, not a transcript or analysis.
            self._materialize_product_evidence(task_id)
        if inserted:
            self.store.event(
                task_id,
                "visible_event_batch",
                f"Accepted {len(inserted)} visible page event(s); {duplicates} duplicate(s).",
            )
        offsets = [
            event["recording_offset_seconds"]
            for event in inserted
            if event["recording_offset_seconds"] is not None
        ]
        return {
            "task_id": task_id,
            "collector_session_id": collector_session_id,
            "accepted": len(inserted),
            "duplicates": duplicates,
            "visible_event_count": self._public_task(row)["visible_event_count"],
            "visible_event_count_total": self.store.visible_event_count(task_id),
            "first_recording_offset_seconds": min(offsets) if offsets else None,
            "last_recording_offset_seconds": max(offsets) if offsets else None,
            "time_alignment_status": "wall_clock_approximate_uncalibrated",
        }

    def set_collector_options(self, task_id: str, payload: Any) -> dict[str, Any]:
        options = validate_collector_options(payload, require_all=True)
        return self._public_task(self.store.update_collector_options(task_id, options))

    def create(self, payload: Any, *, single_active_task: bool = False, browser_delivery=False) -> tuple[dict[str, Any], bool]:
        task = validate_create_request(payload)
        previous = self.store.get(stable_task_id(task['room_url']))
        if previous and previous['state'] in ACTIVE_STATES:
            return self._public_task(previous), True
        if single_active_task:
            requested_task_id = stable_task_id(task["room_url"])
            active_other = next(
                (
                    row
                    for row in self.store.list()
                    if row["state"] in ACTIVE_STATES and row["task_id"] != requested_task_id
                ),
                None,
            )
            if active_other is not None:
                raise ServiceConflictError("another live room is already recording in the extension")
        entry = self.deliveries.create('recording', 'recording:' + secrets.token_hex(16)) if browser_delivery else None
        task["output_dir"] = str(create_session_output_root(
            self.deliveries.work_root(entry['id']) if entry else self._current_output_root(), task["room_id"]))
        if entry:
            self.deliveries.source(entry['id'], task['output_dir'])
        row, reused = self.store.upsert_queued(task)
        task_id = row["task_id"]
        if reused:
            return self._public_task(row), True
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._worker,
            args=(task_id, task, stop_event),
            name=f"brandbai-recorder-{task_id}",
            daemon=True,
        )
        with self._lock:
            self._running[task_id] = RunningTask(thread=thread, stop_event=stop_event)
        thread.start()
        current = self.store.get(task_id) or row
        return self._public_task(current), False

    def _worker(self, task_id: str, task: dict[str, Any], stop_event: threading.Event) -> None:
        try:
            self.store.update(
                task_id,
                state="checking",
                started_at=iso_time(local_now()),
            )
            if self.runtime_preparer is not None and not task["test_mode"]:
                self.runtime_preparer()
            config = RecorderConfig(
                room_url=task["room_url"],
                output_root=Path(task["output_dir"]),
                segment_duration_seconds=task["segment_duration_seconds"],
                split_enabled=task["split_enabled"],
                requested_quality=task["quality"],
                retain_original=task["retain_original"],
                test_mode=task["test_mode"],
                min_free_space_gb=self.min_free_space_gb,
                ffmpeg_path=self.ffmpeg_path,
                ffprobe_path=self.ffprobe_path,
                full_read_check=task["full_read_check"],
                compute_sha256=task["sha256"],
                max_runtime_seconds=task["max_runtime_seconds"],
                collect_room_metrics=True,
            )
            self.store.update(task_id, state="recording")
            result = self.recorder(config, stop_event=stop_event)
            final_state = "failed"
            if result.outcome == "not_live":
                final_state = "not_live"
            elif result.completion_status == "complete_observed_session":
                final_state = "complete"
            elif str(result.completion_status).startswith("partial_"):
                final_state = "partial"
            self.store.update(
                task_id,
                state=final_state,
                ended_at=iso_time(local_now()),
                outcome=result.outcome,
                completion_status=result.completion_status,
                segment_count=result.segment_count,
                valid_mp4_count=result.valid_mp4_count,
                actual_media_duration_seconds=result.actual_media_duration_seconds,
            )
            self.store.event(task_id, "task_finished", f"Task finished as {final_state}.")
        except (RecorderError, RuntimeSetupError, OSError, ValueError) as exc:
            reason_code = getattr(exc, "reason_code", "service_worker_failed")
            detail = redact_text(str(exc), secrets=(str(self.output_root),))[-900:]
            message = f"{reason_code}: {detail}"
            self.store.update(
                task_id,
                state="failed",
                ended_at=iso_time(local_now()),
                outcome="failed",
                completion_status="failed_service_worker",
                last_error=message,
            )
            self.store.event(task_id, "task_failed", "Task worker failed.")
        finally:
            try:
                self._materialize_visible_events(task_id)
            except OSError:
                self.store.event(task_id, "visible_event_export_failed", "Visible event export failed.")
            with self._lock:
                self._running.pop(task_id, None)
            final = self.store.get(task_id)
            entry = self._recording_delivery(final)
            if entry:
                self.deliveries.pack(entry['id'], material_status=final.get('completion_status') or 'partial_unknown',
                                     text_lock=self._visible_event_file_lock, delay=5)

    def stop(self, task_id: str) -> tuple[dict[str, Any], bool]:
        row = self.store.get(task_id)
        if row is None:
            raise ServiceNotFoundError("task not found")
        if row["state"] not in ACTIVE_STATES:
            return self._public_task(row), True
        with self._lock:
            running = self._running.get(task_id)
            if running:
                # API stop and process shutdown used to share the same generic
                # service-stop label. Freeze the first cause before signaling.
                if not running.stop_event.is_set():
                    running.stop_event.recording_stop_kind = "manual"
                running.stop_event.set()
        row = self.store.update(task_id, state="stopping")
        self.store.event(task_id, "stop_requested", "Idempotent stop requested.")
        return self._public_task(row), False

    def get(self, task_id: str) -> dict[str, Any]:
        row = self.store.get(task_id)
        if row is None:
            raise ServiceNotFoundError("task not found")
        return self._public_task(row)

    def list(self) -> list[dict[str, Any]]:
        return [self._public_task(row) for row in self.store.list()]

    def wait_for_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                threads = [running.thread for running in self._running.values()]
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for thread in threads:
                thread.join(timeout=min(remaining, 0.25))

    def shutdown(self, timeout: float = 30.0) -> bool:
        self.product_downloads.stop.set()
        self.product_reviews.shutdown()
        with self._lock:
            running_items = list(self._running.items())
        for task_id, running in running_items:
            running.stop_event.set()
            row = self.store.get(task_id)
            if row and row["state"] in ACTIVE_STATES:
                try:
                    self.store.update(task_id, state="stopping")
                    self.store.event(task_id, "service_shutdown", "Service shutdown requested.")
                except ServiceNotFoundError:
                    pass
        return self.wait_for_idle(timeout)


class LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = True


def create_http_server(
    *,
    host: str,
    port: int,
    manager: TaskManager,
    token: str,
    extension_sessions: ExtensionSessionManager | None = None,
) -> ThreadingHTTPServer:
    if host != DEFAULT_HOST:
        raise ServiceInputError("the service may only bind to 127.0.0.1")
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ServiceInputError("port must be between 0 and 65535")
    if len(token) < 32:
        raise ServiceInputError("service token must contain at least 32 characters")
    session_manager = extension_sessions or ExtensionSessionManager()

    class Handler(BaseHTTPRequestHandler):
        server_version = "BrandBAILiveRecorder/" + SERVICE_VERSION

        def log_message(self, format_string: str, *args: Any) -> None:
            message = redact_text(format_string % args)
            try:
                print(f"{self.log_date_time_string()} {message}", flush=True)
            except (OSError, ValueError):
                # A closed parent console must not break localhost HTTP responses.
                pass

        def _origin(self) -> str | None:
            return self.headers.get("Origin")

        def _set_cors(self) -> None:
            origin = self._origin()
            if origin and is_allowed_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._set_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _require_origin(self) -> None:
            if not is_allowed_origin(self._origin()):
                raise ServiceOriginError("browser origin is not allowed")

        def _require_token(self) -> None:
            supplied = self.headers.get("X-BrandBAI-Token", "")
            if hmac.compare_digest(supplied, token):
                return
            client_id = self.headers.get("X-BrandBAI-Client", "")
            if not session_manager.validate(supplied, self._origin(), client_id):
                raise ServiceUnauthorizedError("invalid service token")

        def _require_pair_action(self) -> None:
            if not is_extension_origin(self._origin()):
                raise ServiceOriginError("extension pairing requires a Chrome extension origin")
            if self.headers.get("X-BrandBAI-Pair", "") not in PAIR_ACTIONS:
                raise ServiceInputError("extension pairing requires a supported popup action header")
            client_id = self.headers.get("X-BrandBAI-Client", "")
            expected_client_id = extension_id_from_origin(self._origin())
            if not expected_client_id or not hmac.compare_digest(client_id, expected_client_id):
                raise ServiceOriginError("extension client ID does not match the pairing origin")

        def _read_json(self, max_bytes=65_536) -> Any:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                raise ServiceInputError("Content-Type must be application/json")
            length_text = self.headers.get("Content-Length", "")
            try:
                length = int(length_text)
            except ValueError as exc:
                raise ServiceInputError("invalid Content-Length") from exc
            if length <= 0 or length > max_bytes:
                raise ServiceInputError(f"JSON body must be between 1 and {max_bytes} bytes")
            try:
                body = self.rfile.read(length)
                self._body_consumed = True
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ServiceInputError("request body is not valid UTF-8 JSON") from exc

        def _route_error(self, exc: Exception) -> None:
            # Closing HTTP/1.0 with unread POST bytes can reset the socket on Windows
            # before the caller sees its 401/403. Drain only bounded small bodies;
            # never interpret them or weaken the authorization decision.
            if self.command == 'POST' and not getattr(self, '_body_consumed', False):
                length = self.headers.get('Content-Length', '')
                if length.isdigit() and 0 < int(length) <= 2_000_000:
                    timeout = self.connection.gettimeout()
                    try:
                        self.connection.settimeout(.25)
                        self.rfile.read(int(length))
                    except OSError:
                        pass
                    finally:
                        self.connection.settimeout(timeout)
            status = exc.status_code if isinstance(exc, ServiceError) else 409 if isinstance(exc, DeliveryError) else 500
            message = str(exc) if isinstance(exc, (ServiceError, DeliveryError)) else "internal service error"
            self._json(status, {"error": type(exc).__name__, "message": message})

        def _browser_delivery(self):
            return self.headers.get('X-BrandBAI-Delivery') == 'browser-zip'

        def _download_file(self, ident, attempt):
            stream = manager.deliveries.open_archive(ident, attempt,
                self.headers.get('X-BrandBAI-FileTicket', ''), self.headers.get('X-BrandBAI-Client', ''))
            with stream:
                size = os.fstat(stream.fileno()).st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                    if not match or int(match[1]) >= size:
                        self.send_response(416); self.send_header('Content-Range', f'bytes */{size}')
                        self.send_header('Content-Length', '0'); self.end_headers(); return
                    start, end, status = int(match[1]), min(int(match[2]) if match[2] else size-1, size-1), 206
                    if end < start:
                        self.send_response(416); self.send_header('Content-Length', '0'); self.end_headers(); return
                item = manager.deliveries.public(ident)
                self.send_response(status); self._set_cors()
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(item['filename']))
                self.send_header('Content-Length', str(end-start+1)); self.send_header('Accept-Ranges', 'bytes')
                self.send_header('ETag', '"' + attempt + '"'); self.send_header('Cache-Control', 'no-store')
                if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers(); stream.seek(start); remaining = end-start+1
                try:
                    while remaining:
                        block = stream.read(min(1024*1024, remaining))
                        if not block: break
                        self.wfile.write(block); remaining -= len(block)
                except OSError:
                    pass  # Browser owns transfer success; never mark complete here.

        def do_OPTIONS(self) -> None:
            try:
                self._require_origin()
                self.send_response(204)
                self._set_cors()
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-BrandBAI-Token, X-BrandBAI-Pair, X-BrandBAI-Client, X-BrandBAI-Delivery, X-BrandBAI-FileTicket, Range",
                )
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()
            except Exception as exc:
                self._route_error(exc)

        def do_GET(self) -> None:
            try:
                self._require_origin()
                path = urlsplit(self.path).path.rstrip("/") or "/"
                if path == "/v1/health":
                    self._json(
                        200,
                        {
                            "service": "brandbai-live-recorder",
                            "version": SERVICE_VERSION,
                            "product_snapshots": True,
                            "product_catalog": True,
                            "product_downloads": True,
                            "independent_product_downloads": True,
                            "full_product_materials": True,
                            "all_visible_product_skus": True,
                            "independent_product_catalogs": True,
                            "catalog_number_verification": True,
                            "readable_interaction_exports": True,
                            "recording_popup_bundle": True,
                            "independent_product_reviews": True,
                            "review_stop_save": True,
                            "review_target_continuation": True,
                            "review_visibility_wait": True,
                            "shared_product_identity": True,
                            "browser_zip_delivery": True,
                            "status": "ready",
                            "host": DEFAULT_HOST,
                            "authentication_required": True,
                            "one_click_pairing": True,
                            "automatic_pairing": True,
                            "extension_session_ttl_seconds": session_manager.ttl_seconds,
                        },
                    )
                    return
                file_match = re.fullmatch(r'/v1/deliveries/([a-f0-9]{32})/file/([a-f0-9]{32})', path)
                if file_match:
                    self._download_file(*file_match.groups())
                    return
                self._require_token()
                if path == '/v1/deliveries':
                    self._json(200, {'deliveries': manager.deliveries.list()}); return
                if path == "/v1/tasks":
                    self._json(200, {"tasks": manager.list()})
                    return
                if path == "/v1/settings":
                    self._json(200, {'storage': {'configured': True, 'mode': 'browser-zip', 'display_path': '浏览器默认下载位置'}
                        if self._browser_delivery() else manager.storage_settings()})
                    return
                match = re.fullmatch(r"/v1/product-downloads/([a-f0-9-]{36})", path)
                if match:
                    self._json(200, {"product_download": manager.current_product_download(match.group(1))})
                    return
                match = re.fullmatch(r"/v1/product-reviews/([a-f0-9-]{36})", path)
                if match:
                    self._json(200, {"task": manager.review_status(match.group(1))})
                    return
                match = re.fullmatch(r"/v1/tasks/(dy-[0-9a-f]{16})", path)
                if match:
                    self._json(200, {"task": manager.get(match.group(1))})
                    return
                raise ServiceNotFoundError("endpoint not found")
            except Exception as exc:
                self._route_error(exc)

        def do_POST(self) -> None:
            try:
                self._require_origin()
                path = urlsplit(self.path).path.rstrip("/") or "/"
                if path == "/v1/pair":
                    self._require_pair_action()
                    session_token, expires_in = session_manager.issue(
                        self._origin(), self.headers.get("X-BrandBAI-Client", "")
                    )
                    self._json(
                        201,
                        {
                            "session_token": session_token,
                            "expires_in_seconds": expires_in,
                            "persisted": False,
                            "origin_bound": True,
                            "pairing_mode": self.headers.get("X-BrandBAI-Pair"),
                        },
                    )
                    return
                self._require_token()
                delivery_match = re.fullmatch(r'/v1/deliveries/([a-f0-9]{32})/(claim|report|prepare|missing)', path)
                if delivery_match:
                    ident, action = delivery_match.groups(); body = self._read_json(2000)
                    client = self.headers.get('X-BrandBAI-Client', '')
                    if action == 'report': result = manager.deliveries.report(ident, body, client)
                    elif action == 'claim':
                        if not isinstance(body, dict) or set(body) != {'retry'} or type(body['retry']) is not bool:
                            raise DeliveryError('invalid_delivery_request')
                        result = manager.deliveries.claim(ident, client, retry=body['retry'])
                    elif body != {}: raise DeliveryError('invalid_delivery_request')
                    elif action == 'prepare': result = manager.prepare_delivery(ident)
                    else: result = manager.deliveries.reconcile_missing(ident, client)
                    self._json(200, {'delivery': result}); return
                if path == "/v1/product-reviews":
                    self._json(201, {"task": manager.review_request(self._read_json(100_000), browser_delivery=self._browser_delivery())})
                    return
                review_stop = re.fullmatch(r"/v1/product-reviews/([a-f0-9-]{36})/stop", path)
                if review_stop:
                    self._json(200, {"task": manager.stop_review(review_stop.group(1), self._read_json(2_000))})
                    return
                review_match = re.fullmatch(r"/v1/product-reviews/([a-f0-9-]{36})/events", path)
                if review_match:
                    self._json(200, {"task": manager.review_request(self._read_json(2_000_000), review_match.group(1))})
                    return
                if path == "/v1/product-downloads":
                    result = manager.download_current_product(self._read_json(1_000_000), browser_delivery=self._browser_delivery())
                    self._json(202, {"product_download": result})
                    return
                if path == "/v1/tasks":
                    extension_request = is_extension_origin(self._origin()) or bool(self.headers.get('X-BrandBAI-Client'))
                    if extension_request and not self._browser_delivery() and manager.storage_settings().get("configured") is not True:
                        raise ServiceConflictError("the recording location must be confirmed first")
                    row, reused = manager.create(
                        self._read_json(),
                        single_active_task=extension_request,
                        browser_delivery=self._browser_delivery(),
                    )
                    self._json(200 if reused else 202, {"task": row, "reused": reused})
                    return
                if path == "/v1/settings/output-root":
                    if self.headers.get("X-BrandBAI-Settings", "") != "user-click":
                        raise ServiceInputError("changing the recording location requires a user action")
                    body = self._read_json()
                    if not isinstance(body, dict) or set(body) != {"action"}:
                        raise ServiceInputError("the storage action is invalid")
                    if body["action"] == "use_default":
                        storage = manager.confirm_default_output_root()
                        self._json(200, {"storage": storage, "canceled": False})
                        return
                    if body["action"] == "choose":
                        storage, canceled = manager.choose_output_root()
                        self._json(200, {"storage": storage, "canceled": canceled})
                        return
                    raise ServiceInputError("the storage action is invalid")
                match = re.fullmatch(r"/v1/tasks/(dy-[0-9a-f]{16})/product-download", path)
                if match:
                    result = manager.download_products(match.group(1), self._read_json(), browser_delivery=self._browser_delivery())
                    self._json(202, {"product_download": result})
                    return
                match = re.fullmatch(r"/v1/tasks/(dy-[0-9a-f]{16})/stop", path)
                if match:
                    row, already_stopped = manager.stop(match.group(1))
                    self._json(200, {"task": row, "already_stopped": already_stopped})
                    return
                match = re.fullmatch(r"/v1/tasks/(dy-[0-9a-f]{16})/visible-events", path)
                if match:
                    result = manager.ingest_visible_events(match.group(1), self._read_json())
                    self._json(202 if result["accepted"] else 200, result)
                    return
                match = re.fullmatch(r"/v1/tasks/(dy-[0-9a-f]{16})/collector-options", path)
                if match:
                    task = manager.set_collector_options(match.group(1), self._read_json())
                    self._json(200, {"task": task})
                    return
                raise ServiceNotFoundError("endpoint not found")
            except Exception as exc:
                self._route_error(exc)

    return LoopbackServer((host, port), Handler)
