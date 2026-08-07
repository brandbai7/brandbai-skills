from __future__ import annotations

import unittest

from collector_core import (
    CollectionError,
    canonical_note_id,
    canonical_note_url,
    canonical_profile_id,
    canonical_profile_url,
    comment_completion_state,
    freeze_search_results,
    select_profile_notes,
    sanitize_media_url,
    stable_pseudonym,
)


class CollectorCoreTests(unittest.TestCase):
    def test_note_id_from_explore_url(self) -> None:
        self.assertEqual(canonical_note_id("https://www.xiaohongshu.com/explore/abc123?xsec_token=x"), "abc123")

    def test_rejects_other_hosts(self) -> None:
        with self.assertRaises(ValueError):
            canonical_note_id("https://example.com/explore/abc123")

    def test_search_result_url_normalizes_without_token(self) -> None:
        source = "https://www.xiaohongshu.com/search_result/0123456789abcdef01234567?xsec_token=secret"
        self.assertEqual(canonical_note_id(source), "0123456789abcdef01234567")
        self.assertEqual(canonical_note_url(source), "https://www.xiaohongshu.com/explore/0123456789abcdef01234567")

    def test_profile_url_normalizes_without_token(self) -> None:
        source = "https://www.xiaohongshu.com/user/profile/profile-1?xsec_token=secret"
        self.assertEqual(canonical_profile_id(source), "profile-1")
        self.assertEqual(canonical_profile_url(source), "https://www.xiaohongshu.com/user/profile/profile-1")

    def test_note_id_from_profile_detail_url(self) -> None:
        source = "https://www.xiaohongshu.com/user/profile/profile-1/note-1?xsec_token=secret"
        self.assertEqual(canonical_note_id(source), "note-1")

    def test_media_url_is_allowlisted_and_query_redacted(self) -> None:
        clean, redacted = sanitize_media_url("http://sns-webpic-qc.xhscdn.com/path/a.webp?token=secret#x")
        self.assertEqual(clean, "https://sns-webpic-qc.xhscdn.com/path/a.webp")
        self.assertTrue(redacted)
        with self.assertRaises(CollectionError):
            sanitize_media_url("https://example.com/a.webp")

    def test_profile_selection_keeps_all_pinned_plus_recent(self) -> None:
        records = [
            {"note_id": "p1", "is_pinned": True},
            {"note_id": "n1", "is_pinned": False},
            {"note_id": "p2", "is_pinned": True},
            {"note_id": "n2", "is_pinned": False},
            {"note_id": "n3", "is_pinned": False},
        ]
        result = select_profile_notes(records, 2)
        self.assertEqual([row["note_id"] for row in result["selected"]], ["p1", "p2", "n1", "n2"])
        self.assertEqual(
            [row["selection_reason"] for row in result["selected"]],
            ["pinned", "pinned", "recent_non_pinned", "recent_non_pinned"],
        )
        self.assertEqual(result["state"], "complete_visible_pinned_plus_recent_n")

    def test_search_preserves_rank_and_context(self) -> None:
        result = freeze_search_results(
            [{"note_id": "a"}, {"note_id": "b"}], keyword="洗脸巾", tab="全部", filters=["综合"], limit=2,
            related_queries=["洗脸巾排行榜"], captured_at="2026-08-07T00:00:00+00:00",
        )
        self.assertEqual([row["rank"] for row in result["results"]], [1, 2])
        self.assertEqual(result["results"][0]["keyword"], "洗脸巾")
        self.assertEqual(result["state"], "complete_first_n_visible_results")

    def test_search_deduplicates_note_id_before_limit(self) -> None:
        result = freeze_search_results(
            [{"note_id": "a", "rank": 1}, {"note_id": "a", "rank": 2}, {"note_id": "b", "rank": 3}],
            keyword="测试", tab="全部", filters=["综合"], limit=2, captured_at="2026-08-07T00:00:00+00:00",
        )
        self.assertEqual([row["note_id"] for row in result["results"]], ["a", "b"])
        self.assertEqual([row["rank"] for row in result["results"]], [1, 3])

    def test_reply_shortfall_is_partial(self) -> None:
        state = comment_completion_state(
            exhausted=True, limit_reached=False, declared_reply_count=5, saved_reply_count=2, replies_requested=True,
        )
        self.assertEqual(state, "partial_reply_not_expanded")

    def test_pseudonym_is_stable(self) -> None:
        self.assertEqual(stable_pseudonym("user-a"), stable_pseudonym("user-a"))
        self.assertNotEqual(stable_pseudonym("user-a"), stable_pseudonym("user-b"))


if __name__ == "__main__":
    unittest.main()
