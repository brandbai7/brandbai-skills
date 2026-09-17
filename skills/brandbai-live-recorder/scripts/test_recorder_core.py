from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from recorder_core import (
    InputError,
    MediaProbe,
    RecorderConfig,
    RecordingResult,
    RunLedger,
    StorageError,
    StreamInfo,
    _run_ffmpeg_process,
    _run_hidden,
    _windows_creation_flags,
    build_ffmpeg_record_command,
    classify_resolver_exception,
    media_validation_status,
    installed_package_version,
    is_retryable_ffmpeg_startup_failure,
    normalize_douyin_room_url,
    normalize_segment_duration,
    proxy_environment_report,
    redact_text,
    relative_posix,
    record_single_room,
    select_completion_status,
    validate_segment_duration,
)


@contextmanager
def scratch_dir():
    path = Path(__file__).resolve().parent / f".unit-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class SegmentDurationTests(unittest.TestCase):
    def test_regular_range_and_default(self) -> None:
        self.assertEqual(normalize_segment_duration(None), 1800)
        self.assertEqual(normalize_segment_duration(1, unit="minutes"), 60)
        self.assertEqual(normalize_segment_duration(360, unit="minutes"), 21600)
        self.assertEqual(validate_segment_duration(60), 60)
        with self.assertRaises(InputError):
            validate_segment_duration(59)
        with self.assertRaises(InputError):
            validate_segment_duration(21601)

    def test_explicit_test_range(self) -> None:
        self.assertEqual(validate_segment_duration(10, test_mode=True), 10)
        self.assertEqual(validate_segment_duration(59, test_mode=True), 59)
        with self.assertRaises(InputError):
            validate_segment_duration(9, test_mode=True)

    def test_no_split_uses_one_fixed_output_instead_of_segment_muxer(self) -> None:
        command = build_ffmpeg_record_command(
            ffmpeg="ffmpeg",
            stream_url="https://signed.example.test/live",
            output_pattern=Path("room_%03d.ts"),
            segment_seconds=1800,
            split_enabled=False,
            max_runtime_seconds=60,
        )
        self.assertNotIn("segment", command)
        self.assertNotIn("-segment_time", command)
        self.assertEqual(command[command.index("-t") + 1], "60")
        self.assertEqual(command[-1], "room_001.ts")

    def test_bounded_split_uses_only_pre_end_boundaries(self) -> None:
        command = build_ffmpeg_record_command(
            ffmpeg="ffmpeg",
            stream_url="https://signed.example.test/live",
            output_pattern=Path("room_%03d.ts"),
            segment_seconds=600,
            split_enabled=True,
            max_runtime_seconds=1800,
        )
        self.assertIn("segment", command)
        self.assertNotIn("-segment_time", command)
        self.assertEqual(command[command.index("-segment_times") + 1], "600,1200")
        self.assertEqual(command[command.index("-t") + 1], "1800")

    def test_non_even_bounded_split_keeps_the_real_remainder(self) -> None:
        command = build_ffmpeg_record_command(
            ffmpeg="ffmpeg",
            stream_url="https://signed.example.test/live",
            output_pattern=Path("room_%03d.ts"),
            segment_seconds=60,
            split_enabled=True,
            max_runtime_seconds=130,
        )
        self.assertEqual(command[command.index("-segment_times") + 1], "60,120")

    def test_one_segment_bounded_split_does_not_open_an_empty_tail(self) -> None:
        command = build_ffmpeg_record_command(
            ffmpeg="ffmpeg",
            stream_url="https://signed.example.test/live",
            output_pattern=Path("room_%03d.ts"),
            segment_seconds=60,
            split_enabled=True,
            max_runtime_seconds=60,
        )
        self.assertNotIn("segment", command)
        self.assertNotIn("-segment_time", command)
        self.assertNotIn("-segment_times", command)
        self.assertEqual(command[-1], "room_001.ts")

    def test_unbounded_recording_does_not_add_ffmpeg_duration_limit(self) -> None:
        command = build_ffmpeg_record_command(
            ffmpeg="ffmpeg",
            stream_url="https://signed.example.test/live",
            output_pattern=Path("room_%03d.ts"),
            segment_seconds=600,
            split_enabled=True,
        )
        self.assertNotIn("-t", command)
        self.assertEqual(command[command.index("-segment_time") + 1], "600")


