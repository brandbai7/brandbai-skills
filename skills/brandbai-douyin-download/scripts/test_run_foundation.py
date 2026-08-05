import argparse
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from run_foundation import (
    FoundationError,
    all_plan,
    build_parser,
    child_command,
    load_work_urls,
    run_all,
    run_shared_browser_stages,
    unique_work_urls,
)


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_foundation_test_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


class RunFoundationTests(unittest.TestCase):
    def test_unique_work_urls_deduplicates_same_aweme_id(self):
        urls = unique_work_urls([
            "https://www.douyin.com/video/12345678901",
            "https://www.douyin.com/note/12345678901",
            "https://www.douyin.com/video/22345678901",
        ])
        self.assertEqual(len(urls), 2)

    def test_load_work_urls_preserves_note_route_and_falls_back_from_type(self):
        with workspace_temp() as temp:
            path = temp / "works.json"
            path.write_text(json.dumps([
                {"aweme_id": "12345678901", "type": "图文"},
                {
                    "aweme_id": "22345678901",
                    "type": "视频",
                    "source_url": "https://www.douyin.com/video/22345678901",
                },
            ]), encoding="utf-8")
            self.assertEqual(load_work_urls(path), [
                "https://www.douyin.com/note/12345678901",
                "https://www.douyin.com/video/22345678901",
            ])

    def test_works_command_delegates_without_analysis(self):
        args = build_parser().parse_args([
            "works", "--creator", "https://www.douyin.com/user/test",
            "--profile-dir", "profile", "--out", "out", "--dry-run",
        ])
        command = child_command(args, Path("scripts"))
        self.assertTrue(command[1].endswith("download_creator_works.py"))
        self.assertIn("--dry-run", command)
        self.assertNotIn("prepare_analysis_batches.py", " ".join(command))

    def test_works_command_can_place_media_in_delivery_folder(self):
        args = build_parser().parse_args([
            "works", "--creator", "https://www.douyin.com/user/test",
            "--profile-dir", "profile", "--out", "data/作品采集",
            "--media-dir", "03_作品素材", "--media-label", "03_作品素材",
        ])
        command = child_command(args, Path("scripts"))
        self.assertIn("--media-dir", command)
        self.assertIn("03_作品素材", command)

    def test_comments_command_uses_works_json_and_defaults_to_top_level(self):
        with workspace_temp() as temp:
            path = temp / "works.json"
            path.write_text(json.dumps([
                {"source_url": "https://www.douyin.com/video/12345678901"}
            ]), encoding="utf-8")
            args = build_parser().parse_args([
                "comments", "--works-json", str(path),
                "--profile-dir", "profile", "--out", "out", "--dry-run",
            ])
            command = child_command(args, Path("scripts"))
            self.assertTrue(command[1].endswith("browser_collect_comments.py"))
            self.assertIn("--works-json", command)
            self.assertIn(str(path), command)
            self.assertNotIn("--video", command)
            self.assertNotIn("--include-replies", command)

    def test_replies_are_explicit_opt_in(self):
        args = build_parser().parse_args([
            "comments", "--video", "https://www.douyin.com/video/12345678901",
            "--include-replies", "--profile-dir", "profile", "--out", "out",
        ])
        self.assertIn("--include-replies", child_command(args, Path("scripts")))

    def test_all_dry_run_describes_ordinary_delivery_without_running_children(self):
        args = build_parser().parse_args([
            "all", "--creator", "https://www.douyin.com/user/test", "--recent", "5",
            "--profile-dir", "profile", "--out", "delivery",
            "--dry-run",
        ])
        plan = all_plan(args)
        self.assertEqual(plan["ordinary_files"][0], "01_作品清单.xlsx")
        self.assertEqual(plan["comments"], "top-level only")
        self.assertEqual(plan["privacy_mode"], "hash")
        self.assertIn("one shared visible Chrome context", plan["browser_session"])
        self.assertFalse(plan["analysis_included"])
        self.assertTrue(plan["preview_dir"].endswith("delivery_QA"))

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("dry-run must not start browser or workbook processes")

        self.assertEqual(run_all(args, Path("scripts"), runner=must_not_run), 0)

    def test_all_runs_three_stages_into_one_delivery_tree(self):
        with workspace_temp() as temp:
            scripts = temp / "scripts"
            scripts.mkdir()
            for name in ("download_creator_works.py", "browser_collect_comments.py"):
                (scripts / name).write_text("", encoding="utf-8")
            (scripts / "build_foundation_workbooks.py").write_text("# test", encoding="utf-8")
            delivery = temp / "delivery"
            preview = temp / "preview"
            calls = []
            browser_calls = []

            class Result:
                def __init__(self, returncode=0):
                    self.returncode = returncode

            def fake_browser_stage_runner(works_args, comments_args, trace_path):
                browser_calls.append((works_args, comments_args, trace_path))
                works_out = Path(works_args.out)
                works_out.mkdir(parents=True, exist_ok=True)
                (works_out / "works.json").write_text(json.dumps([
                    {"source_url": "https://www.douyin.com/video/12345678901"}
                ]), encoding="utf-8")
                (works_out / "download_manifest.json").write_text("{}", encoding="utf-8")
                comments_out = Path(comments_args.out)
                comments_out.mkdir(parents=True, exist_ok=True)
                (comments_out / "comments.csv").write_text(
                    "aweme_id,text\n12345678901,test\n", encoding="utf-8"
                )
                (comments_out / "run_manifest.json").write_text("{}", encoding="utf-8")
                return 0, 0

            def fake_runner(command, **_kwargs):
                calls.append(command)
                delivery.mkdir(parents=True, exist_ok=True)
                preview.mkdir(parents=True, exist_ok=True)
                for name in ("01_作品清单.xlsx", "02_评论明细.xlsx", "04_采集说明.md"):
                    (delivery / name).write_text("test", encoding="utf-8")
                (preview / "workbook_qa.json").write_text("{}", encoding="utf-8")
                return Result(1)

            args = build_parser().parse_args([
                "all", "--creator", "https://www.douyin.com/user/test",
                "--profile-dir", str(temp / "profile"), "--out", str(delivery),
                "--preview-dir", str(preview),
            ])
            self.assertEqual(
                run_all(
                    args,
                    scripts,
                    runner=fake_runner,
                    browser_stage_runner=fake_browser_stage_runner,
                ),
                0,
            )
            self.assertEqual(len(browser_calls), 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(browser_calls[0][0].media_dir, str(delivery / "03_作品素材"))
            self.assertTrue((delivery / "data" / "作品采集" / "works.json").is_file())
            self.assertTrue((delivery / "data" / "评论采集" / "comments.csv").is_file())

    def test_shared_browser_stages_launch_once_and_reuse_context(self):
        with workspace_temp() as temp:
            launches = []
            seen_contexts = []

            class FakeContext:
                def __init__(self):
                    self.closed = False

                def close(self):
                    self.closed = True

            class FakeChromium:
                def launch_persistent_context(self, **kwargs):
                    launches.append(kwargs)
                    return FakeContext()

            class FakePlaywright:
                chromium = FakeChromium()

            @contextmanager
            def fake_playwright_factory():
                yield FakePlaywright()

            def fake_works(_args, browser_context=None):
                seen_contexts.append(browser_context)
                return 0

            def fake_comments(_args, browser_context=None):
                seen_contexts.append(browser_context)
                return 0

            works_args = argparse.Namespace(
                profile_dir=str(temp / "profile"), chrome_path=""
            )
            comments_args = argparse.Namespace()
            result = run_shared_browser_stages(
                works_args,
                comments_args,
                temp / "trace.jsonl",
                playwright_factory=fake_playwright_factory,
                works_runner=fake_works,
                comments_runner=fake_comments,
                chrome_finder=lambda _value: "chrome.exe",
            )
            self.assertEqual(result, (0, 0))
            self.assertEqual(len(launches), 1)
            self.assertIs(seen_contexts[0], seen_contexts[1])
            self.assertTrue(seen_contexts[0].closed)
            events = [json.loads(line) for line in (temp / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[0]["event"], "browser_session_start")
            self.assertEqual(events[-1]["event"], "browser_session_end")

    def test_shared_browser_launch_failure_still_closes_audit_trace(self):
        with workspace_temp() as temp:
            class FakeChromium:
                def launch_persistent_context(self, **_kwargs):
                    raise RuntimeError("synthetic launch failure")

            class FakePlaywright:
                chromium = FakeChromium()

            @contextmanager
            def fake_playwright_factory():
                yield FakePlaywright()

            works_args = argparse.Namespace(
                profile_dir=str(temp / "profile"), chrome_path=""
            )
            trace_path = temp / "trace.jsonl"
            with self.assertRaisesRegex(FoundationError, "Browser launch failed"):
                run_shared_browser_stages(
                    works_args,
                    argparse.Namespace(),
                    trace_path,
                    playwright_factory=fake_playwright_factory,
                    works_runner=lambda *_args, **_kwargs: 0,
                    comments_runner=lambda *_args, **_kwargs: 0,
                    chrome_finder=lambda _value: "chrome.exe",
                )
            events = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-2]["event"], "browser_session_launch_error")
            self.assertEqual(events[-1]["event"], "browser_session_end")
            self.assertNotIn("synthetic launch failure", trace_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
