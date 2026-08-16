from __future__ import annotations

import contextlib
import io
import json
import shutil
import unittest
from pathlib import Path

from run_foundation import main


class RunFoundationTests(unittest.TestCase):
    def test_dry_run_redacts_transient_navigation_context(self) -> None:
        base = Path(__file__).resolve().parent / ".xhs_run_dry_test_runtime"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir()
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "all",
                    "--note", "https://www.xiaohongshu.com/search_result/0123456789abcdef01234567?xsec_token=secret&xsec_source=pc_search",
                    "--profile-dir", str(base / "private-profile"),
                    "--out", str(base / "delivery"),
                    "--assets", "images,cover",
                    "--dry-run",
                ])
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertNotIn("secret", text)
            plan = json.loads(text)
            self.assertEqual(plan["notes"][0]["note_id"], "0123456789abcdef01234567")
            self.assertEqual(plan["notes"][0]["canonical_url"], "https://www.xiaohongshu.com/explore/0123456789abcdef01234567")
            self.assertEqual(plan["navigation_context"], "used_in_memory_only")
            self.assertEqual(plan["privacy_mode"], "comment_authors_pseudonymized")
            self.assertEqual(plan["login_wait_seconds"], 180)
            self.assertFalse((base / "delivery").exists())
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_profile_cannot_be_inside_delivery(self) -> None:
        base = Path(__file__).resolve().parent / ".xhs_run_scope_test_runtime"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir()
        try:
            out = base / "delivery"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "note", "--note", "0123456789abcdef01234567",
                    "--profile-dir", str(out / "profile"),
                    "--out", str(out), "--dry-run",
                ])
            self.assertEqual(code, 2)
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_profile_dry_run_redacts_token_and_records_policy(self) -> None:
        base = Path(__file__).resolve().parent / ".xhs_profile_dry_test_runtime"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir()
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "batch",
                    "--profile", "https://www.xiaohongshu.com/user/profile/profile-1?xsec_token=secret",
                    "--recent", "5",
                    "--profile-dir", str(base / "private-profile"),
                    "--out", str(base / "delivery"),
                    "--assets", "none",
                    "--dry-run",
                ])
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertNotIn("secret", text)
            plan = json.loads(text)
            self.assertEqual(plan["profile"]["profile_id"], "profile-1")
            self.assertEqual(plan["profile"]["canonical_url"], "https://www.xiaohongshu.com/user/profile/profile-1")
            self.assertEqual(plan["profile"]["recent_non_pinned"], 5)
            self.assertEqual(plan["navigation_context"], "used_in_memory_only")
            self.assertFalse((base / "delivery").exists())
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_search_dry_run_records_first_n_visible_contract(self) -> None:
        base = Path(__file__).resolve().parent / ".xhs_search_dry_test_runtime"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir()
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "batch", "--search", "合成关键词", "--search-limit", "5", "--search-tab", "视频",
                    "--profile-dir", str(base / "private-profile"), "--out", str(base / "delivery"),
                    "--assets", "video,cover", "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["search"]["keyword"], "合成关键词")
            self.assertEqual(plan["search"]["tab"], "视频")
            self.assertEqual(plan["search"]["filters"], ["综合"])
            self.assertEqual(plan["search"]["first_visible_results"], 5)
            self.assertEqual(plan["notes"], [])
            self.assertFalse((base / "delivery").exists())
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_profile_rejects_detail_mode(self) -> None:
        base = Path(__file__).resolve().parent / ".xhs_profile_mode_test_runtime"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "all", "--profile", "profile-1",
                    "--profile-dir", str(base / "private-profile"),
                    "--out", str(base / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 2)
        finally:
            if base.exists():
                shutil.rmtree(base)


if __name__ == "__main__":
    unittest.main()