class PackageVersionTests(unittest.TestCase):
    def test_falls_back_to_dist_info_directory_when_metadata_version_is_empty(self) -> None:
        with scratch_dir() as root:
            (root / "streamget-4.0.10.dist-info").mkdir()
            original = __import__("importlib.metadata").metadata.version
            try:
                __import__("importlib.metadata").metadata.version = lambda _name: None
                self.assertEqual(
                    installed_package_version("streamget", search_paths=(str(root),)),
                    "4.0.10",
                )
            finally:
                __import__("importlib.metadata").metadata.version = original


class InputAndPrivacyTests(unittest.TestCase):
    def test_room_url_is_canonicalized(self) -> None:
        canonical, room_id = normalize_douyin_room_url(
            "https://live.douyin.com/123456/?token=secret#fragment"
        )
        self.assertEqual(canonical, "https://live.douyin.com/123456")
        self.assertEqual(room_id, "123456")

    def test_non_public_room_url_is_rejected(self) -> None:
        for url in (
            "http://live.douyin.com/123",
            "https://example.com/123",
            "https://user:pass@live.douyin.com/123",
        ):
            with self.subTest(url=url), self.assertRaises(InputError):
                normalize_douyin_room_url(url)

    def test_sensitive_text_is_redacted(self) -> None:
        value = "pull https://example.test/live?token=x cookie=abc token=xyz LOCAL_SECRET"
        redacted = redact_text(value, secrets=("LOCAL_SECRET",))
        self.assertNotIn("https://", redacted)
        self.assertNotIn("abc", redacted)
        self.assertNotIn("xyz", redacted)
        self.assertNotIn("LOCAL_SECRET", redacted)

    def test_private_stream_url_never_enters_public_summary(self) -> None:
        stream = StreamInfo(
            canonical_room_url="https://live.douyin.com/1",
            room_id="1",
            streamer_name="合成主播",
            title=None,
            is_live=True,
            source_type="flv",
            requested_quality="SD",
            actual_quality="SD",
            quality_fallback_reason=None,
            stream_url="https://signed.example.test/secret",
        )
        self.assertNotIn("stream_url", stream.public_summary())
        self.assertNotIn("signed.example", json.dumps(stream.public_summary()))

    def test_manifest_paths_must_stay_inside_delivery(self) -> None:
        with scratch_dir() as temporary:
            root = temporary / "delivery"
            root.mkdir()
            inside = root / "media" / "a.mp4"
            inside.parent.mkdir()
            inside.touch()
            self.assertEqual(relative_posix(inside, root), "media/a.mp4")
            with self.assertRaises(StorageError):
                relative_posix(Path(temporary) / "outside.mp4", root)

    def test_proxy_report_never_exposes_proxy_value(self) -> None:
        report = proxy_environment_report(
            {"HTTPS_PROXY": "http://user:secret@127.0.0.1:9999"}
        )
        rendered = json.dumps(report)
        self.assertTrue(report["configured"])
        self.assertIn("HTTPS_PROXY", report["variables_present"])
        self.assertNotIn("secret", rendered)
        self.assertNotIn("127.0.0.1", rendered)

    def test_network_text_wrapped_as_json_is_classified_without_echo(self) -> None:
        raw = "ConnectError: [WinError 10061] connection refused at private proxy"
        error = json.JSONDecodeError("Expecting value", raw, 0)
        reason, message = classify_resolver_exception(error)
        self.assertEqual(reason, "resolver_network_unavailable")
        self.assertNotIn("private proxy", message)

    def test_max_runtime_range(self) -> None:
        with scratch_dir() as root:
            RecorderConfig(
                room_url="https://live.douyin.com/1",
                output_root=root,
                max_runtime_seconds=10,
            ).validated()
            with self.assertRaises(InputError):
                RecorderConfig(
                    room_url="https://live.douyin.com/1",
                    output_root=root,
                    max_runtime_seconds=9,
                ).validated()


