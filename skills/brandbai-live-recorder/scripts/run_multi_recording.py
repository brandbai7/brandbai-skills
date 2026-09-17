"""Record several public Douyin live streams concurrently without page enhancement."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

from recorder_core import (
    EnvironmentError,
    InputError,
    RecorderConfig,
    RecorderError,
    create_session_output_root,
    normalize_douyin_room_url,
    normalize_segment_duration,
    record_single_room,
    result_as_dict,
)
from runtime_support import RuntimeSetupError, ensure_streamget_runtime


DEFAULT_RECORDING_MINUTES = 30
DEFAULT_SPLIT_MINUTES = 10
DEFAULT_MAX_CONCURRENT = 3
MAX_CONCURRENT = 5


def default_output_base() -> Path:
    configured = os.environ.get("BRANDBAI_LIVE_OUTPUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Videos" / "BrandBAI直播录屏"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record multiple public Douyin live streams concurrently. "
            "Browser comments and product-card events are intentionally excluded."
        )
    )
    parser.add_argument(
        "room_urls",
        nargs="+",
        help="Two or more public https://live.douyin.com/<room-id> URLs.",
    )
    parser.add_argument(
        "--recording-minutes",
        type=int,
        default=DEFAULT_RECORDING_MINUTES,
        help="Shared total duration for every room, 1-1440 minutes; default 30.",
    )
    parser.add_argument("--split", action="store_true")
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--segment-minutes", type=int)
    duration.add_argument("--segment-seconds", type=int)
    parser.add_argument("--quality", choices=("SD", "HD", "OD"), default="SD")
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=DEFAULT_MAX_CONCURRENT,
        help="Maximum simultaneously active streams, 1-5; default 3.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Shared recording library root; each room receives an independent session folder.",
    )
    return parser


def _validated_inputs(args: argparse.Namespace) -> tuple[list[tuple[str, str]], int, int, bool]:
    if not 1 <= args.recording_minutes <= 1_440:
        raise InputError("recording duration must be between 1 and 1440 minutes")
    if not 1 <= args.max_concurrent <= MAX_CONCURRENT:
        raise InputError("max concurrent recordings must be between 1 and 5")

    rooms: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_url in args.room_urls:
        canonical, room_id = normalize_douyin_room_url(raw_url)
        if canonical in seen:
            raise InputError("the same live room cannot be submitted twice")
        seen.add(canonical)
        rooms.append((canonical, room_id))
    if len(rooms) < 2:
        raise InputError("multi-room recording requires at least two different live rooms")

    total_seconds = args.recording_minutes * 60
    split_enabled = bool(
        args.split or args.segment_minutes is not None or args.segment_seconds is not None
    )
    if not split_enabled:
        if total_seconds > 360 * 60:
            raise InputError("recordings longer than 360 minutes must enable splitting")
        segment_seconds = total_seconds
    elif args.segment_minutes is not None:
        segment_seconds = normalize_segment_duration(args.segment_minutes, unit="minutes")
    elif args.segment_seconds is not None:
        segment_seconds = normalize_segment_duration(args.segment_seconds, unit="seconds")
    else:
        segment_seconds = DEFAULT_SPLIT_MINUTES * 60
    if segment_seconds > total_seconds:
        raise InputError("segment duration cannot exceed total recording duration")
    return rooms, total_seconds, segment_seconds, split_enabled


def _record_room(
    *,
    canonical_room_url: str,
    room_id: str,
    output_base: Path,
    total_seconds: int,
    segment_seconds: int,
    split_enabled: bool,
    quality: str,
    stop_event: threading.Event,
) -> dict[str, Any]:
    output_root = create_session_output_root(output_base, room_id)
    config = RecorderConfig(
        room_url=canonical_room_url,
        output_root=output_root,
        segment_duration_seconds=segment_seconds,
        split_enabled=split_enabled,
        requested_quality=quality,
        retain_original=True,
        collect_room_metrics=True,
        room_metrics_interval_seconds=15,
        max_runtime_seconds=total_seconds,
    ).validated()
    result = record_single_room(config, stop_event=stop_event, stop_event_kind="manual")
    payload = result_as_dict(result)
    payload["room_url"] = canonical_room_url
    payload["saved_to"] = str(Path(result.output_root).resolve())
    payload["output_root"] = "."
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rooms, total_seconds, segment_seconds, split_enabled = _validated_inputs(args)
        runtime_status = ensure_streamget_runtime(auto_install=True)
        output_base = (args.out or default_output_base()).expanduser().resolve()
        stop_event = threading.Event()
        previous_sigint = signal.getsignal(signal.SIGINT)

        def request_manual_stop(_signum, _frame) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_manual_stop)
        results: list[dict[str, Any]] = []
        try:
            worker_count = min(args.max_concurrent, len(rooms))
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="brandbai-live-room",
            ) as executor:
                futures = {
                    executor.submit(
                        _record_room,
                        canonical_room_url=canonical,
                        room_id=room_id,
                        output_base=output_base,
                        total_seconds=total_seconds,
                        segment_seconds=segment_seconds,
                        split_enabled=split_enabled,
                        quality=args.quality,
                        stop_event=stop_event,
                    ): canonical
                    for canonical, room_id in rooms
                }
                for future in as_completed(futures):
                    canonical = futures[future]
                    try:
                        results.append(future.result())
                    except (InputError, EnvironmentError, RecorderError, OSError) as exc:
                        results.append(
                            {
                                "room_url": canonical,
                                "error": type(exc).__name__,
                                "reason_code": getattr(exc, "reason_code", "multi_room_failed"),
                                "message": str(exc),
                            }
                        )
        finally:
            signal.signal(signal.SIGINT, previous_sigint)

        results.sort(key=lambda item: str(item.get("room_url") or ""))
        payload = {
            "room_count": len(rooms),
            "max_concurrent": min(args.max_concurrent, len(rooms)),
            "browser_page_enhancement": False,
            "comments_or_product_cards_collected": False,
            "runtime_dependency": runtime_status.public_summary(),
            "results": results,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        if any(item.get("error") for item in results):
            return 1
        if any(
            item.get("outcome") == "not_live"
            or str(item.get("completion_status") or "").startswith("partial_")
            for item in results
        ):
            return 3
        return 0
    except (InputError, EnvironmentError, RecorderError, RuntimeSetupError, OSError) as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "reason_code": getattr(exc, "reason_code", "multi_room_start_failed"),
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
