from __future__ import annotations

import unittest

from browser_collect_xiaohongshu import _normalize_comment_rows, normalize_assets
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


if __name__ == "__main__":
    unittest.main()
