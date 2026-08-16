from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from browser_collect_xiaohongshu import (
    NOTE_SCRIPT,
    PROFILE_SCRIPT,
    SEARCH_SCRIPT,
    _normalize_comment_rows,
    _public_profile_selection,
    _public_search_snapshot,
    _collect_visible_list_records,
    _media_dimensions,
    _split_date_region_text,
    _wait_for_login_or_ready,
    normalize_assets,
)
from collector_core import CollectionError


class BrowserCollectorContractTests(unittest.TestCase):
    def test_blob_video_recovers_public_mp4_from_inline_page_data(self) -> None:
        self.assertIn("document.scripts", NOTE_SCRIPT)
        self.assertIn("scriptVideoCandidates", NOTE_SCRIPT)
        self.assertIn("host.endsWith('.xhscdn.com')", NOTE_SCRIPT)
        self.assertIn("parsed.pathname", NOTE_SCRIPT)
        self.assertIn("recoveredCandidates", NOTE_SCRIPT)
        self.assertIn("logicalVideo.candidates", NOTE_SCRIPT)

    def test_edited_date_is_not_misclassified_as_a_region(self) -> None:
        self.assertEqual(_split_date_region_text("编辑于 04-20"), ("编辑于 04-20", ""))
        self.assertEqual(_split_date_region_text("编辑于 04-20 上海"), ("编辑于 04-20", "上海"))
        self.assertEqual(_split_date_region_text("01-04"), ("01-04", ""))
        self.assertEqual(_split_date_region_text("01-04 IP属地：广东"), ("01-04", "广东"))

    def test_final_mp4_dimensions_override_page_labels(self) -> None:
        size = 92
        body = (
            size.to_bytes(4, "big")
            + b"tkhd"
            + bytes(size - 16)
            + (720 << 16).to_bytes(4, "big")
            + (1280 << 16).to_bytes(4, "big")
        )
        self.assertEqual(_media_dimensions(body, "video"), {"width": 720, "height": 1280})

    def test_login_wait_returns_as_soon_as_target_is_visible(self) -> None:
        class FakeLocator:
            def __init__(self, page: "FakePage", role: bool = False) -> None:
                self.page = page
                self.role = role

            def count(self) -> int:
                if self.role:
                    return 0
                return int(self.page.waited_ms >= 2_000)

        class FakePage:
            def __init__(self) -> None:
                self.waited_ms = 0
                self.reloads = 0

            def locator(self, _selector: str) -> FakeLocator:
                return FakeLocator(self)

            def get_by_role(self, *_args: object, **_kwargs: object) -> FakeLocator:
                return FakeLocator(self, role=True)

            def wait_for_timeout(self, milliseconds: int) -> None:
                self.waited_ms += milliseconds

            def reload(self, **_kwargs: object) -> None:
                self.reloads += 1

        page = FakePage()
        self.assertTrue(_wait_for_login_or_ready(page, ".note-container", 10))
        self.assertEqual(page.waited_ms, 2_000)
        self.assertEqual(page.reloads, 0)

    def test_batch_list_records_do_not_require_detail_navigation(self) -> None:
        out = Path(__file__).resolve().parent / ".xhs_batch_list_test_runtime"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir()
        try:
            states = _collect_visible_list_records(
                None,
                out,
                [{
                    "note_id": "0123456789abcdef01234567",
                    "rank": 1,
                    "title": "合成列表卡片",
                    "author": "合成作者",
                    "note_type": "image",
                    "like_count_text": "12",
                    "cover_url": "",
                    "search_snapshot_id": "search-1",
                    "keyword": "合成关键词",
                }],
                source_kind="search",
                assets=[],
                resume=False,
                max_asset_bytes=1024,
            )
            self.assertEqual(states["0123456789abcdef01234567"], "complete_visible_list_card")
            row = json.loads((out / "data" / "notes.jsonl").read_text(encoding="utf-8").strip())
            self.assertFalse(row["detail_page_opened"])
            self.assertEqual(row["field_scope"], "visible_list_card_only")
            self.assertEqual(row["body"], "")
        finally:
            if out.exists():
                shutil.rmtree(out)

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
