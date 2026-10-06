"""Portable wrapper tests: synthetic media, no model execution or network."""
import asyncio
import contextlib
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import extract_video_subtitles as subtitles
from run_foundation import run_subtitle_stage
import test_video_subtitles as fixtures
from test_video_subtitles import temporary


def bundle(root):
    assets = root / "assets"
    vendor = assets / "vendor"
    vendor.mkdir(parents=True)
    for name in ["engine.js", "recognizer.js", "recognizer-worker.js"]:
        (assets / name).write_text("// synthetic 中文规则：不能喝一杯。 " + name, encoding="utf-8")
    hashes = {}
    for name in ["rec.onnx", "keys.txt", "ort/runtime.js"]:
        path = vendor / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"engine": "synthetic-recognizer", "model_version": "test-2", "model_registry": "local-fixture",
                "packages": {"runtime": "test-1"}, "sha256": hashes}
    (vendor / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return assets, manifest


class RuntimeReceiptTests(unittest.TestCase):
    def test_actual_bundle_identity_and_hashes(self):
        with temporary() as root:
            assets, manifest = bundle(root)
            with patch.object(subtitles, "ASSETS", assets):
                receipt = subtitles.runtime_receipt()
            self.assertEqual(receipt["engineName"], manifest["engine"])
            self.assertEqual(receipt["engineVersion"], "test-2")
            self.assertEqual(receipt["wrapperVersion"], "0.6.3")
            self.assertEqual(receipt["modelSha256"], manifest["sha256"]["rec.onnx"])
            self.assertEqual(set(receipt["codeSha256"]), {"engine.js", "recognizer.js", "recognizer-worker.js"})

    def test_runtime_change_during_run_cannot_claim_verified_version(self):
        with temporary() as root:
            assets, unused_manifest = bundle(root)
            with patch.object(subtitles, "ASSETS", assets):
                receipt = subtitles.runtime_receipt()
                subtitles.verify_runtime_unchanged(receipt)
                (assets / "engine.js").write_text("// changed during run", encoding="utf-8")
                with self.assertRaises(ValueError): subtitles.verify_runtime_unchanged(receipt)

    def test_missing_or_tampered_assets_fail_before_model(self):
        for action in ["missing", "tampered", "missing_model_hash", "outside", "bad_hash"]:
            with self.subTest(action=action), temporary() as root:
                assets, manifest = bundle(root)
                if action == "missing":
                    (assets / "recognizer.js").unlink()
                elif action == "tampered":
                    (assets / "vendor/rec.onnx").write_bytes(b"changed")
                else:
                    if action == "missing_model_hash": del manifest["sha256"]["rec.onnx"]
                    if action == "outside": manifest["sha256"]["../engine.js"] = hashlib.sha256((assets / "engine.js").read_bytes()).hexdigest()
                    if action == "bad_hash": manifest["sha256"]["rec.onnx"] = "not-a-hash"
                    (assets / "vendor/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                with patch.object(subtitles, "ASSETS", assets), self.assertRaises(ValueError):
                    subtitles.runtime_receipt()

    def test_result_preserves_raw_evidence_and_source_identity(self):
        runtime = {"engineName": "synthetic-recognizer", "engineVersion": "test-2"}
        raw = [{"time": 0.5, "text": "合成测试", "confidence": 80}]
        state = {"state": "partial", "engine": runtime["engineName"], "observations": raw, "segments": [],
                 "workId": "wrong", "accuracy": "verified", "uploaded": True}
        identity = {"workId": "7000000000000000001", "video_sha256": "a" * 64}
        payload = subtitles.result_record(identity, state, {"top": .7}, .5, runtime)
        self.assertEqual(payload["workId"], identity["workId"])
        self.assertEqual(payload["observations"], raw)
        self.assertEqual(payload["accuracy"], "machine_unverified")
        self.assertFalse(payload["uploaded"])
        self.assertFalse(payload["audio_transcribed"])
        self.assertEqual(payload["interval"], .5)
        self.assertEqual(state["workId"], "wrong")

    def test_conflicting_runtime_and_invalid_result_are_rejected(self):
        runtime = {"engineName": "current-model"}
        for state in [{"engine": "old-model", "segments": []}, {"segments": "invalid"}, []]:
            with self.subTest(state=state), self.assertRaises(ValueError):
                subtitles.result_record({}, state, {}, .5, runtime)

    def test_video_limit_and_interval_are_checked(self):
        with temporary() as root:
            video = root / "test.mp4"
            video.write_bytes(b"synthetic")
            for interval in [True, float("nan"), float("inf"), 0, 1.1]:
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    subtitles.validate_video(video, interval)
            with patch.object(subtitles, "MAX_BYTES", 1), self.assertRaises(ValueError):
                subtitles.validate_video(video, .5)
            video.write_bytes(b"")
            with self.assertRaises(ValueError): subtitles.validate_video(video, .5)


class FakeBrowser:
    def __init__(self, final="processed"):
        self.final = final
        self.closed = False
        self.script = None
        self.parameters = None
        self.callback = None

    async def launch(self, **options):
        self.options = options
        return self

    async def new_context(self, **options):
        self.context_options = options
        return self

    async def route(self, pattern, handler): self.route_handler = handler
    async def new_page(self): return self
    async def expose_function(self, name, callback): self.callback = callback
    async def goto(self, url):
        self.url = url
        self.served = {}
        for path in ["/", "/engine.js"]:
            route = types.SimpleNamespace(request=types.SimpleNamespace(url=url + path), fulfill=AsyncMock(), abort=AsyncMock())
            await self.route_handler(route)
            self.served[path] = route.fulfill.await_args.kwargs
    async def close(self): self.closed = True

    async def evaluate(self, script, parameters):
        self.script, self.parameters = script, parameters
        result = {"state": "running", "engine": "synthetic-recognizer", "processed": 1, "total": 2,
                  "observations": [{"time": .5, "text": "合成字幕"}],
                  "segments": [{"text": "合成字幕", "firstObserved": .5, "lastObserved": .5}]}
        self.callback(result)
        if self.final == "raise": raise RuntimeError("synthetic interruption")
        return {**result, "state": self.final, "processed": 2}

    async def __aenter__(self): return types.SimpleNamespace(chromium=self)
    async def __aexit__(self, *unused): return False


class ExtractContractTests(unittest.TestCase):
    def run_extract(self, final="processed"):
        with temporary() as root:
            assets, unused_manifest = bundle(root)
            video = root / "source.mp4"
            video.write_bytes(b"synthetic video; never decoded")
            out = root / "result"
            fake = FakeBrowser(final)
            parent_module, module = types.ModuleType("playwright"), types.ModuleType("playwright.async_api")
            module.async_playwright = lambda: fake
            parent_module.async_api = module
            selected = subtitles.parse_region(".1,.7,.9,.8")
            with patch.dict(sys.modules, {"playwright": parent_module, "playwright.async_api": module}), \
                 patch.object(subtitles, "ASSETS", assets), patch.object(subtitles, "chrome_path", return_value=None), \
                 contextlib.redirect_stdout(io.StringIO()):
                operation = subtitles.extract(video, out, selected, work_id="7000000000000000001")
                if final == "raise":
                    with self.assertRaises(RuntimeError): asyncio.run(operation)
                    summary = None
                else:
                    summary = asyncio.run(operation)
            record = json.loads((out / "字幕识别记录.json").read_text(encoding="utf-8"))
            text = (out / "视频字幕.txt").read_text(encoding="utf-8-sig")
            self.assertTrue(fake.closed)
            self.assertTrue(fake.options["headless"])
            self.assertEqual(fake.context_options["service_workers"], "block")
            # Exercise the actual response handler, not just source matching.
            # An absent charset would use the old Windows-1252 fallback here.
            html = fake.served["/"]
            headers = Message(); headers["Content-Type"] = html["content_type"]
            self.assertEqual(headers.get_content_charset(), "utf-8")
            self.assertIn('<meta charset="utf-8">', html["body"])
            javascript = fake.served["/engine.js"]
            headers = Message(); headers["Content-Type"] = javascript["content_type"]
            decoded = Path(javascript["path"]).read_bytes().decode(headers.get_content_charset() or "windows-1252")
            self.assertIn("中文规则：不能喝一杯。", decoded)
            self.assertIn("new BrandbaiSubtitles.Session", fake.script)
            self.assertEqual(fake.parameters["selected"], selected)
            self.assertEqual(fake.parameters["interval"], .5)
            self.assertEqual(record["workId"], "7000000000000000001")
            self.assertEqual(record["video_sha256"], hashlib.sha256(video.read_bytes()).hexdigest())
            self.assertEqual(record["runtime"]["engineVersion"], "test-2")
            self.assertIn("[00:00.50–00:00.50] 合成字幕", text)
            return summary, record

    def test_success_runs_same_browser_engine_and_records_receipt(self):
        summary, record = self.run_extract()
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["runtime"], record["runtime"])
        self.assertEqual(record["runtimeVerification"], "unchanged_before_after_run")
        self.assertEqual(len(record["observations"]), 1)

    def test_partial_is_not_relabelled_complete(self):
        summary, record = self.run_extract("partial")
        self.assertEqual(summary["exit_code"], 3)
        self.assertEqual(record["state"], "partial")

    def test_interruption_retains_original_observations(self):
        unused_summary, record = self.run_extract("raise")
        self.assertEqual(record["state"], "failed")
        self.assertEqual(len(record["observations"]), 1)
        self.assertEqual(record["segments"][0]["text"], "合成字幕")

    def test_existing_output_is_not_overwritten(self):
        with temporary() as root:
            video = root / "test.mp4"; video.write_bytes(b"synthetic")
            out = root / "out"; out.mkdir()
            record = out / "字幕识别记录.json"; record.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                asyncio.run(subtitles.extract(video, out, subtitles.parse_region("0,.7,1,.8")))
            self.assertEqual(record.read_bytes(), b"keep")

    def test_runtime_environment_failure_returns_partial_exit_code(self):
        with temporary() as root:
            video = root / "test.mp4"; video.write_bytes(b"synthetic")
            with patch.object(subtitles, "extract", new_callable=AsyncMock, side_effect=PermissionError("synthetic")), \
                 contextlib.redirect_stderr(io.StringIO()):
                code = subtitles.main(["--video-file", str(video), "--out", str(root / "out"), "--region", "0,.7,1,.8"])
            self.assertEqual(code, 3)

    def test_download_handoff_uses_exact_record_without_second_file_selection(self):
        with temporary() as root:
            folder = root / "03_作品素材" / "one"; folder.mkdir(parents=True)
            video = folder / "download.mp4"; video.write_bytes(b"synthetic")
            work_id = "7000000000000000001"
            work = {"aweme_id": work_id, "type": "视频", "local_folder": "03_作品素材/one",
                    "downloads": {"video": {"status": "downloaded", "file": "download.mp4"}}}
            data = root / "works.json"; data.write_text(json.dumps([work]), encoding="utf-8")
            args = fixtures.SubtitleTests().args("--subtitles", "--subtitle-region", "0,.7,1,.8")
            receipt = {"engineName": "synthetic-recognizer", "engineVersion": "test-2"}
            with patch.object(subtitles, "extract", new_callable=AsyncMock,
                              return_value={"requested": True, "state": "processed", "exit_code": 0, "runtime": receipt}) as extract:
                result = run_subtitle_stage(args, data, root)
            extract.assert_awaited_once_with(video, folder / "字幕", subtitles.parse_region("0,.7,1,.8"), executable=args.chrome_path, work_id=work_id)
            self.assertEqual(result["runtime"], receipt)
            self.assertEqual(result["folder"], "03_作品素材/one/字幕")


if __name__ == "__main__": unittest.main()
