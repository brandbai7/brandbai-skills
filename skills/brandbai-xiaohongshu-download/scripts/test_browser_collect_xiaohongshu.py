from __future__ import annotations

import json
import unittest

from browser_collect_xiaohongshu import (
    PROFILE_SCRIPT,
    SEARCH_SCRIPT,
    _normalize_comment_rows,
    _public_profile_selection,
    _public_search_snapshot,
    normalize_assets,
)
from collector_core import CollectionError


class BrowserCollectorContractTests(unittest.TestCase):
    def test_derived_comment_id_does_not_change_with_relative_time(self) -> None:
        base = {
            "level": 1,
            "author_name": "合成用户",
            "author_platform_id": "synthetic-user-1",
            "content": "仅用于稳定 ID 测试",
            "region_text": "测试地区",
            "like_count_text": "赞",
            "declared_reply_count": 0,
            "saved_reply_count": 0,
        }
        first = _normalize_comment_rows([{**base, "time_text": "2分钟前"}], "synthetic-note", False, False)[0]
        later = _normalize_comment_rows([{**base, "time_text": "1小时前"}], "synthetic-note", False, False)[0]
        self.assertEqual(first["comment_id"], later["comment_id"])
        self.assertNotEqual(first["time_text"], later["time_text"])

    def test_visible_reply_is_not_saved_when_not_requested(self) -> None:
        row = _normalize_comment_rows([{
            "level": 1,
            "author_platform_id": "synthetic-user-2",
            "content": "合成一级评论",
            "declared_reply_count": 0,
            "saved_reply_count": 1,
        }], "synthetic-note", False, False)[0]
        self.assertEqual(row["declared_reply_count"], 1)
        self.assertEqual(row["saved_reply_count"], 0)
        self.assertEqual(row["reply_expansion_status"], "not_requested")

    def test_asset_aliases_are_validated(self) -> None:
        self.assertEqual(normalize_assets("images,cover,images"), ["images", "cover"])
        with self.assertRaises(CollectionError):
            normalize_assets("images,unknown")

    def test_public_profile_selection_drops_transient_navigation_context(self) -> None:
        public = _public_profile_selection({
            "profile_selection_id": "selection-1",
            "profile_id": "profile-1",
            "selected": [{
                "note_id": "note-1",
                "rank": 1,
                "is_pinned": True,
                "selection_reason": "pinned",
                "title": "合成标题",
                "author_name": "合成作者",
                "cover_url": "https://sns-webpic-qc.xhscdn.com/a.webp?token=cover-secret",
                "navigation_url": "https://www.xiaohongshu.com/user/profile/profile-1/note-1?xsec_token=secret",
            }],
        })
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("navigation_url", serialized)
        self.assertNotIn("secret", serialized)
        self.assertEqual(public["selected"][0]["canonical_url"], "https://www.xiaohongshu.com/explore/note-1")

    def test_profile_metrics_read_number_and_label_from_shared_parent(self) -> None:
        self.assertIn("node.parentElement?.innerText", PROFILE_SCRIPT)

    def test_search_script_ignores_related_query_cards_without_note_link(self) -> None:
        self.assertIn('a[href*="/search_result/"]', SEARCH_SCRIPT)
        self.assertIn(".query-note-item .item-text", SEARCH_SCRIPT)
        self.assertIn(".play-icon", SEARCH_SCRIPT)

    def test_public_search_snapshot_drops_transient_navigation_context(self) -> None:
        public = _public_search_snapshot({
            "search_snapshot_id": "search-1",
            "keyword": "合成关键词",
            "results": [{
                "search_snapshot_id": "search-1",
                "note_id": "note-1",
                "rank": 1,
                "title": "合成标题",
                "author": "合成作者",
                "cover_url": "https://sns-webpic-qc.xhscdn.com/a.webp?token=cover-secret",
                "navigation_url": "https://www.xiaohongshu.com/search_result/note-1?xsec_token=secret",
            }],
        })
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("navigation_url", serialized)
        self.assertNotIn("secret", serialized)
        self.assertEqual(public["results"][0]["canonical_url"], "https://www.xiaohongshu.com/explore/note-1")


if __name__ == "__main__":
    unittest.main()
