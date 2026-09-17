"""Simple one-required-input entry point for browser-free live recording."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Sequence

from recorder_core import (
    create_session_output_root,
    EnvironmentError,
    InputError,
    RecorderConfig,
    RecorderError,
    normalize_segment_duration,
    normalize_douyin_room_url,
    record_single_room,
    result_as_dict,
)
from runtime_support import RuntimeSetupError, ensure_streamget_runtime


EXIT_COMPLETE = 0
EXIT_FAILED = 1
EXIT_INPUT_OR_ENVIRONMENT = 2
EXIT_PARTIAL_OR_NOT_LIVE = 3
MIN_MAX_RUNTIME_MINUTES = 1
MAX_MAX_RUNTIME_MINUTES = 1_440
DEFAULT_RECORDING_MINUTES = 30
DEFAULT_SPLIT_MINUTES = 10
MAX_SINGLE_FILE_MINUTES = 360


def default_output_root(
    *,
    room_id: str = "未知直播间",
    now: datetime | None = None,
    home: Path | None = None,
    run_token: str | None = None,
) -> Path:
    configured = os.environ.get("BRANDBAI_LIVE_OUTPUT_ROOT", "").strip()
    base = Path(configured).expanduser() if configured else (home or Path.home()) / "Videos" / "BrandBAI直播录屏"
    return create_session_output_root(
        base,
        room_id,
        now=now or datetime.now().astimezone(),
        run_token=run_token,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record one public Douyin live room; only the room URL is required."
    )
    parser.add_argument("room_url", help="Public https://live.douyin.com/<room-id> URL.")
    parser.add_argument(
        "--recording-minutes",
        "--max-runtime-minutes",
        dest="recording_minutes",
        type=int,
        default=DEFAULT_RECORDING_MINUTES,
        help="Total recording duration, 1-1440 minutes; default is 30.",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Split the recording; default segment duration is 10 minutes.",
    )
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--segment-minutes", type=int, help="1-360; implies --split.")
    duration.add_argument("--segment-seconds", type=int, help="60-21600; implies --split.")
    parser.add_argument("--quality", choices=("SD", "HD", "OD"), default="SD")
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional output directory; defaults to the user's Videos folder.",
    )
    return parser


def _recording_seconds(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError("recording duration must be a whole number of minutes")
    if not MIN_MAX_RUNTIME_MINUTES <= value <= MAX_MAX_RUNTIME_MINUTES:
        raise InputError("recording duration must be between 1 and 1440 minutes")
    return value * 60


def _split_enabled(args: argparse.Namespace) -> bool:
    return bool(
        args.split
        or args.segment_minutes is not None
        or args.segment_seconds is not None
    )


def _segment_seconds(args: argparse.Namespace, *, recording_seconds: int) -> int:
    split_enabled = _split_enabled(args)
    if not split_enabled:
        if recording_seconds > MAX_SINGLE_FILE_MINUTES * 60:
            raise InputError(
                "recordings longer than 360 minutes must enable splitting"
            )
        return recording_seconds
    if args.segment_minutes is not None:
        segment_seconds = normalize_segment_duration(args.segment_minutes, unit="minutes")
    elif args.segment_seconds is not None:
        segment_seconds = normalize_segment_duration(args.segment_seconds, unit="seconds")
    else:
        segment_seconds = DEFAULT_SPLIT_MINUTES * 60
    if segment_seconds > recording_seconds:
        raise InputError("segment duration cannot exceed total recording duration")
    return segment_seconds


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _canonical_room, room_id = normalize_douyin_room_url(args.room_url)
        output_root = args.out or default_output_root(room_id=room_id)
        recording_seconds = _recording_seconds(args.recording_minutes)
        split_enabled = _split_enabled(args)
        config = RecorderConfig(
            room_url=args.room_url,
            output_root=output_root,
            segment_duration_seconds=_segment_seconds(
                args,
                recording_seconds=recording_seconds,
            ),
            split_enabled=split_enabled,
            requested_quality=args.quality,
            retain_original=True,
            collect_room_metrics=True,
            room_metrics_interval_seconds=15,
            max_runtime_seconds=recording_seconds,
        )
        config.validated()
        runtime_status = ensure_streamget_runtime(auto_install=True)
        stop_event = threading.Event()
        previous_sigint = signal.getsignal(signal.SIGINT)

        def request_manual_stop(_signum, _frame) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_manual_stop)
        try:
            result = record_single_room(
                config,
                stop_event=stop_event,
                stop_event_kind="manual",
            )
        finally:
            signal.signal(signal.SIGINT, previous_sigint)
        payload = result_as_dict(result)
        payload["saved_to"] = str(Path(result.output_root).resolve())
        payload["simple_input_defaults"] = {
            "quality": args.quality,
            "recording_duration_seconds": config.max_runtime_seconds,
            "split_enabled": split_enabled,
            "segment_duration_seconds": config.segment_duration_seconds,
            "room_metrics_interval_seconds": config.room_metrics_interval_seconds,
            "retain_original": config.retain_original,
        }
        payload["runtime_dependency"] = runtime_status.public_summary()
        payload["output_root"] = "."
        _print_json(payload)
        if result.completion_status == "complete_observed_session":
            return EXIT_COMPLETE
        if result.outcome == "not_live" or str(result.completion_status).startswith("partial_"):
            return EXIT_PARTIAL_OR_NOT_LIVE
        return EXIT_FAILED
    except (InputError, EnvironmentError, RecorderError, RuntimeSetupError, OSError) as exc:
        _print_json(
            {
                "error": type(exc).__name__,
                "reason_code": getattr(exc, "reason_code", "simple_start_failed"),
                "message": str(exc),
            }
        )
        return EXIT_INPUT_OR_ENVIRONMENT


if __name__ == "__main__":
    sys.exit(main())
