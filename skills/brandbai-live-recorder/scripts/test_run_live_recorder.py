from __future__ import annotations

import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from recorder_core import ResolveError, StreamInfo
from runtime_support import RuntimeStatus
from run_live_recorder import (
    EXIT_COMPLETE,
    EXIT_INPUT_OR_ENVIRONMENT,
    EXIT_PARTIAL_OR_NOT_LIVE,
    main,
)


@contextmanager
def scratch_dir():
    path = Path(__file__).resolve().parent / f".cli-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class RecorderCliTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "run_live_recorder.ensure_streamget_runtime",
            return_value=RuntimeStatus(True, "4.0.10", "synthetic_runtime"),
        )
        self.runtime_prepare = patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_is_read_only_and_strips_query(self) -> None:
        with scratch_dir() as temporary:
            output = temporary / "must-not-exist"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "dry-run",
                        "--room-url",
                        "https://live.douyin.com/123/?token=secret",
                        "--segment-minutes",
                        "5",
                    ]
                )
            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, EXIT_COMPLETE)
            self.assertEqual(payload["canonical_room_url"], "https://live.douyin.com/123")
            self.assertEqual(payload["segment_duration_seconds"], 300)
            self.assertFalse(payload["network_accessed"])
            self.assertFalse(payload["files_written"])
            self.assertFalse(output.exists())

    def test_start_requires_authorization_flag_before_writing(self) -> None:
        with scratch_dir() as temporary:
            output = temporary / "delivery"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "start",
                        "--room-url",
                        "https://live.douyin.com/123",
                        "--out",
                        str(output),
                    ]
                )
            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, EXIT_INPUT_OR_ENVIRONMENT)
            self.assertEqual(payload["error"], "InputError")
            self.assertFalse(output.exists())

    def test_seconds_below_regular_minimum_require_test_mode(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                [
                    "dry-run",
                    "--room-url",
                    "https://live.douyin.com/123",
                    "--segment-seconds",
                    "30",
                ]
            )
        self.assertEqual(exit_code, EXIT_INPUT_OR_ENVIRONMENT)
        self.assertIn("between 60 and 21600", buffer.getvalue())

    def test_probe_outputs_public_summary_without_stream_url(self) -> None:
        stream = StreamInfo(
            canonical_room_url="https://live.douyin.com/123",
            room_id="123",
            streamer_name="合成主播",
            title="合成直播",
            is_live=True,
            source_type="FLV",
            requested_quality="SD",
            actual_quality="SD",
            quality_fallback_reason=None,
            stream_url="https://signed.example.test/private",
        )
        buffer = io.StringIO()
        with patch("run_live_recorder.resolve_douyin_room_sync", return_value=stream):
            with redirect_stdout(buffer):
                exit_code = main(
                    ["probe", "--room-url", "https://live.douyin.com/123", "--quality", "SD"]
                )
        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, EXIT_COMPLETE)
        self.assertTrue(payload["is_live"])
        self.assertFalse(payload["files_written"])
        self.assertNotIn("stream_url", payload)
        self.assertNotIn("signed.example", buffer.getvalue())

    def test_probe_not_live_uses_partial_exit_code(self) -> None:
        stream = StreamInfo(
            canonical_room_url="https://live.douyin.com/123",
            room_id="123",
            streamer_name="合成主播",
            title=None,
            is_live=False,
            source_type=None,
            requested_quality="SD",
            actual_quality=None,
            quality_fallback_reason=None,
            stream_url=None,
        )
        with patch("run_live_recorder.resolve_douyin_room_sync", return_value=stream):
            with redirect_stdout(io.StringIO()):
                exit_code = main(["probe", "--room-url", "https://live.douyin.com/123"])
        self.assertEqual(exit_code, EXIT_PARTIAL_OR_NOT_LIVE)

    def test_probe_failure_returns_stable_reason_code(self) -> None:
        buffer = io.StringIO()
        error = ResolveError("network unavailable", reason_code="resolver_network_unavailable")
        with patch("run_live_recorder.resolve_douyin_room_sync", side_effect=error):
            with redirect_stdout(buffer):
                exit_code = main(["probe", "--room-url", "https://live.douyin.com/123"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, EXIT_INPUT_OR_ENVIRONMENT)
        self.assertEqual(payload["reason_code"], "resolver_network_unavailable")

    def test_invalid_probe_url_does_not_prepare_runtime(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["probe", "--room-url", "https://example.com/not-douyin"])
        self.assertEqual(exit_code, EXIT_INPUT_OR_ENVIRONMENT)
        self.runtime_prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
