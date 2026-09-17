from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import run_simple_recording as simple
from recorder_core import RecordingResult
from runtime_support import RuntimeStatus


class SimpleInputTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "run_simple_recording.ensure_streamget_runtime",
            return_value=RuntimeStatus(True, "4.0.10", "synthetic_runtime"),
        )
        self.runtime_prepare = patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_room_url_is_required_and_defaults_are_safe(self) -> None:
        result = RecordingResult(
            task_id="dy-synthetic",
            session_id="ses-synthetic",
            outcome="recorded",
            completion_status="partial_manual_stop",
            valid_mp4_count=1,
            segment_count=1,
            actual_media_duration_seconds=65.0,
            output_root=str(Path.cwd() / "synthetic-output"),
            test_only=False,
        )
        buffer = io.StringIO()
        with patch("run_simple_recording.record_single_room", return_value=result) as recorder:
            with patch(
                "run_simple_recording.default_output_root",
                return_value=Path.cwd() / "synthetic-output",
            ):
                with redirect_stdout(buffer):
                    exit_code = simple.main(["https://live.douyin.com/123"])
        config = recorder.call_args.args[0]
        kwargs = recorder.call_args.kwargs
        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, simple.EXIT_PARTIAL_OR_NOT_LIVE)
        self.assertEqual(config.segment_duration_seconds, 1800)
        self.assertFalse(config.split_enabled)
        self.assertEqual(config.requested_quality, "SD")
        self.assertEqual(config.max_runtime_seconds, 1800)
        self.assertTrue(config.collect_room_metrics)
        self.assertEqual(config.room_metrics_interval_seconds, 15)
        self.assertTrue(config.retain_original)
        self.assertEqual(kwargs["stop_event_kind"], "manual")
        self.assertIn("saved_to", payload)
        self.assertEqual(payload["runtime_dependency"]["source"], "synthetic_runtime")
        self.assertFalse(payload["runtime_dependency"]["path_exposed"])
        self.assertFalse(payload["simple_input_defaults"]["split_enabled"])
        self.assertEqual(
            payload["simple_input_defaults"]["recording_duration_seconds"], 1800
        )

    def test_three_optional_business_inputs_are_forwarded(self) -> None:
        result = RecordingResult(
            task_id="dy-synthetic",
            session_id=None,
            outcome="not_live",
            completion_status=None,
            valid_mp4_count=0,
            segment_count=0,
            actual_media_duration_seconds=0.0,
            output_root=str(Path.cwd() / "chosen-output"),
            test_only=False,
        )
        with patch("run_simple_recording.record_single_room", return_value=result) as recorder:
            with redirect_stdout(io.StringIO()):
                exit_code = simple.main(
                    [
                        "https://live.douyin.com/123",
                        "--segment-seconds",
                        "90",
                        "--quality",
                        "HD",
                        "--recording-minutes",
                        "120",
                        "--out",
                        str(Path.cwd() / "chosen-output"),
                    ]
                )
        config = recorder.call_args.args[0]
        self.assertEqual(exit_code, simple.EXIT_PARTIAL_OR_NOT_LIVE)
        self.assertEqual(config.segment_duration_seconds, 90)
        self.assertTrue(config.split_enabled)
        self.assertEqual(config.requested_quality, "HD")
        self.assertEqual(config.max_runtime_seconds, 7200)

    def test_split_without_duration_uses_ten_minutes(self) -> None:
        args = simple.build_parser().parse_args(
            ["https://live.douyin.com/123", "--recording-minutes", "30", "--split"]
        )
        recording_seconds = simple._recording_seconds(args.recording_minutes)
        self.assertTrue(simple._split_enabled(args))
        self.assertEqual(
            simple._segment_seconds(args, recording_seconds=recording_seconds),
            600,
        )

    def test_thirty_minutes_with_ten_minute_segments_maps_to_three_files(self) -> None:
        args = simple.build_parser().parse_args(
            [
                "https://live.douyin.com/123",
                "--recording-minutes",
                "30",
                "--segment-minutes",
                "10",
            ]
        )
        recording_seconds = simple._recording_seconds(args.recording_minutes)
        segment_seconds = simple._segment_seconds(
            args, recording_seconds=recording_seconds
        )
        self.assertEqual(recording_seconds // segment_seconds, 3)

    def test_segment_duration_cannot_exceed_total_recording_duration(self) -> None:
        args = simple.build_parser().parse_args(
            [
                "https://live.douyin.com/123",
                "--recording-minutes",
                "5",
                "--segment-minutes",
                "10",
            ]
        )
        with self.assertRaisesRegex(simple.InputError, "cannot exceed"):
            simple._segment_seconds(
                args,
                recording_seconds=simple._recording_seconds(args.recording_minutes),
            )

    def test_unsegmented_single_file_is_limited_to_six_hours(self) -> None:
        args = simple.build_parser().parse_args(
            ["https://live.douyin.com/123", "--recording-minutes", "361"]
        )
        with self.assertRaisesRegex(simple.InputError, "must enable splitting"):
            simple._segment_seconds(
                args,
                recording_seconds=simple._recording_seconds(args.recording_minutes),
            )

    def test_maximum_runtime_is_limited_to_24_hours(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = simple.main(
                ["https://live.douyin.com/123", "--recording-minutes", "1441"]
            )
        self.assertEqual(exit_code, simple.EXIT_INPUT_OR_ENVIRONMENT)
        self.assertIn("recording duration must be between 1 and 1440 minutes", buffer.getvalue())
        self.runtime_prepare.assert_not_called()

    def test_default_output_is_unique_and_human_readable(self) -> None:
        home = Path.cwd() / "synthetic-home"
        path = simple.default_output_root(
            room_id="295178185857",
            now=datetime(2026, 8, 27, 20, 30, 0),
            home=home,
            run_token="fixedrun",
        )
        self.assertEqual(path.parent, home / "Videos" / "BrandBAI直播录屏" / "直播录制")
        self.assertTrue(path.name.startswith('抖音_直播间待核_R295178185857_直播录制_20260827-203000_B'))
        self.assertEqual(path, simple.default_output_root(room_id='295178185857',
            now=datetime(2026,8,27,20,30,0),home=home,run_token='fixedrun'))


if __name__ == "__main__":
    unittest.main()
