import tempfile
import unittest
from pathlib import Path

from collector_core import CollectionError
from run_foundation import build_parser, build_plan, main


class RunFoundationTests(unittest.TestCase):
    def test_dry_run_single_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            out = Path(tmp) / "delivery"
            code = main(["all", "--work", "https://www.tiktok.com/@demo/photo/7654321098765432101",
                         "--profile-dir", str(profile), "--out", str(out), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertFalse(out.exists())

    def test_profile_requires_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = build_parser().parse_args(["all", "--profile", "@demo", "--profile-dir", str(Path(tmp) / "p"),
                                              "--out", str(Path(tmp) / "o")])
            with self.assertRaises(CollectionError):
                build_plan(args)

    def test_photo_search_plan_and_paid_features_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = build_parser().parse_args(["batch", "--search", "skincare", "--search-tab", "photo",
                                              "--profile-dir", str(Path(tmp) / "p"), "--out", str(Path(tmp) / "o")])
            plan = build_plan(args)
            self.assertIn("/search/photo", plan["search"]["url"])
            self.assertEqual(plan["paid_features"]["speech_to_text"], "disabled_coming_soon")

    def test_market_scan_context_is_frozen_without_region_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = build_parser().parse_args([
                "batch", "--search", "sensitive skin moisturizer", "--search-tab", "video",
                "--business-preset", "market-scan", "--market-scope", "US",
                "--source-locale", "en-US", "--search-language", "en",
                "--observation-timezone", "America/New_York", "--downstream-use", "content-diagnosis",
                "--profile-dir", str(Path(tmp) / "p"), "--out", str(Path(tmp) / "o"),
            ])
            context = build_plan(args)["business_context"]
            self.assertEqual(context["business_preset"], "market-scan")
            self.assertEqual(context["market_scope"], "US")
            self.assertEqual(context["source_surface"], "public_tiktok")
            self.assertEqual(context["search_query_original"], "sensitive skin moisturizer")
            self.assertEqual(context["authorization_mode"], "public_visible")

    def test_rejects_profile_inside_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = build_parser().parse_args(["batch", "--profile", "@demo", "--profile-dir", str(root / "delivery" / "profile"),
                                              "--out", str(root / "delivery")])
            with self.assertRaises(CollectionError):
                build_plan(args)


if __name__ == "__main__":
    unittest.main()
