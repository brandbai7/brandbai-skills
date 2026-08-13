from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from run_foundation import main
from test_support import workspace_temp


class RunFoundationTests(unittest.TestCase):
    def test_dry_run_normalizes_targets_without_opening_browser(self) -> None:
        with workspace_temp() as temp:
            base = Path(temp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "all",
                    "--item", "https://detail.tmall.com/item.htm?id=123456789&skuId=987654&spm=tracking",
                    "--item", "123456789",
                    "--profile-dir", str(base / "private-profile"),
                    "--out", str(base / "delivery"),
                    "--assets", "main_images,detail_images",
                    "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(len(plan["items"]), 1)
            self.assertEqual(plan["items"][0]["canonical_url"], "https://detail.tmall.com/item.htm?id=123456789")
            self.assertEqual(plan["items"][0]["navigation_url"], "https://detail.tmall.com/item.htm?id=123456789&skuId=987654")
            self.assertEqual(plan["privacy_mode"], "pseudonymized")
            self.assertFalse((base / "delivery").exists())

    def test_profile_cannot_be_inside_delivery(self) -> None:
        with workspace_temp() as temp:
            out = Path(temp) / "delivery"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "product", "--item", "123456789",
                    "--profile-dir", str(out / "profile"),
                    "--out", str(out), "--dry-run",
                ])
            self.assertEqual(code, 2)

    def test_questions_dry_run_has_independent_delivery_scope(self) -> None:
        with workspace_temp() as temp:
            base = Path(temp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "questions", "--item", "123456789", "--question-limit", "80",
                    "--profile-dir", str(base / "private-profile"),
                    "--out", str(base / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["mode"], "questions")
            self.assertEqual(plan["question_limit"], 80)
            self.assertEqual(plan["delivery_scope"], ["questions"])


if __name__ == "__main__":
    unittest.main()
