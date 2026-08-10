from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from run_foundation import main


class RunFoundationTests(unittest.TestCase):
    def test_dry_run_builds_post_plan_without_launching_browser(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "all", "--post", "https://weibo.com/2712305611/RbNQaAljk?secret=1",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"),
                    "--assets", "images,cover", "--include-replies", "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["posts"][0]["post_id"], "RbNQaAljk")
            self.assertEqual(plan["posts"][0]["canonical_url"], "https://weibo.com/2712305611/RbNQaAljk")
            self.assertEqual(plan["privacy_mode"], "interaction_authors_pseudonymized")

    def test_rejects_profile_directory_inside_delivery(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            with redirect_stderr(io.StringIO()):
                code = main([
                    "posts", "--post", "RbNQaAljk", "--profile-dir", str(root / "delivery" / "profile"),
                    "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 2)

    def test_dry_run_builds_supertopic_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            source = "https://weibo.com/p/1008081c60117765725e0da0e23007ba00d630/super_index?mod=TAB"
            with redirect_stdout(buffer):
                code = main([
                    "posts", "--supertopic", source, "--supertopic-tab", "latest", "--search-limit", "3",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["supertopic"]["selected_tab"], "最新")
            self.assertEqual(plan["supertopic"]["first_visible_results"], 3)

    def test_dry_run_builds_entertainment_hotlist_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "posts", "--hotlist", "文娱", "--hotlist-limit", "50",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["hotlist"]["category_code"], "entrank")
            self.assertEqual(plan["hotlist"]["ranked_limit"], 50)
            self.assertEqual(plan["hotlist"]["visible_pinned_and_special_rows"], "additional")


if __name__ == "__main__":
    unittest.main()
