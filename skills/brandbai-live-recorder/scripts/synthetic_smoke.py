"""End-to-end smoke test using generated media instead of a real live room."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from recorder_core import (
    RecorderConfig,
    StreamInfo,
    record_single_room,
    resolve_executable,
    result_as_dict,
)


def generate_source(ffmpeg: str, destination: Path) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x568:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=44100",
        "-t",
        "22",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-g",
        "25",
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-f",
        "mpegts",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"synthetic source generation failed: {completed.stderr[-1000:]}")


def main() -> int:
    ffmpeg = resolve_executable(None, "ffmpeg")
    ffprobe = resolve_executable(None, "ffprobe")
    script_dir = Path(__file__).resolve().parent
    temporary_root = script_dir / f".synthetic-smoke-{uuid.uuid4().hex}"
    temporary_root.mkdir()
    try:
        source = temporary_root / "synthetic_source.ts"
        output = temporary_root / "delivery"
        generate_source(ffmpeg, source)

        stream = StreamInfo(
            canonical_room_url="https://live.douyin.com/synthetic-smoke",
            room_id="synthetic-smoke",
            streamer_name="合成测试直播间",
            title="合成测试",
            is_live=True,
            source_type="synthetic_local",
            requested_quality="SD",
            actual_quality="SD",
            quality_fallback_reason=None,
            stream_url=str(source),
        )
        config = RecorderConfig(
            room_url=stream.canonical_room_url,
            output_root=output,
            segment_duration_seconds=10,
            requested_quality="SD",
            retain_original=True,
            test_mode=True,
            min_free_space_gb=0.01,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            full_read_check=True,
            compute_sha256=True,
            confirm_eof_as_offline=True,
        )
        result = record_single_room(config, stream_info=stream)
        if result.completion_status != "complete_observed_session":
            raise AssertionError(result_as_dict(result))
        if result.segment_count < 2 or result.valid_mp4_count < 2:
            raise AssertionError("the 22-second fixture did not produce at least two valid MP4 segments")
        if not 21.0 <= result.actual_media_duration_seconds <= 23.5:
            raise AssertionError("unexpected total media duration")

        manifest_path = output / "data" / "project_manifest.json"
        manifest_text = manifest_path.read_text(encoding="utf-8")
        if str(temporary_root) in manifest_text or str(source) in manifest_text:
            raise AssertionError("manifest leaked a local absolute path")

        bounded_output = temporary_root / "delivery-bounded"
        bounded_config = RecorderConfig(
            room_url=stream.canonical_room_url,
            output_root=bounded_output,
            segment_duration_seconds=10,
            split_enabled=False,
            max_runtime_seconds=10,
            requested_quality="SD",
            retain_original=True,
            test_mode=True,
            min_free_space_gb=0.01,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            full_read_check=True,
            compute_sha256=True,
        )
        bounded_result = record_single_room(bounded_config, stream_info=stream)
        if bounded_result.completion_status != "partial_time_limit":
            raise AssertionError(result_as_dict(bounded_result))
        if bounded_result.segment_count != 1 or bounded_result.valid_mp4_count != 1:
            raise AssertionError("bounded no-split recording did not produce exactly one MP4")
        if not 10.0 <= bounded_result.actual_media_duration_seconds <= 10.5:
            raise AssertionError(
                "bounded recording did not reach the requested media duration: "
                f"{bounded_result.actual_media_duration_seconds}"
            )

        bounded_split_output = temporary_root / "delivery-bounded-split"
        bounded_split_config = RecorderConfig(
            room_url=stream.canonical_room_url,
            output_root=bounded_split_output,
            segment_duration_seconds=10,
            split_enabled=True,
            max_runtime_seconds=20,
            requested_quality="SD",
            retain_original=True,
            test_mode=True,
            min_free_space_gb=0.01,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            full_read_check=True,
            compute_sha256=True,
        )
        bounded_split_result = record_single_room(bounded_split_config, stream_info=stream)
        if bounded_split_result.completion_status != "partial_time_limit":
            raise AssertionError(result_as_dict(bounded_split_result))
        if bounded_split_result.segment_count != 2 or bounded_split_result.valid_mp4_count != 2:
            raise AssertionError(
                "bounded 20-second recording with 10-second splits did not produce exactly two MP4s"
            )
        if not 20.0 <= bounded_split_result.actual_media_duration_seconds <= 20.5:
            raise AssertionError(
                "bounded split recording did not reach the requested media duration: "
                f"{bounded_split_result.actual_media_duration_seconds}"
            )

        payload = result_as_dict(result)
        payload["output_root"] = "<temporary synthetic delivery>"
        payload["bounded_actual_media_duration_seconds"] = (
            bounded_result.actual_media_duration_seconds
        )
        payload["bounded_split_actual_media_duration_seconds"] = (
            bounded_split_result.actual_media_duration_seconds
        )
        payload["smoke_assertions"] = {
            "at_least_two_segments": True,
            "all_media_full_read": True,
            "sha256_recorded": True,
            "no_absolute_source_path_in_manifest": True,
            "bounded_media_reaches_requested_duration": True,
            "bounded_split_has_no_empty_tail": True,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
