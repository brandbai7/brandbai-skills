#!/usr/bin/env python3
"""Transcribe one authorized recording with Doubao Lite audio input.

The model supplies text only. Stable timestamps come from deterministic local
audio chunks, so model-invented word timings are never presented as evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "brandbai-live-recorder/doubao-lite-transcription/0.1.0"
DEFAULT_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
NO_SPEECH_MARKER = "[NO_SPEECH]"
EXIT_COMPLETE = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2


class TranscriptionError(RuntimeError):
    """Expected configuration or processing failure."""


@dataclass(frozen=True)
class Chunk:
    path: Path
    index: int
    clip_start_seconds: float
    clip_end_seconds: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def format_srt_time(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(path: Path, rows: list[dict[str, Any]]) -> None:
    entries: list[str] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if row.get("status") != "completed" or not text or text == NO_SPEECH_MARKER:
            continue
        entries.append(
            "\n".join(
                [
                    str(len(entries) + 1),
                    f"{format_srt_time(float(row['media_start_seconds']))} --> "
                    f"{format_srt_time(float(row['media_end_seconds']))}",
                    text,
                ]
            )
        )
    path.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")


def resolve_program(name_or_path: str) -> str:
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(name_or_path)
    if not resolved:
        raise TranscriptionError(f"找不到本机程序：{name_or_path}")
    return resolved


def run_checked(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise TranscriptionError(f"{label}失败，退出码 {result.returncode}。")
    return result


def probe_duration(ffprobe: str, media: Path) -> float:
    result = run_checked(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        "媒体时长探测",
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise TranscriptionError("媒体时长不可读。") from exc
    if duration <= 0:
        raise TranscriptionError("媒体时长必须大于 0。")
    return duration


def prepare_chunks(
    ffmpeg: str,
    ffprobe: str,
    media: Path,
    chunk_dir: Path,
    chunk_seconds: int,
) -> list[Chunk]:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    pattern = chunk_dir / "chunk_%04d.wav"
    run_checked(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(media),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            str(pattern),
        ],
        "音频切块",
    )
    paths = sorted(chunk_dir.glob("chunk_*.wav"))
    if not paths:
        raise TranscriptionError("媒体中没有形成可转写音频。")
    chunks: list[Chunk] = []
    cursor = 0.0
    for index, path in enumerate(paths):
        duration = probe_duration(ffprobe, path)
        chunks.append(Chunk(path, index, cursor, cursor + duration))
        cursor += duration
    return chunks


def clean_model_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:-1]
        text = "\n".join(lines).strip()
    return text


def build_prompt(context: str) -> str:
    context_block = context.strip()
    prompt = (
        "Transcribe the Chinese speech in this live-commerce audio verbatim. "
        "Output only the transcript text, without analysis, summary, timestamps, "
        "Markdown fences, or invented words. Preserve original order and spoken "
        "numbers. Mark an unclear phrase as [unclear]. If there is no intelligible "
        f"speech, output exactly {NO_SPEECH_MARKER}."
    )
    if context_block:
        prompt += (
            "\nThe following visible room context is provided only as a glossary. "
            "Do not add a term unless it is actually spoken:\n" + context_block
        )
    return prompt


def build_payload(model: str, prompt: str, audio_bytes: bytes) -> bytes:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(audio_bytes).decode("ascii"),
                            "format": "wav",
                        },
                    },
                ],
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def call_ark(
    *,
    api_url: str,
    api_key: str,
    model: str,
    prompt: str,
    audio_bytes: bytes,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url,
        data=build_payload(model, prompt, audio_bytes),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise TranscriptionError(f"豆包接口返回 HTTP {exc.code}。") from exc
    except urllib.error.URLError as exc:
        raise TranscriptionError("豆包接口网络不可达。") from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
        text = clean_model_text(parsed["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise TranscriptionError("豆包接口返回结构无法识别。") from exc
    if not text:
        raise TranscriptionError("豆包接口返回了空文本。")
    return {
        "text": text,
        "resolved_model": str(parsed.get("model") or ""),
        "usage": parsed.get("usage") or {},
    }


def transcribe_chunks(
    *,
    chunks: list[Chunk],
    api_url: str,
    api_key: str,
    model: str,
    context: str,
    timeout_seconds: int,
    retries: int,
    media_offset_seconds: float,
) -> list[dict[str, Any]]:
    prompt = build_prompt(context)
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        started = time.monotonic()
        result: dict[str, Any] | None = None
        error = ""
        for attempt in range(retries + 1):
            try:
                result = call_ark(
                    api_url=api_url,
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    audio_bytes=chunk.path.read_bytes(),
                    timeout_seconds=timeout_seconds,
                )
                error = ""
                break
            except TranscriptionError as exc:
                error = str(exc)
                if attempt < retries:
                    time.sleep(min(3, attempt + 1))
        elapsed = round(time.monotonic() - started, 3)
        completed = result is not None
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "segment_index": chunk.index,
                "clip_start_seconds": round(chunk.clip_start_seconds, 3),
                "clip_end_seconds": round(chunk.clip_end_seconds, 3),
                "media_start_seconds": round(media_offset_seconds + chunk.clip_start_seconds, 3),
                "media_end_seconds": round(media_offset_seconds + chunk.clip_end_seconds, 3),
                "time_source": "deterministic_local_audio_chunk_boundaries",
                "model_timestamp": False,
                "audio_sha256": sha256_file(chunk.path),
                "status": "completed" if completed else "failed",
                "text": result["text"] if completed else "",
                "resolved_model": result["resolved_model"] if completed else "",
                "usage": result["usage"] if completed else {},
                "elapsed_seconds": elapsed,
                "human_review_status": "NOT_REVIEWED",
                "error": error,
            }
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 Doubao Lite 转写一段已获授权的录屏。")
    parser.add_argument("--media", required=True, help="本地音频或视频文件")
    parser.add_argument("--out", required=True, help="新的转写输出目录")
    parser.add_argument("--model", help="方舟模型或 Endpoint ID；默认读取 ARK_MODEL")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key-env", default="ARK_API_KEY")
    parser.add_argument("--context-file", help="可选的直播间可见词表或上下文")
    parser.add_argument("--chunk-seconds", type=int, default=10, choices=range(5, 61))
    parser.add_argument("--media-offset-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--retries", type=int, default=1, choices=range(0, 4))
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--authorized-external-upload",
        action="store_true",
        help="确认允许把本媒体的音频切块上传火山方舟处理",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    if not args.authorized_external_upload:
        raise TranscriptionError("必须显式确认允许把音频上传火山方舟。")
    media = Path(args.media).expanduser().resolve()
    if not media.is_file():
        raise TranscriptionError("找不到待转写媒体。")
    output = Path(args.out).expanduser().resolve()
    if output.exists():
        raise TranscriptionError("输出目录已存在；请使用新的目录，避免覆盖既有证据。")
    if args.media_offset_seconds < 0:
        raise TranscriptionError("媒体时间偏移不能为负数。")
    if not 10 <= args.timeout_seconds <= 600:
        raise TranscriptionError("接口超时必须在 10—600 秒之间。")

    model = str(args.model or os.environ.get("ARK_MODEL") or "").strip()
    api_key = str(os.environ.get(args.api_key_env) or "").strip()
    if not model:
        raise TranscriptionError("未提供方舟模型；请设置 ARK_MODEL 或使用 --model。")
    if not api_key:
        raise TranscriptionError(f"环境变量 {args.api_key_env} 未配置。")

    context = ""
    if args.context_file:
        context_path = Path(args.context_file).expanduser().resolve()
        if not context_path.is_file():
            raise TranscriptionError("找不到转写上下文文件。")
        context = context_path.read_text(encoding="utf-8")

    ffmpeg = resolve_program(args.ffmpeg)
    ffprobe = resolve_program(args.ffprobe)
    media_duration = probe_duration(ffprobe, media)
    output.mkdir(parents=True)
    data_dir = output / "data"
    data_dir.mkdir()

    work_dir = output / ".doubao-lite-work"
    work_dir.mkdir()
    try:
        chunks = prepare_chunks(
            ffmpeg,
            ffprobe,
            media,
            work_dir / "chunks",
            args.chunk_seconds,
        )
        rows = transcribe_chunks(
            chunks=chunks,
            api_url=args.api_url,
            api_key=api_key,
            model=model,
            context=context,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            media_offset_seconds=args.media_offset_seconds,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    completed = [row for row in rows if row["status"] == "completed"]
    failed = [row for row in rows if row["status"] != "completed"]
    resolved_models = sorted({row["resolved_model"] for row in completed if row["resolved_model"]})
    write_jsonl(data_dir / "transcript_segments.jsonl", rows)
    write_srt(output / "transcript.recording-time.srt", rows)
    (output / "transcript.txt").write_text(
        "\n".join(row["text"] for row in completed if row["text"] != NO_SPEECH_MARKER) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if not failed else ("partial" if completed else "failed"),
        "provider": "volcengine_ark",
        "requested_model_source": "argument" if args.model else "ARK_MODEL_environment",
        "resolved_models": resolved_models,
        "credential_source": args.api_key_env,
        "credential_persisted": False,
        "authorized_external_upload": True,
        "source_media_name": media.name,
        "source_media_sha256": sha256_file(media),
        "source_media_duration_seconds": round(media_duration, 3),
        "media_offset_seconds": round(args.media_offset_seconds, 3),
        "chunk_seconds": args.chunk_seconds,
        "timestamp_granularity": "LOCAL_AUDIO_CHUNK_WINDOW",
        "model_timestamps_used": False,
        "human_review_status": "NOT_REVIEWED",
        "interaction_conclusion_allowed": False,
        "counts": {
            "chunks": len(rows),
            "completed_chunks": len(completed),
            "failed_chunks": len(failed),
        },
    }
    write_json(data_dir / "transcription_manifest.json", manifest)
    api_key = ""
    return EXIT_COMPLETE if not failed else EXIT_PARTIAL


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except TranscriptionError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
