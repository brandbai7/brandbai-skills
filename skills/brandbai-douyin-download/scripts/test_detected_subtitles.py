"""Local mocks only. No Chrome, OCR, platform, or accepted accuracy result."""
import asyncio
import base64
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import extract_detected_subtitles as native
import extract_video_subtitles as fixed
import run_foundation as foundation
from test_video_subtitles import temporary


class FakeBrowser:
    def __init__(self, final="processed"):
        self.final, self.callbacks, self.closed, self.served = final, {}, False, {}
    async def __aenter__(self):
        return types.SimpleNamespace(chromium=self)
    async def __aexit__(self, *unused):
        return False
    async def launch(self, **options):
        self.options = options
        return self
    async def new_context(self, **options):
        self.context_options = options
        return self
    async def route(self, pattern, handler):
        self.handler = handler
    async def new_page(self):
        return self
    async def expose_function(self, name, callback):
        self.callbacks[name] = callback
    async def goto(self, url):
        for suffix in ["/", "/native-runner.js", "/../outside", "https://www.douyin.com/"]:
            target = suffix if suffix.startswith("https:") else url + suffix
            route = types.SimpleNamespace(request=types.SimpleNamespace(url=target), fulfill=AsyncMock(), abort=AsyncMock())
            await self.handler(route)
            self.served[suffix] = route
    async def close(self):
        self.closed = True
    async def evaluate(self, script, parameters):
        self.script, self.parameters = script, parameters
        raw = {"frames": [{"frameIndex": 0, "frameId": "synthetic", "time": .05}],
               "rows": [{"index": 0, "text": "原始繁體", "frameIndex": 0}]}
        state = {"state": "running", "phase": "frames", "processed": 1, "total": 1,
                 "sourceIdentity": {"kind": "local_file_sha256", "sha256": parameters["videoSha256"]},
                 "raw": raw, "segments": [{"text": "工作简体", "firstObserved": .05, "lastObserved": .05}],
                 "events": [{"precision": {"reading": {"text": "實際原讀"}}}]}
        self.callbacks["subtitleNativeProgress"](copy.deepcopy(state))
        if self.final == "raise":
            raise RuntimeError("synthetic interruption")
        if parameters["includeFrames"]:
            await self.callbacks["subtitleNativeImage"]({"path": "画面/001_01_0.05秒.jpg",
                "base64": base64.b64encode(bytes([255, 216, 255, 217])).decode("ascii"), "frameIndex": 0,
                "frameId": "synthetic", "time": .05, "parentPixelsSha256": "a" * 64})
        elif "subtitleNativeImage" in self.callbacks:
            raise AssertionError("Text-only must not expose an image writer")
        state.update(state=self.final, processingComplete=self.final == "processed")
        return {"result": state, "source": {}, "timed": "TIMED working candidate", "plain": "PLAIN working candidate",
                "csv": "CSV source-candidate", "documents": {"markdown": "MD working candidate",
                "html": "<p>working candidate</p>", "csv": "IMAGE CSV", "manifest": {"rows": [{"text": "工作简体"}]}},
                "runtimeBrowser": {"sourceFileSha256": parameters["videoSha256"], "regionMode": "native_detected_lines"},
                "frameStorage": {"sampled": int(parameters["includeFrames"]), "bytes": 4 if parameters["includeFrames"] else 0}}