class CompletionBoundaryTests(unittest.TestCase):
    def test_eof_without_offline_confirmation_is_partial(self) -> None:
        status, issues = select_completion_status(
            has_media=True,
            storage_failed=False,
            conversion_failed=False,
            ffmpeg_return_code=0,
            manual_stop=False,
            service_stop=False,
            offline_confirmed=False,
        )
        self.assertEqual(status, "partial_disconnect")
        self.assertIn("source_ended_without_offline_confirmation", issues)

    def test_only_confirmed_end_is_complete(self) -> None:
        status, issues = select_completion_status(
            has_media=True,
            storage_failed=False,
            conversion_failed=False,
            ffmpeg_return_code=0,
            manual_stop=False,
            service_stop=False,
            offline_confirmed=True,
        )
        self.assertEqual(status, "complete_observed_session")
        self.assertEqual(issues, [])

    def test_short_valid_media_is_not_zero_or_missing(self) -> None:
        probe = MediaProbe(4.0, "mp4", "h264", "aac", 320, 568, True, True, True, None)
        status, short = media_validation_status(probe, target_seconds=10)
        self.assertEqual(status, "short_fragment")
        self.assertTrue(short)

    def test_time_limit_is_partial_not_complete(self) -> None:
        status, issues = select_completion_status(
            has_media=True,
            storage_failed=False,
            conversion_failed=False,
            ffmpeg_return_code=0,
            manual_stop=False,
            service_stop=False,
            time_limit_stop=True,
            offline_confirmed=False,
        )
        self.assertEqual(status, "partial_time_limit")
        self.assertIn("time_limit_stop", issues)


