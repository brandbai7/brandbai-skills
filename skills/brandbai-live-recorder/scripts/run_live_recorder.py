"""Command-line entry point for the BrandBAI single-room recorder prototype."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from recorder_core import (
    DEFAULT_MIN_FREE_SPACE_GB,
    DEFAULT_SEGMENT_SECONDS,
    EnvironmentError,
    InputError,
    RecorderConfig,
    RecorderError,
    doctor_report,
    normalize_douyin_room_url,
    normalize_segment_duration,
    record_single_room,
    resolve_douyin_room_sync,
    result_as_dict,
    stable_task_id,
)
from runtime_support import (
    RuntimeSetupError,
    activate_existing_streamget_runtime,
    ensure_streamget_runtime,
)


EXIT_COMPLETE = 0
EXIT_FAILED = 1
EXIT_INPUT_OR_ENVIRONMENT = 2
EXIT_PARTIAL_OR_NOT_LIVE = 3


def _add_duration_options(parser: argparse.ArgumentParser) -> None:
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument(
        "--segment-minutes",
        type=int,
        help="Segment duration in whole minutes; regular range is 1-360.",
    )
    duration.add_argument(
        "--segment-seconds",
        type=int,
        help="Segment duration in whole seconds; regular range is 60-21600.",
    )


def _add_task_options(parser: argparse.ArgumentParser, *, include_output: bool) -> None:
    parser.add_argument("--room-url", required=True, help="Public Douyin live-room URL.")
    if include_output:
        parser.add_argument("--out", required=True, type=Path, help="Local output directory.")
    parser.add_argument("--quality", choices=("SD", "HD", "OD"), default="SD")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Allow 10-59 second segments for explicit local testing only.",
    )
    _add_duration_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record one authorized public Douyin live room into verified segments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check the local runtime without recording.")
    doctor.add_argument("--ffmpeg", help="Explicit FFmpeg executable path.")
    doctor.add_argument("--ffprobe", help="Explicit FFprobe executable path.")

    dry_run = subparsers.add_parser(
        "dry-run", help="Validate and normalize task inputs without network access or file writes."
    )
    _add_task_options(dry_run, include_output=False)

    probe = subparsers.add_parser(
        "probe", help="Resolve one public room without recording or creating delivery files."
    )
    probe.add_argument("--room-url", required=True, help="Public Douyin live-room URL.")
    probe.add_argument("--quality", choices=("SD", "HD", "OD"), default="SD")

    start = subparsers.add_parser("start", help="Start one immediate recording task.")
    _add_task_options(start, include_output=True)
    start.add_argument(
        "--authorized-public-content",
        action="store_true",
        help="Confirm that the recording is authorized and limited to public content.",
    )
    start.add_argument(
        "--retain-original",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Retain original TS segments after verified MP4 remuxing (default: true).",
    )
    start.add_argument(
        "--min-free-space-gb",
        type=float,
        default=DEFAULT_MIN_FREE_SPACE_GB,
        help="Stop before recording when available storage is below this threshold.",
    )
    start.add_argument("--ffmpeg", help="Explicit FFmpeg executable path.")
    start.add_argument("--ffprobe", help="Explicit FFprobe executable path.")
    start.add_argument(
        "--full-read-check",
        action="store_true",
        help="Decode-read every finalized media file before marking it valid.",
    )
    start.add_argument(
        "--sha256",
        action="store_true",
        help="Compute SHA-256 for each finalized media file.",
    )
    start.add_argument(
        "--max-runtime-seconds",
        type=int,
        help="Gracefully stop after 10-86400 seconds and mark the run partial_time_limit.",
    )
    start.add_argument(
        "--collect-room-metrics",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Collect low-frequency browser-free viewer, like, and room-commerce snapshots "
            "while recording (default: true)."
        ),
    )
    start.add_argument(
        "--room-metrics-interval-seconds",
        type=int,
        default=15,
        help="Browser-free room metric polling interval, from 10 to 300 seconds (default: 15).",
    )
    return parser


def _duration_from_args(args: argparse.Namespace) -> int:
    if args.segment_minutes is not None:
        return normalize_segment_duration(
            args.segment_minutes, unit="minutes", test_mode=args.test_mode
        )
    if args.segment_seconds is not None:
        return normalize_segment_duration(
            args.segment_seconds, unit="seconds", test_mode=args.test_mode
        )
    return DEFAULT_SEGMENT_SECONDS


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _dry_run(args: argparse.Namespace) -> int:
    canonical, room_id = normalize_douyin_room_url(args.room_url)
    segment_seconds = _duration_from_args(args)
    _print_json(
        {
            "action": "dry_run",
            "canonical_room_url": canonical,
            "room_id": room_id,
            "task_id": stable_task_id(canonical),
            "quality": args.quality,
            "segment_duration_seconds": segment_seconds,
            "test_only": bool(args.test_mode),
            "network_accessed": False,
            "files_written": False,
            "prototype_scope": "single-room immediate recording core",
            "not_in_prototype": [
                "loop monitoring service",
                "automatic reconnection",
                "Excel delivery",
            ],
        }
    )
    return EXIT_COMPLETE


def _start(args: argparse.Namespace) -> int:
    if not args.authorized_public_content:
        raise InputError(
            "start requires --authorized-public-content to confirm authorization and public scope"
        )
    config = RecorderConfig(
        room_url=args.room_url,
        output_root=args.out,
        segment_duration_seconds=_duration_from_args(args),
        requested_quality=args.quality,
        retain_original=args.retain_original,
        test_mode=args.test_mode,
        min_free_space_gb=args.min_free_space_gb,
        ffmpeg_path=args.ffmpeg,
        ffprobe_path=args.ffprobe,
        full_read_check=args.full_read_check,
        compute_sha256=args.sha256,
        max_runtime_seconds=args.max_runtime_seconds,
        collect_room_metrics=args.collect_room_metrics,
        room_metrics_interval_seconds=args.room_metrics_interval_seconds,
    )
    config.validated()
    ensure_streamget_runtime(auto_install=True)
    result = record_single_room(config)
    payload = result_as_dict(result)
    payload["output_root"] = "."
    _print_json(payload)
    if result.completion_status == "complete_observed_session":
        return EXIT_COMPLETE
    if result.outcome == "not_live" or str(result.completion_status).startswith("partial_"):
        return EXIT_PARTIAL_OR_NOT_LIVE
    return EXIT_FAILED


def _probe(args: argparse.Namespace) -> int:
    normalize_douyin_room_url(args.room_url)
    ensure_streamget_runtime(auto_install=True)
    stream = resolve_douyin_room_sync(args.room_url, args.quality)
    payload: dict[str, object] = {
        "action": "probe",
        "network_accessed": True,
        "files_written": False,
        "media_recorded": False,
    }
    payload.update(stream.public_summary())
    _print_json(payload)
    return EXIT_COMPLETE if stream.is_live else EXIT_PARTIAL_OR_NOT_LIVE


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            runtime_status = activate_existing_streamget_runtime()
            report = doctor_report(ffmpeg_path=args.ffmpeg, ffprobe_path=args.ffprobe)
            report["runtime_discovery"] = runtime_status.public_summary()
            _print_json(report)
            return EXIT_COMPLETE if report["ready_for_real_douyin"] else EXIT_INPUT_OR_ENVIRONMENT
        if args.command == "dry-run":
            return _dry_run(args)
        if args.command == "probe":
            return _probe(args)
        if args.command == "start":
            return _start(args)
        raise InputError("unknown command")
    except (InputError, EnvironmentError, RecorderError, RuntimeSetupError) as exc:
        _print_json(
            {
                "error": type(exc).__name__,
                "reason_code": getattr(exc, "reason_code", "recorder_error"),
                "message": str(exc),
            }
        )
        return EXIT_INPUT_OR_ENVIRONMENT


if __name__ == "__main__":
    sys.exit(main())
