from __future__ import annotations

import unittest

from collector_core import (
    CollectionError,
    canonical_post_id,
    canonical_hotlist_url,
    canonical_post_url,
    canonical_profile_id,
    canonical_profile_url,
    canonical_search_url,
    canonical_supertopic_id,
    canonical_supertopic_url,
    comment_completion_state,
    freeze_search_results,
    freeze_hotlist_snapshot,
    normalize_hotlist_category,
    normalize_supertopic_tab,
    repost_completion_state,
    sanitize_media_url,
    select_profile_posts,
    stable_pseudonym,
)


class CollectorCoreTests(unittest.TestCase):
    def test_post_reference_normalizes_without_query(self) -> None:
        source = "https://weibo.com/2712305611/RbNQaAljk?refer_flag=secret"
        self.assertEqual(canonical_post_id(source), "RbNQaAljk")
        self.assertEqual(canonical_post_url(source), "https://weibo.com/2712305611/RbNQaAljk")

    def test_mobile_detail_and_profile_normalize(self) -> None:
        self.assertEqual(canonical_post_id("https://m.weibo.cn/detail/RbNQaAljk"), "RbNQaAljk")
        self.assertEqual(canonical_profile_id("https://weibo.com/u/2712305611?tabtype=feed"), "2712305611")
        self.assertEqual(canonical_profile_url("2712305611"), "https://weibo.com/u/2712305611")

    def test_rejects_other_hosts(self) -> None:
        with self.assertRaises(ValueError):
            canonical_post_id("https://example.com/2712305611/RbNQaAljk")

    def test_search_and_topic_urls(self) -> None:
        self.assertIn("q=%E6%98%8E%E6%98%9F", canonical_search_url("明星"))
        self.assertIn("%23%E5%93%81%E7%89%8C%23", canonical_search_url("#品牌#", topic=True))

    def test_supertopic_url_tab_and_snapshot(self) -> None:
        source = "https://weibo.com/p/1008081c60117765725e0da0e23007ba00d630/super_index?mod=TAB"
        self.assertEqual(canonical_supertopic_id(source), "1008081c60117765725e0da0e23007ba00d630")
        self.assertEqual(canonical_supertopic_url(source), source)
        self.assertEqual(normalize_supertopic_tab("latest"), "最新")
        snapshot = freeze_search_results(
            [{"post_id": "a", "rank": 1}], query="丁禹兮", query_kind="supertopic",
            sort="热门", filters=[], limit=1, captured_at="2026-08-09T00:00:00+00:00",
        )
        self.assertEqual(snapshot["query_kind"], "supertopic")

    def test_hotlist_snapshot_keeps_ranked_rows_plus_visible_extras(self) -> None:
        self.assertEqual(normalize_hotlist_category("entertainment"), ("entrank", "文娱"))
        self.assertEqual(canonical_hotlist_url("文娱"), "https://s.weibo.com/top/summary?cate=entrank")
        snapshot = freeze_hotlist_snapshot([
            {"observed_position": 1, "rank_text": "", "keyword": "置顶词", "is_pinned": True},
            {"observed_position": 2, "rank_text": "1", "rank_numeric": 1, "keyword": "第一名", "heat_text": "100万"},
            {"observed_position": 3, "rank_text": "2", "rank_numeric": 2, "keyword": "第二名"},
            {"observed_position": 4, "rank_text": "•", "keyword": "特殊行", "is_special": True},
        ], category="文娱", ranked_limit=2, captured_at="2026-08-09T00:00:00+00:00")
        self.assertEqual(snapshot["saved_ranked"], 2)
        self.assertEqual(snapshot["saved_extras"], 2)
        self.assertEqual(snapshot["state"], "complete_ranked_hotlist_plus_visible_extras")

    def test_media_url_is_allowlisted_and_query_redacted(self) -> None:
        clean, redacted = sanitize_media_url("http://wx1.sinaimg.cn/large/a.jpg?token=secret#x")
        self.assertEqual(clean, "https://wx1.sinaimg.cn/large/a.jpg")
        self.assertTrue(redacted)
        with self.assertRaises(CollectionError):
            sanitize_media_url("https://example.com/a.jpg")

    def test_profile_selection_keeps_all_pinned_plus_recent(self) -> None:
        result = select_profile_posts([
            {"post_id": "p1", "is_pinned": True},
            {"post_id": "n1", "is_pinned": False},
            {"post_id": "p2", "is_pinned": True},
            {"post_id": "n2", "is_pinned": False},
            {"post_id": "n3", "is_pinned": False},
        ], 2)
        self.assertEqual([row["post_id"] for row in result["selected"]], ["p1", "p2", "n1", "n2"])
        self.assertEqual(result["state"], "complete_visible_pinned_plus_recent_n")

    def test_search_snapshot_preserves_rank_and_context(self) -> None:
        result = freeze_search_results(
            [{"post_id": "a", "rank": 1}, {"post_id": "b", "rank": 3}],
            query="代言", query_kind="keyword", sort="综合", filters=["全部"], limit=2,
            captured_at="2026-08-09T00:00:00+00:00",
        )
        self.assertEqual([row["rank"] for row in result["results"]], [1, 3])
        self.assertEqual(result["state"], "complete_first_n_visible_results")

    def test_comment_and_repost_partial_states_are_explicit(self) -> None:
        self.assertEqual(comment_completion_state(
            exhausted=True, limit_reached=False, declared_reply_count=5,
            saved_reply_count=2, replies_requested=True,
        ), "partial_reply_not_expanded")
        self.assertEqual(repost_completion_state(
            exhausted=False, limit_reached=False, available=False,
        ), "partial_reposts_not_available")

    def test_comment_completion_explains_login_budget_and_dual_sort(self) -> None:
        common = {
            "exhausted": False, "limit_reached": False,
            "declared_reply_count": 0, "saved_reply_count": 0,
            "replies_requested": False,
        }
        self.assertEqual(comment_completion_state(
            **common, login_limited=True,
        ), "partial_login_required")
        self.assertEqual(comment_completion_state(
            **common, scroll_budget_exhausted=True,
        ), "partial_scroll_budget_exhausted")
        self.assertEqual(comment_completion_state(
            exhausted=True, limit_reached=False, declared_reply_count=0,
            saved_reply_count=0, replies_requested=False,
            sort_modes_available=["按热度", "按时间"],
            sort_modes_exhausted=["按热度", "按时间"],
        ), "complete_visible_both_sorts_exhausted")

    def test_pseudonym_is_stable(self) -> None:
        self.assertEqual(stable_pseudonym("user-a"), stable_pseudonym("user-a"))
        self.assertNotEqual(stable_pseudonym("user-a"), stable_pseudonym("user-b"))


if __name__ == "__main__":
    unittest.main()
