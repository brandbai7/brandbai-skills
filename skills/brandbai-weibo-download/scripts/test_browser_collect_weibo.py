from __future__ import annotations

import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from browser_collect_weibo import (
    COMMENT_SCROLL_STEP_SCRIPT,
    COMMENT_SCROLL_STATE_SCRIPT,
    COMMENT_SCROLL_TOP_SCRIPT,
    COMMENT_SORT_ACTIVATE_SCRIPT,
    COMMENT_SORT_DISCOVERY_SCRIPT,
    COMMENTS_SCRIPT,
    POST_SCRIPT,
    PROFILE_SCRIPT,
    REPOSTS_SCRIPT,
    SEARCH_SCRIPT,
    _public_profile_selection,
    _profile_pinned_ids_from_payload,
    _public_search_snapshot,
    _normalize_comment_rows,
    _normalize_repost_rows,
    _new_unique_rows,
    _annotate_comment_sort,
    _collect_comments,
    _merge_comment_record,
    _next_bottom_stability,
    _prepare_comment_sort_modes,
    _write_jsonl,
    normalize_assets,
)
from collector_core import CollectionError


class BrowserCollectorTests(unittest.TestCase):
    def test_jsonl_checkpoint_retries_transient_windows_file_lock(self) -> None:
        real_replace = os.replace
        attempts = 0

        def flaky_replace(source, target):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError("synthetic file lock")
            return real_replace(source, target)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "comments.jsonl"
            with mock.patch("browser_collect_weibo.os.replace", side_effect=flaky_replace):
                _write_jsonl(path, [{"comment_id": "root-1"}])
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(attempts, 2)
        self.assertEqual(saved["comment_id"], "root-1")

    def test_comment_collector_keeps_scrolling_when_ids_pause_before_bottom(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.step = 0

            def evaluate(self, expression, *args):
                if expression == COMMENT_SORT_DISCOVERY_SCRIPT:
                    return []
                if expression == COMMENTS_SCRIPT:
                    rows = [{
                        "platform_comment_id": "root-1", "author_platform_id": "user-1",
                        "author_name": "甲", "content": "合成评论一", "level": 1,
                    }]
                    if self.step >= 3:
                        rows.append({
                            "platform_comment_id": "root-2", "author_platform_id": "user-2",
                            "author_name": "乙", "content": "合成评论二", "level": 1,
                        })
                    return {"rows": rows, "declared": "", "exhausted": False}
                if expression == COMMENT_SCROLL_STATE_SCRIPT:
                    return {
                        "top": min(self.step * 700, 4200), "height": 5000, "viewport": 800,
                        "at_bottom": self.step >= 6,
                    }
                if expression == COMMENT_SCROLL_STEP_SCRIPT:
                    self.step += 1
                    return {}
                if expression == COMMENT_SCROLL_TOP_SCRIPT:
                    self.step = 0
                    return True
                raise AssertionError(f"unexpected evaluate expression: {expression[:40]}")

            def wait_for_timeout(self, _milliseconds: int) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp:
            result = _collect_comments(
                FakePage(), "post-1", Path(temp) / "comments.jsonl",
                limit=0, max_scroll_actions=20, include_replies=False,
                retain_author_display=False, resume=False,
            )
        self.assertEqual(result["saved_comments"], 2)
        self.assertGreaterEqual(result["scroll_actions"], 8)
        self.assertEqual(result["state"], "complete_visible_comments_exhausted")
        self.assertEqual(
            result["sort_runs"][0]["termination_reason"],
            "document_bottom_and_comment_ids_stable",
        )

    def test_comment_checkpoint_survives_unexpected_page_failure(self) -> None:
        class FailingPage:
            def __init__(self) -> None:
                self.step = 0

            def evaluate(self, expression, *args):
                if expression == COMMENT_SORT_DISCOVERY_SCRIPT:
                    return []
                if expression == COMMENTS_SCRIPT:
                    if self.step:
                        raise RuntimeError("synthetic page closed")
                    return {"rows": [{
                        "platform_comment_id": "root-1", "author_platform_id": "user-1",
                        "author_name": "甲", "content": "合成断点评论", "level": 1,
                    }]}
                if expression == COMMENT_SCROLL_STATE_SCRIPT:
                    return {"top": 0, "height": 5000, "viewport": 800, "at_bottom": False}
                if expression == COMMENT_SCROLL_STEP_SCRIPT:
                    self.step += 1
                    return {}
                if expression == COMMENT_SCROLL_TOP_SCRIPT:
                    self.step = 0
                    return True
                raise AssertionError("unexpected expression")

            def wait_for_timeout(self, _milliseconds: int) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "comments.jsonl"
            with self.assertRaisesRegex(RuntimeError, "synthetic page closed"):
                _collect_comments(
                    FailingPage(), "post-1", path, limit=0, max_scroll_actions=20,
                    include_replies=False, retain_author_display=False, resume=False,
                )
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["comment_id"] for row in rows], ["root-1"])

    def test_comment_sort_probe_waits_for_lazy_toolbar(self) -> None:
        class LazyToolbarPage:
            def __init__(self) -> None:
                self.step = 0

            def evaluate(self, expression, *args):
                if expression == COMMENT_SORT_DISCOVERY_SCRIPT:
                    return ["按热度", "按时间"] if self.step >= 3 else []
                if expression == COMMENT_SCROLL_STATE_SCRIPT:
                    return {"top": self.step * 700, "height": 5000, "viewport": 800, "at_bottom": False}
                if expression == COMMENT_SCROLL_STEP_SCRIPT:
                    self.step += 1
                    return {}
                raise AssertionError("unexpected expression")

            def wait_for_timeout(self, _milliseconds: int) -> None:
                return None

        modes, actions = _prepare_comment_sort_modes(LazyToolbarPage(), 8)
        self.assertEqual(modes, ["按热度", "按时间"])
        self.assertEqual(actions, 3)

    def test_profile_network_payload_preserves_only_platform_pinned_ids(self) -> None:
        payload = {"data": {"list": [
            {"mblogid": "Pinned123", "isTop": 1},
            {"mblogid": "Normal456"},
            {"mblogid": "Pinned789", "isTop": "1"},
            {"idstr": "numeric-only", "isTop": 1},
        ]}}
        self.assertEqual(
            _profile_pinned_ids_from_payload(payload),
            {"Pinned123", "Pinned789"},
        )

    def test_batch_dedupe_applies_limit_to_unique_records(self) -> None:
        rows = [
            {"comment_id": "a"}, {"comment_id": "a"}, {"comment_id": "b"},
            {"comment_id": "c"}, {"comment_id": "c"},
        ]
        self.assertEqual(
            [row["comment_id"] for row in _new_unique_rows(rows, "comment_id", set(), 2)],
            ["a", "b"],
        )
        self.assertEqual(
            [row["comment_id"] for row in _new_unique_rows(rows, "comment_id", {"a"}, 0)],
            ["b", "c"],
        )

    def test_live_weibo_contract_uses_scoped_body_and_comment_layers(self) -> None:
        self.assertNotIn('[class*="content"] [class*="text"]', POST_SCRIPT)
        self.assertIn(".item1", COMMENTS_SCRIPT)
        self.assertIn(":scope > .item1in", COMMENTS_SCRIPT)
        self.assertIn(":scope > .list2 > .item2", COMMENTS_SCRIPT)
        self.assertIn("replace(/^@/, '').replace(/\\s*的个人主页$/", PROFILE_SCRIPT)
        self.assertIn("bestHeaderRoot", PROFILE_SCRIPT)
        self.assertNotIn("lines.find((line) => /(?:认证|演员", PROFILE_SCRIPT)
        self.assertIn("[class*=\"_retweet_\"][class*=\"_wrap_\"]", REPOSTS_SCRIPT)
        self.assertIn("main.querySelectorAll('.item1')", REPOSTS_SCRIPT)
        self.assertNotIn("map((link) =>", REPOSTS_SCRIPT)
        self.assertIn("login_limited", COMMENTS_SCRIPT)
        self.assertIn("按热度", COMMENT_SORT_DISCOVERY_SCRIPT)
        self.assertIn("按时间", COMMENT_SORT_DISCOVERY_SCRIPT)
        self.assertIn("li,span,div", COMMENT_SORT_DISCOVERY_SCRIPT)
        self.assertIn("selected_before", COMMENT_SORT_ACTIVATE_SCRIPT)
        self.assertIn("at_bottom", COMMENT_SCROLL_STEP_SCRIPT)

    def test_comment_no_growth_only_counts_at_real_bottom(self) -> None:
        stability = _next_bottom_stability(
            0, at_bottom=False, ids_grew=False, height_changed=False,
        )
        self.assertEqual(stability, 0)
        for expected in [1, 2, 3]:
            stability = _next_bottom_stability(
                stability, at_bottom=True, ids_grew=False, height_changed=False,
            )
            self.assertEqual(stability, expected)
        self.assertEqual(_next_bottom_stability(
            stability, at_bottom=True, ids_grew=False, height_changed=True,
        ), 0)

    def test_comment_sort_union_preserves_both_ranks_and_reply_declaration(self) -> None:
        heat = _annotate_comment_sort([{
            "comment_id": "root-1", "root_comment_id": "root-1", "level": 1,
            "declared_reply_count": 2, "collected_at": "first",
        }], "按热度", {})[0]
        time = _annotate_comment_sort([{
            "comment_id": "root-1", "root_comment_id": "root-1", "level": 1,
            "declared_reply_count": 3, "collected_at": "second",
        }], "按时间", {})[0]
        merged = _merge_comment_record(heat, time)
        self.assertEqual(merged["observed_sort_modes"], ["按热度", "按时间"])
        self.assertEqual(merged["sort_rank_by_mode"], {"按热度": 1, "按时间": 1})
        self.assertEqual(merged["declared_reply_count"], 3)
        self.assertEqual(merged["collected_at"], "first")
        self.assertEqual(merged["last_observed_at"], "second")

    def test_search_snapshot_tolerates_missing_document_body(self) -> None:
        self.assertIn("document.body?.innerText", SEARCH_SCRIPT)
        self.assertIn("document.documentElement?.innerText", SEARCH_SCRIPT)
        self.assertNotIn("document.body.innerText", SEARCH_SCRIPT)

    def test_asset_modes_are_normalized(self) -> None:
        self.assertEqual(normalize_assets("images,cover,images"), ["images", "cover"])
        self.assertEqual(normalize_assets("none"), [])
        with self.assertRaises(CollectionError):
            normalize_assets("none,video")

    def test_comments_default_to_pseudonyms_and_count_visible_replies(self) -> None:
        rows = _normalize_comment_rows([
            {
                "platform_comment_id": "root-1", "author_platform_id": "user-1", "author_name": "甲",
                "content": "合成一级评论", "level": 1, "declared_reply_count": 2,
            },
            {
                "platform_comment_id": "reply-1", "author_platform_id": "user-2", "author_name": "乙",
                "content": "合成回复", "level": 2, "root_platform_id": "root-1",
            },
        ], "post-1", retain_author_display=False, include_replies=True)
        self.assertEqual(rows[0]["saved_reply_count"], 1)
        self.assertEqual(rows[0]["reply_expansion_status"], "partial_reply_not_expanded")
        self.assertEqual(rows[0]["author_display"], "")
        self.assertTrue(rows[0]["author_id"].startswith("wb_user_"))
        self.assertEqual(rows[1]["parent_comment_id"], "root-1")

    def test_derived_comment_id_does_not_change_with_relative_time(self) -> None:
        base = {
            "author_platform_id": "user-1", "author_name": "甲", "content": "合成评论",
            "level": 1, "declared_reply_count": 0,
        }
        first = _normalize_comment_rows([{**base, "time_text": "2分钟前"}], "post-1", False, False)[0]
        later = _normalize_comment_rows([{**base, "time_text": "1小时前"}], "post-1", False, False)[0]
        self.assertEqual(first["comment_id"], later["comment_id"])
        self.assertNotEqual(first["time_text"], later["time_text"])

    def test_repost_display_name_is_opt_in(self) -> None:
        hidden = _normalize_repost_rows([{
            "author_platform_id": "user-1", "author_name": "合成作者", "content": "合成转发",
        }], "post-1", retain_author_display=False)
        shown = _normalize_repost_rows([{
            "author_platform_id": "user-1", "author_name": "合成作者", "content": "合成转发",
        }], "post-1", retain_author_display=True)
        self.assertEqual(hidden[0]["author_display"], "")
        self.assertEqual(shown[0]["author_display"], "合成作者")

    def test_public_selection_drops_transient_navigation_and_media_tokens(self) -> None:
        profile = _public_profile_selection({
            "profile_id": "10001", "selected": [{
                "post_id": "Abcde123", "author_uid": "10001", "rank": 1,
                "cover_url": "https://wx1.sinaimg.cn/large/a.jpg?token=secret",
                "navigation_url": "https://weibo.com/10001/Abcde123?refer_flag=secret",
            }],
        })
        search = _public_search_snapshot({
            "search_snapshot_id": "search-1", "results": [{
                "post_id": "Abcde123", "author_uid": "10001", "rank": 1,
                "cover_url": "https://wx1.sinaimg.cn/large/a.jpg?token=secret",
                "navigation_url": "https://weibo.com/10001/Abcde123?refer_flag=secret",
            }],
        })
        serialized = json.dumps({"profile": profile, "search": search}, ensure_ascii=False)
        self.assertNotIn("navigation_url", serialized)
        self.assertNotIn("secret", serialized)
        self.assertEqual(profile["selected"][0]["canonical_url"], "https://weibo.com/10001/Abcde123")


if __name__ == "__main__":
    unittest.main()
