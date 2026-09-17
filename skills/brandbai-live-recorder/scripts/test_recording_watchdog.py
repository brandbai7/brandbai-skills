import io
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from recording_watchdog import MediaProgress
from recorder_core import RecorderConfig, RecordingResult, _run_ffmpeg_process, record_single_room
from test_recorder_core import scratch_dir


class WatchdogTests(unittest.TestCase):
    def test_only_advancing_media_resets_clock(self):
        now = [0.0]
        progress = MediaProgress(None, clock=lambda: now[0])
        now[0] = 44
        self.assertEqual(progress.snapshot()['state'], 'connecting')
        progress.accept('out_time_us=7000000')
        now[0] = 73
        self.assertEqual(progress.snapshot()['state'], 'receiving')
        for line in ('out_time_us=N/A', 'out_time_us=nan', 'frame=400', 'out_time_us=7000000'):
            progress.accept(line)
        now[0] = 74
        self.assertEqual(progress.snapshot()['state'], 'stalled')
        progress.accept('out_time_us=8000000')
        self.assertEqual(progress.snapshot()['state'], 'receiving')

    def test_no_start_has_its_own_bounded_timeout(self):
        progress = MediaProgress(None, clock=lambda: 1)
        progress.clock = lambda: 46
        self.assertEqual(progress.snapshot()['state'], 'stalled')

    def test_pipe_drained_and_no_sensitive_lines_retained(self):
        progress = MediaProgress(io.StringIO('unknown=private\nout_time_us=2000000\nprogress=end\n'))
        progress.start(); progress.close()
        self.assertEqual(progress.snapshot()['media_seconds'], 2)
        self.assertNotIn('private', str(progress.snapshot()))

    def test_hung_process_ends_as_fault_not_manual_or_success(self):
        reports = []
        result = _run_ffmpeg_process(
            [sys.executable, '-u', '-c', 'print("out_time_us=7000000"); input()'], secrets=(),
            watch_progress=True, startup_timeout_seconds=2, stall_timeout_seconds=0.25,
            progress_callback=reports.append, max_runtime_seconds=5)
        self.assertNotEqual(result[0], 0)
        self.assertEqual(result[1:4], (False, False, False))
        self.assertIn('media_progress_stalled', result[4])

    @staticmethod
    def result(seconds=7, retry=True):
        return RecordingResult(task_id='dy-test', session_id='ses-test', outcome='recorded',
            completion_status='partial_disconnect' if retry else 'partial_time_limit', valid_mp4_count=1,
            segment_count=1, actual_media_duration_seconds=seconds, output_root='unused', test_only=True,
            retryable_stream_failure=retry)

    def test_retry_preserves_media_and_original_deadline(self):
        with scratch_dir() as root:
            config = RecorderConfig(room_url='https://live.douyin.com/1', output_root=Path(root), max_runtime_seconds=60)
            now = [100.0]
            def first(*args, **kwargs):
                now[0] += 20
                self.assertEqual(kwargs['deadline_monotonic'], 160)
                return self.result()
            def retry(config, **kwargs):
                self.assertEqual(config.max_runtime_seconds, 60)  # ledger retains original target
                self.assertEqual(kwargs['deadline_monotonic'], 160)
                self.assertIsNone(kwargs['stream_info'])
                return self.result(35, False)
            with patch('recorder_core.time.monotonic', side_effect=lambda: now[0]), \
                 patch('recorder_core.STREAM_RECOVERY_BACKOFF_SECONDS', 0), \
                 patch('recorder_core._record_with_startup_retry', side_effect=first), \
                 patch('recorder_core._record_single_room_once', side_effect=retry) as run:
                result = record_single_room(config)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(result.valid_mp4_count, 2)
            self.assertEqual(result.actual_media_duration_seconds, 42)
            self.assertEqual(result.completion_status, 'partial_disconnect')

    def test_retries_are_bounded_and_stops_are_respected(self):
        for stopped, bounded, expected in ((False, True, 2), (True, True, 0), (False, False, 0)):
            with self.subTest(stopped=stopped, bounded=bounded), scratch_dir() as root:
                config = RecorderConfig(room_url='https://live.douyin.com/1', output_root=Path(root), max_runtime_seconds=60 if bounded else None)
                stop = threading.Event()
                if stopped: stop.set()
                with patch('recorder_core.STREAM_RECOVERY_BACKOFF_SECONDS', 0), \
                     patch('recorder_core._record_with_startup_retry', return_value=self.result()), \
                     patch('recorder_core._record_single_room_once', return_value=self.result()) as run:
                    result = record_single_room(config, stop_event=stop)
                self.assertEqual(run.call_count, expected)
                self.assertEqual(result.valid_mp4_count, expected + 1)

    def test_no_retry_if_less_than_minimum_budget_remains(self):
        with scratch_dir() as root:
            config = RecorderConfig(room_url='https://live.douyin.com/1', output_root=Path(root), max_runtime_seconds=10)
            with patch('recorder_core.time.monotonic', side_effect=[100, 109]), \
                 patch('recorder_core._record_with_startup_retry', return_value=self.result()), \
                 patch('recorder_core._record_single_room_once') as run:
                record_single_room(config)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
