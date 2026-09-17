import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import run_doubao_lite_transcription as dut


class DoubaoLiteTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent / ".test-doubao-lite-transcription-v2"
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir()

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_srt_uses_recording_time_and_skips_no_speech(self):
        path = self.test_root / "out.srt"
        dut.write_srt(
            path,
            [
                {
                    "status": "completed",
                    "text": "现在看三号链接",
                    "media_start_seconds": 39.226,
                    "media_end_seconds": 49.226,
                },
                {
                    "status": "completed",
                    "text": dut.NO_SPEECH_MARKER,
                    "media_start_seconds": 49.226,
                    "media_end_seconds": 54.226,
                },
            ],
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn("00:00:39,226 --> 00:00:49,226", text)
        self.assertNotIn(dut.NO_SPEECH_MARKER, text)

    def test_payload_contains_audio_but_never_api_key(self):
        payload = dut.build_payload("ep-test", "转写", b"fake-wave")
        parsed = json.loads(payload)
        self.assertEqual(parsed["model"], "ep-test")
        self.assertEqual(parsed["messages"][0]["content"][1]["type"], "input_audio")
        self.assertNotIn("secret-value", payload.decode("utf-8"))

    def test_chunk_rows_use_local_boundaries_not_model_timestamps(self):
        chunk_path = self.test_root / "chunk.wav"
        chunk_path.write_bytes(b"fake-wave")
        chunk = dut.Chunk(chunk_path, 0, 0.0, 10.0)
        with mock.patch.object(
            dut,
            "call_ark",
            return_value={
                "text": "还有的，给你们再加一波",
                "resolved_model": "doubao-seed-2-0-lite-test",
                "usage": {"audio_tokens": 10},
            },
        ):
            rows = dut.transcribe_chunks(
                chunks=[chunk],
                api_url="https://example.invalid",
                api_key="secret-value",
                model="ep-test",
                context="韩束 红蛮腰",
                timeout_seconds=30,
                retries=0,
                media_offset_seconds=39.226,
            )
        self.assertEqual(rows[0]["media_start_seconds"], 39.226)
        self.assertEqual(rows[0]["media_end_seconds"], 49.226)
        self.assertFalse(rows[0]["model_timestamp"])
        self.assertEqual(rows[0]["time_source"], "deterministic_local_audio_chunk_boundaries")
        self.assertNotIn("secret-value", json.dumps(rows, ensure_ascii=False))

    def test_external_upload_requires_explicit_authorization(self):
        args = dut.build_parser().parse_args(["--media", "missing.mp4", "--out", "new"])
        with self.assertRaisesRegex(dut.TranscriptionError, "显式确认"):
            dut.run(args)


if __name__ == "__main__":
    unittest.main()
