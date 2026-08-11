import json
import tempfile
import unittest
from pathlib import Path

from collector_core import (
    CollectionError, atomic_write_json, canonical_handle, canonical_profile_url,
    canonical_work_id, canonical_work_url, comment_completion_state, freeze_search_results,
    parse_metric, sanitize_media_url, select_profile_works, stable_pseudonym, work_type_from_url,
)


class CollectorCoreTests(unittest.TestCase):
    def test_canonical_routes(self):
        video = "https://www.tiktok.com/@demo/video/7654321098765432101?lang=en"
        photo = "https://www.tiktok.com/@demo/photo/7654321098765432102"
        self.assertEqual(canonical_work_id(video), "7654321098765432101")
        self.assertEqual(work_type_from_url(photo), "photo")
        self.assertEqual(canonical_handle(video), "demo")
        self.assertEqual(canonical_profile_url("@demo"), "https://www.tiktok.com/@demo")
        self.assertEqual(canonical_work_url(photo), photo)

    def test_rejects_other_platform_and_bad_media(self):
        with self.assertRaises(ValueError):
            canonical_work_id("https://example.com/@demo/video/7654321098765432101")
        with self.assertRaises(CollectionError):
            sanitize_media_url("https://example.com/file.mp4")
        clean, transient = sanitize_media_url("https://v16.tiktokcdn.com/file.mp4?token=temporary")
        self.assertEqual(clean, "https://v16.tiktokcdn.com/file.mp4")
        self.assertTrue(transient)

    def test_metric_and_pseudonym(self):
        self.assertEqual(parse_metric("1.2K"), 1200)
        self.assertEqual(parse_metric("3M"), 3_000_000)
        self.assertIsNone(parse_metric("unknown"))
        self.assertEqual(stable_pseudonym("author"), stable_pseudonym("author"))

    def test_profile_selection_pinned_is_additional(self):
        result = select_profile_works([
            {"work_id": "1", "is_pinned": True},
            {"work_id": "2", "is_pinned": False},
            {"work_id": "3", "is_pinned": False},
        ], 2)
        self.assertEqual([row["work_id"] for row in result["selected"]], ["1", "2", "3"])
        self.assertEqual(result["state"], "complete_visible_pinned_plus_recent_n")

    def test_search_freezes_original_rank(self):
        result = freeze_search_results([
            {"work_id": "1", "rank": 1}, {"work_id": "2", "rank": 2}
        ], keyword="skincare", tab="photo", filters=["relevance"], limit=2, captured_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(result["state"], "complete_first_n_visible_results")
        self.assertEqual(result["results"][1]["rank"], 2)

    def test_comment_completion(self):
        self.assertEqual(comment_completion_state(exhausted=True, limit_reached=False, replies_requested=False), "complete_source_visible")
        self.assertEqual(comment_completion_state(exhausted=False, limit_reached=True, replies_requested=False), "partial_limit_sample")
        self.assertEqual(comment_completion_state(exhausted=True, limit_reached=False, replies_requested=True,
                                                  declared_reply_count=2, saved_reply_count=0), "partial_reply_not_expanded")

    def test_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data" / "manifest.json"
            atomic_write_json(target, {"ok": True})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})


if __name__ == "__main__":
    unittest.main()