class DetectedContractTests(unittest.TestCase):
    def run_case(self, final="processed", include_frames=False):
        with temporary() as directory:
            root = Path(directory)
            video = root / "source.mp4"
            video.write_bytes(b"synthetic video: never decoded")
            out = root / "result"
            fake = FakeBrowser(final)
            module = types.ModuleType("playwright.async_api")
            module.async_playwright = lambda: fake
            parent = types.ModuleType("playwright")
            parent.async_api = module
            with patch.dict(sys.modules, {"playwright": parent, "playwright.async_api": module}), patch.object(native, "chrome_path", return_value=None), contextlib.redirect_stdout(io.StringIO()):
                if final == "raise":
                    with self.assertRaises(RuntimeError):
                        asyncio.run(native.extract_detected(video, out))
                    summary = None
                else:
                    summary = asyncio.run(native.extract_detected(video, out, include_frames=include_frames))
            record = json.loads((out / "字幕识别记录.json").read_text(encoding="utf-8"))
            self.assertTrue(fake.closed)
            self.assertTrue(fake.options["headless"])
            self.assertEqual(fake.context_options["service_workers"], "block")
            self.assertTrue(fake.served["https://www.douyin.com/"].abort.called)
            self.assertTrue(fake.served["/../outside"].abort.called)
            self.assertIn('charset="utf-8"', fake.served["/"].fulfill.await_args.kwargs["body"])
            self.assertEqual(record["raw"]["rows"][0]["text"], "原始繁體")
            self.assertEqual(record["events"][0]["precision"]["reading"]["text"], "實際原讀")
            self.assertEqual(record["video_sha256"], hashlib.sha256(video.read_bytes()).hexdigest())
            self.assertFalse(record["regionManuallyConfirmed"])
            self.assertFalse(record["audio_transcribed"])
            self.assertEqual(record["accuracy"], "machine_unverified")
            if final != "raise":
                with zipfile.ZipFile(out / ("字幕画面工作包.zip" if include_frames else "字幕工作包.zip")) as archive:
                    self.assertEqual(json.loads(archive.read("字幕识别记录.json"))["raw"], record["raw"])
                    if include_frames:
                        self.assertEqual(archive.read("画面/001_01_0.05秒.jpg"), bytes([255, 216, 255, 217]))
                    else:
                        self.assertFalse(any(name.startswith("画面/") or name.endswith(".html") for name in archive.namelist()))
                self.assertEqual((out / "视频字幕.txt").read_text(encoding="utf-8-sig"), "TIMED working candidate")
                self.assertEqual((out / "字幕正文.txt").read_text(encoding="utf-8-sig"), "PLAIN working candidate")
            return summary, record

    def test_actual_shipped_manifest_checks_all_files_without_initializing_model(self):
        receipt = native.runtime_receipt()
        self.assertIn("subtitles/vendor/precision-rec.onnx", receipt["sha256"])
        self.assertIn("lib/subtitle-working-candidates-v198.js", receipt["sha256"])
        self.assertEqual(receipt["releaseStatus"], "candidate_not_accepted")

    def test_native_mocks_export_same_full_record_and_close_browser(self):
        summary, record = self.run_case()
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(record["runtimeVerification"], "unchanged_before_after_run")

    def test_partial_keeps_actual_originals_and_is_not_complete(self):
        summary, record = self.run_case("partial")
        self.assertEqual(summary["exit_code"], 3)
        self.assertEqual(record["state"], "partial")

    def test_images_require_explicit_selection(self):
        summary, record = self.run_case(include_frames=True)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(record["captureMode"], "with_frames")

    def test_interrupt_preserves_last_raw_checkpoint(self):
        summary, record = self.run_case("raise")
        self.assertEqual(record["state"], "partial")
        self.assertIn("已有原始记录保留", record["error"])

    def test_no_overwrite_of_any_existing_output(self):
        with temporary() as directory:
            root = Path(directory)
            (root / "original").write_bytes(b"keep")
            with self.assertRaises(ValueError):
                native.validate_outputs(root)
            self.assertEqual((root / "original").read_bytes(), b"keep")

    def test_frame_output_path_is_owned_and_cannot_traverse(self):
        with temporary() as directory:
            root = Path(directory)
            self.assertEqual(native.safe_image_path(root, "画面/001_01_0.05秒.jpg").parent, root / "画面")
            for path in ["../evil.jpg", "images/../evil.jpg", "/absolute.jpg", "画面/../../evil.jpg"]:
                with self.assertRaises(ValueError):
                    native.safe_image_path(root, path)

    def test_record_identity_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            native.record_result({"raw": {}, "sourceIdentity": {"kind": "local_file_sha256", "sha256": "b" * 64}},
                                 {"video_sha256": "a" * 64}, {}, "test")

    def test_direct_modes_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fixed.main(["--video-file", "dummy", "--out", "out", "--region", "0,.7,1,.8", "--detected-lines"])

    def args(self, *values):
        return foundation.build_parser().parse_args(["all", "--video", "https://www.douyin.com/video/7000000000000000001",
                    "--profile-dir", "private", "--out", "out", *values])

    def test_foundation_default_remains_no_subtitles(self):
        self.assertIsNone(foundation.validate_subtitle_args(self.args()))

    def test_foundation_detected_requires_explicit_subtitles(self):
        with self.assertRaises(foundation.FoundationError):
            foundation.validate_subtitle_args(self.args("--subtitle-detected-lines"))

    def test_foundation_region_and_detected_never_silently_ignore_region(self):
        with self.assertRaises(foundation.FoundationError):
            foundation.validate_subtitle_args(self.args("--subtitles", "--subtitle-detected-lines", "--subtitle-region", "0,.7,1,.8"))

    def test_foundation_detected_plan_has_no_fictitious_confirmed_region(self):
        args = self.args("--subtitles", "--subtitle-detected-lines")
        self.assertEqual(foundation.validate_subtitle_args(args), {"mode": "native_detected_lines", "include_frames": False})
        plan = foundation.all_plan(args)["subtitles"]
        self.assertEqual(plan["mode"], "native_detected_lines")
        self.assertIsNone(plan["region"])
        self.assertTrue(plan["automatic_detection"])

    def test_foundation_legacy_region_contract_unchanged(self):
        args = self.args("--subtitles", "--subtitle-region", "0,.7,1,.8")
        self.assertEqual(foundation.validate_subtitle_args(args), fixed.parse_region("0,.7,1,.8"))

if __name__ == "__main__":
    unittest.main()
