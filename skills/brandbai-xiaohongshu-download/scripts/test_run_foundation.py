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


if __name__ == "__main__":
    unittest.main()