class StartupRetryTests(unittest.TestCase):
    @staticmethod
    def result(*, retryable: bool, valid_mp4_count: int = 0) -> RecordingResult:
        return RecordingResult(
            task_id="dy-test",
            session_id=f"ses-{uuid.uuid4().hex}",
            outcome="recorded" if valid_mp4_count else "failed",
            completion_status="partial_time_limit" if valid_mp4_count else "failed_no_media",
            valid_mp4_count=valid_mp4_count,
            segment_count=valid_mp4_count,
            actual_media_duration_seconds=60.0 if valid_mp4_count else 0.0,
            output_root="unused",
            test_only=False,
            retryable_startup_failure=retryable,
        )

    def test_transient_zero_media_eof_is_retryable(self) -> None:
        self.assertTrue(
            is_retryable_ffmpeg_startup_failure(
                "Error reading HTTP response: End of file\nError opening input: End of file",
                has_media=False,
                manual_stop=False,
                service_stop=False,
                time_limit_stop=False,
            )
        )

    def test_media_or_explicit_stop_is_never_retried(self) -> None:
        stderr = "Error reading HTTP response: End of file"
        for values in (
            {"has_media": True, "manual_stop": False, "service_stop": False},
            {"has_media": False, "manual_stop": True, "service_stop": False},
            {"has_media": False, "manual_stop": False, "service_stop": True},
        ):
            with self.subTest(values=values):
                self.assertFalse(
                    is_retryable_ffmpeg_startup_failure(
                        stderr,
                        time_limit_stop=False,
                        **values,
                    )
                )

    def test_one_retry_uses_fresh_resolution_and_returns_success(self) -> None:
        with scratch_dir() as root:
            first = self.result(retryable=True)
            success = self.result(retryable=False, valid_mp4_count=1)
            config = RecorderConfig(
                room_url="https://live.douyin.com/1",
                output_root=root,
            )
            with patch(
                "recorder_core._record_single_room_once",
                side_effect=(first, success),
            ) as run_once, patch("recorder_core.STARTUP_RETRY_BACKOFF_SECONDS", 0.0):
                result = record_single_room(config, stream_info=object())
            self.assertIs(result, success)
            self.assertEqual(run_once.call_count, 2)
            self.assertIsNone(run_once.call_args_list[1].kwargs["stream_info"])
            events = (root / "data" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("startup_retry_scheduled", events)
            self.assertIn("startup_retry_succeeded", events)

    def test_retry_exhaustion_stops_after_two_attempts(self) -> None:
        with scratch_dir() as root:
            first = self.result(retryable=True)
            second = self.result(retryable=True)
            config = RecorderConfig(
                room_url="https://live.douyin.com/1",
                output_root=root,
            )
            with patch(
                "recorder_core._record_single_room_once",
                side_effect=(first, second),
            ) as run_once, patch("recorder_core.STARTUP_RETRY_BACKOFF_SECONDS", 0.0):
                result = record_single_room(config)
            self.assertIs(result, second)
            self.assertEqual(run_once.call_count, 2)
            events = (root / "data" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("startup_retry_exhausted", events)

    def test_non_transient_failure_is_not_retried(self) -> None:
        with scratch_dir() as root:
            failed = self.result(retryable=False)
            config = RecorderConfig(
                room_url="https://live.douyin.com/1",
                output_root=root,
            )
            with patch("recorder_core._record_single_room_once", return_value=failed) as run_once:
                result = record_single_room(config)
            self.assertIs(result, failed)
            run_once.assert_called_once()


class LedgerTests(unittest.TestCase):
    def test_empty_manifest_declares_prototype_boundary(self) -> None:
        with scratch_dir() as root:
            manifest = RunLedger(root).rebuild_project_manifest()
            self.assertEqual(manifest["valid_mp4_count"], 0)
            self.assertNotIn("Chrome plugin control", manifest["not_in_prototype"])
            self.assertNotIn("Chrome real-browser acceptance", manifest["not_in_prototype"])
            self.assertIn("loop monitoring service", manifest["not_in_prototype"])
            summary = (root / "02_录屏说明与完整性.md").read_text(encoding="utf-8")
            self.assertIn("不证明覆盖平台定义的完整直播", summary)


class ProcessStopTests(unittest.TestCase):
    def test_windows_recorder_children_are_started_without_visible_console(self) -> None:
        flags = _windows_creation_flags(process_group=True)
        if sys.platform == "win32":
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
            self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertEqual(flags, 0)

    def test_hidden_runner_applies_quiet_creation_flags(self) -> None:
        completed = type("Completed", (), {"returncode": 0})()
        with patch("recorder_core.subprocess.run", return_value=completed) as runner:
            _run_hidden(["ffprobe", "-version"], check=False)
        self.assertEqual(
            runner.call_args.kwargs["creationflags"],
            _windows_creation_flags(),
        )

    def test_service_stop_gracefully_closes_process_stdin(self) -> None:
        stop_event = threading.Event()
        timer = threading.Timer(0.1, stop_event.set)
        timer.start()
        started = time.monotonic()
        try:
            return_code, manual_stop, service_stop, time_limit_stop, _tail = _run_ffmpeg_process(
                [sys.executable, "-c", "input()"],
                secrets=(),
                stop_event=stop_event,
            )
        finally:
            timer.cancel()
        self.assertEqual(return_code, 0)
        self.assertFalse(manual_stop)
        self.assertTrue(service_stop)
        self.assertFalse(time_limit_stop)
        self.assertLess(time.monotonic() - started, 3)

    def test_time_limit_gracefully_stops_process_without_busy_wait(self) -> None:
        started = time.monotonic()
        return_code, manual_stop, service_stop, time_limit_stop, _tail = _run_ffmpeg_process(
            [sys.executable, "-c", "input()"],
            secrets=(),
            max_runtime_seconds=0.1,
        )
        self.assertEqual(return_code, 0)
        self.assertFalse(manual_stop)
        self.assertFalse(service_stop)
        self.assertTrue(time_limit_stop)
        self.assertGreaterEqual(time.monotonic() - started, 0.1)
        self.assertLess(time.monotonic() - started, 3)

    def test_manual_stop_event_is_distinct_from_service_stop(self) -> None:
        stop_event = threading.Event()
        timer = threading.Timer(0.1, stop_event.set)
        timer.start()
        try:
            return_code, manual_stop, service_stop, time_limit_stop, _tail = _run_ffmpeg_process(
                [sys.executable, "-c", "input()"],
                secrets=(),
                stop_event=stop_event,
                stop_event_kind="manual",
            )
        finally:
            timer.cancel()
        self.assertEqual(return_code, 0)
        self.assertTrue(manual_stop)
        self.assertFalse(service_stop)
        self.assertFalse(time_limit_stop)

    def test_local_api_stop_preserves_manual_cause_in_recording_export(self) -> None:
        stop_event = threading.Event()
        def request():
            stop_event.recording_stop_kind = 'manual'
            stop_event.set()
        timer = threading.Timer(0.1, request)
        timer.start()
        try:
            code, manual, service, deadline, _ = _run_ffmpeg_process(
                [sys.executable, '-c', 'input()'], secrets=(), stop_event=stop_event)
        finally:
            timer.cancel()
        self.assertEqual(code, 0)
        self.assertTrue(manual)
        self.assertFalse(service)
        self.assertFalse(deadline)


if __name__ == "__main__":
    unittest.main()
