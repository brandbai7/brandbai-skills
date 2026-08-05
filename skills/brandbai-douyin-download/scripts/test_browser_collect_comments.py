#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from browser_collect_comments import (  # noqa: E402
    ActionBudget,
    PROVIDER,
    REPLY_EXPANDER_RE,
    ResponseCapture,
    clean_page_title,
    is_page_crash_error,
    is_transient_navigation_error,
    normalize_dom_comment,
    normalize_video_urls,
    reconcile_dom_fallback_duplicates,
    reply_floor_snapshot,
    wait_for_comment_surface,
)
from collector_core import CommentStore  # noqa: E402


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_browser_skill_test_artifacts"
    root.mkdir(exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


class BrowserCollectorTests(unittest.TestCase):
    def test_resume_waits_for_current_page_surface_not_historical_store_rows(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000001"
            store.ensure_video(aweme_id)
            store.upsert_comment(
                {"cid": "historical-c1", "text": "历史断点", "user": {"sec_uid": "u1"}},
                aweme_id,
            )
            capture = SimpleNamespace(
                comment_responses=0,
                current_aweme_id=aweme_id,
                store=store,
            )

            class FakePage:
                def __init__(self):
                    self.waits = 0

                def wait_for_timeout(self, _milliseconds):
                    self.waits += 1

            page = FakePage()
            with patch(
                "browser_collect_comments.comment_surface_state",
                side_effect=[
                    {"item_count": 0, "list_count": 0, "login_gate": False},
                    {"item_count": 1, "list_count": 1, "login_gate": False},
                ],
            ), patch("browser_collect_comments.open_comment_panel", return_value=False):
                state = wait_for_comment_surface(page, capture, ActionBudget(10), 5)
            self.assertEqual(state["item_count"], 1)
            self.assertEqual(page.waits, 1)
            store.close()

    def test_page_title_cleanup_keeps_real_caption(self):
        self.assertEqual(
            clean_page_title("长发？拆了 #生活碎片记录 - 抖音"),
            "长发？拆了 #生活碎片记录",
        )
        self.assertEqual(
            clean_page_title(
                "用了三十年去克服跑调 #痞幼才艺室 - 小痞酱于20260731发布在抖音，已经收获了17626个喜欢"
            ),
            "用了三十年去克服跑调 #痞幼才艺室",
        )
        self.assertEqual(clean_page_title("抖音-记录美好生活"), "")

    def test_normalize_video_urls_deduplicates(self):
        values = normalize_video_urls(
            [
                "https://www.douyin.com/video/7000000000000000001",
                "https://www.douyin.com/user/x?modal_id=7000000000000000001",
                "https://www.douyin.com/note/7000000000000000003",
                "7000000000000000002",
                "not-a-video",
            ]
        )
        self.assertEqual(
            values,
            [
                "https://www.douyin.com/video/7000000000000000001",
                "https://www.douyin.com/note/7000000000000000003",
                "https://www.douyin.com/video/7000000000000000002",
            ],
        )

    def test_browser_failures_are_classified_for_fresh_child_page_retry(self):
        self.assertTrue(
            is_page_crash_error(RuntimeError("TargetClosedError: Page.wait_for_timeout: Page crashed"))
        )
        self.assertTrue(
            is_transient_navigation_error(
                RuntimeError("Execution context was destroyed, most likely because of a navigation")
            )
        )
        self.assertFalse(is_page_crash_error(RuntimeError("selector not found")))

    def test_reply_expander_does_not_match_generic_more_controls(self):
        self.assertIsNotNone(REPLY_EXPANDER_RE.search("展开 7 条回复"))
        self.assertIsNotNone(REPLY_EXPANDER_RE.search("查看更多回复"))
        self.assertIsNotNone(REPLY_EXPANDER_RE.search("回复(7)"))
        self.assertIsNone(REPLY_EXPANDER_RE.search("查看更多"))

    def test_observed_comment_and_reply_payloads_use_shared_evidence_store(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            capture = ResponseCapture(store)
            aweme_id = "7000000000000000001"
            capture.set_current_video(aweme_id)
            top_url = (
                "https://www.douyin.com/aweme/v1/web/comment/list/"
                f"?aweme_id={aweme_id}&cursor=0&count=20"
            )
            inserted = capture.process_payload(
                top_url,
                {
                    "comments": [
                        {
                            "cid": "c1",
                            "text": "求链接，适合油皮吗？",
                            "reply_comment_total": 1,
                            "user": {"uid": "u1", "nickname": "用户甲"},
                        }
                    ],
                    "cursor": 20,
                    "has_more": 1,
                },
            )
            self.assertEqual(inserted, 1)
            self.assertFalse(store.get_progress("comments", aweme_id)["done"])

            reply_url = (
                "https://www.douyin.com/aweme/v1/web/comment/list/reply/"
                f"?item_id={aweme_id}&comment_id=c1&cursor=0&count=20"
            )
            inserted = capture.process_payload(
                reply_url,
                {
                    "comments": [
                        {
                            "cid": "r1",
                            "text": "我也是油皮，蹲一个",
                            "user": {"uid": "u2", "nickname": "用户乙"},
                        }
                    ],
                    "cursor": 0,
                    "has_more": 0,
                },
            )
            self.assertEqual(inserted, 1)
            self.assertTrue(store.get_progress("replies", f"{aweme_id}:c1")["done"])
            rows = list(store.conn.execute("SELECT * FROM comments ORDER BY reply_level"))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source_role"], "viewer_comment")
            self.assertEqual(rows[1]["source_role"], "viewer_reply")
            self.assertTrue(rows[0]["author_pseudonym"].startswith("user_"))
            self.assertEqual(rows[0]["author_unique_id"], "")
            store.close()

    def test_terminal_progress_is_not_downgraded_during_resume(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            capture = ResponseCapture(store)
            aweme_id = "7000000000000000001"
            capture.set_current_video(aweme_id)
            url = (
                "https://www.douyin.com/aweme/v1/web/comment/list/"
                f"?aweme_id={aweme_id}&cursor=0&count=20"
            )
            capture.process_payload(
                url,
                {"comments": [], "cursor": 60, "has_more": 0},
            )
            self.assertTrue(store.get_progress("comments", aweme_id)["done"])

            capture.process_payload(
                url,
                {"comments": [], "cursor": 20, "has_more": 1},
            )
            progress = store.get_progress("comments", aweme_id)
            self.assertTrue(progress["done"])
            self.assertEqual(progress["cursor"], "60")
            store.close()

    def test_dry_run_has_no_browser_or_signature_side_effect(self):
        with workspace_temp() as temp:
            command = [
                sys.executable,
                str(SCRIPT_DIR / "browser_collect_comments.py"),
                "--creator",
                "https://www.douyin.com/user/MS4wLjABTEST",
                "--videos",
                "30",
                "--include-replies",
                "--profile-dir",
                str(temp / "profile"),
                "--out",
                str(temp / "out"),
                "--dry-run",
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["provider"], PROVIDER)
            self.assertEqual(plan["creator_videos"], 30)
            self.assertTrue(plan["include_replies"])
            self.assertEqual(plan["reply_batch_size"], 5)
            self.assertEqual(plan["reply_sweeps"], 3)
            self.assertFalse(plan["cookies_exported"])
            self.assertFalse(plan["signature_generation"])
            self.assertFalse((temp / "profile").exists())
            self.assertFalse((temp / "out").exists())

    def test_visible_dom_comment_normalizes_without_volatile_class_names(self):
        item = normalize_dom_comment(
            {
                "nickname": "何润心",
                "user_url": "https://www.douyin.com/user/MS4wLjABDOMUSER",
                "text": "",
                "lines": [
                    "何润心",
                    "...",
                    "请问这个脚本在哪里领取？",
                    "1年前·湖北",
                    "1",
                    "分享",
                    "回复",
                    "展开7条回复",
                ],
            },
            "7000000000000000001",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["text"], "请问这个脚本在哪里领取？")
        self.assertEqual(item["create_time"], "1年前")
        self.assertEqual(item["ip_label"], "湖北")
        self.assertEqual(item["reply_comment_total"], 7)
        self.assertEqual(item["user"]["sec_uid"], "MS4wLjABDOMUSER")

    def test_network_row_replaces_matching_generated_dom_fallback(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000001"
            store.ensure_video(aweme_id)
            dom_item = normalize_dom_comment(
                {
                    "nickname": "用户甲",
                    "user_url": "https://www.douyin.com/user/sec-user-1",
                    "text": "同一条评论",
                    "lines": ["用户甲", "同一条评论", "3周前·广东"],
                },
                aweme_id,
            )
            store.upsert_comment(dom_item, aweme_id)
            capture = ResponseCapture(store)
            capture.set_current_video(aweme_id)
            capture.process_payload(
                "https://www.douyin.com/aweme/v1/web/comment/list/"
                f"?aweme_id={aweme_id}&cursor=0&count=20",
                {
                    "comments": [
                        {
                            "cid": "platform-c1",
                            "text": "同一条评论",
                            "create_time": 1700000000,
                            "user": {"sec_uid": "sec-user-1", "nickname": "用户甲"},
                        }
                    ],
                    "has_more": 0,
                },
            )
            rows = list(store.conn.execute("SELECT comment_id FROM comments"))
            self.assertEqual([row["comment_id"] for row in rows], ["platform-c1"])
            self.assertEqual(capture.dom_duplicates_replaced, 1)
            store.close()

    def test_note_source_url_is_preserved_in_video_and_comment_exports(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000003"
            note_url = f"https://www.douyin.com/note/{aweme_id}"
            store.upsert_video({"aweme_id": aweme_id, "source_url": note_url})
            store.upsert_comment(
                {
                    "cid": "note-c1",
                    "text": "图文评论",
                    "user": {"sec_uid": "note-user"},
                },
                aweme_id,
            )
            video = store.get_video(aweme_id)
            comment = store.conn.execute(
                "SELECT source_url FROM comments WHERE comment_id='note-c1'"
            ).fetchone()
            self.assertEqual(video["source_url"], note_url)
            self.assertEqual(comment["source_url"], note_url)
            store.close()

    def test_reconcile_removes_dom_row_when_platform_row_arrived_first(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000001"
            store.ensure_video(aweme_id)
            platform = {
                "cid": "platform-c1",
                "text": "同一条评论",
                "user": {"sec_uid": "sec-user-1", "nickname": "用户甲"},
            }
            dom = normalize_dom_comment(
                {
                    "nickname": "用户甲",
                    "user_url": "https://www.douyin.com/user/sec-user-1",
                    "text": "同一条评论",
                    "lines": ["用户甲", "同一条评论", "3周前·广东"],
                },
                aweme_id,
            )
            store.upsert_comment(platform, aweme_id)
            store.upsert_comment(dom, aweme_id)
            self.assertEqual(store.count_top_level_comments(aweme_id), 2)
            self.assertEqual(reconcile_dom_fallback_duplicates(store, aweme_id), 1)
            self.assertEqual(store.count_top_level_comments(aweme_id), 1)
            store.close()

    def test_reconcile_removes_unique_emoji_only_dom_duplicate(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000001"
            store.ensure_video(aweme_id)
            store.upsert_comment(
                {
                    "cid": "platform-c1",
                    "text": "真的是小说大女主[色]",
                    "reply_comment_total": 6,
                    "user": {"sec_uid": "platform-user"},
                },
                aweme_id,
            )
            store.upsert_comment(
                {
                    "text": "真的是小说大女主",
                    "reply_comment_total": 6,
                    "user": {"nickname": "页面昵称"},
                },
                aweme_id,
            )
            self.assertEqual(store.count_top_level_comments(aweme_id), 2)
            self.assertEqual(reconcile_dom_fallback_duplicates(store, aweme_id), 1)
            rows = list(store.conn.execute("SELECT comment_id FROM comments"))
            self.assertEqual([row["comment_id"] for row in rows], ["platform-c1"])
            store.close()

    def test_reply_floor_snapshot_tracks_terminal_and_pending_roots(self):
        with workspace_temp() as temp:
            store = CommentStore(temp / "comments.sqlite3", "hash")
            aweme_id = "7000000000000000001"
            store.ensure_video(aweme_id)
            for comment_id in ("c1", "c2"):
                store.upsert_comment(
                    {
                        "cid": comment_id,
                        "text": comment_id,
                        "reply_comment_total": 2,
                        "user": {"sec_uid": comment_id},
                    },
                    aweme_id,
                )
            store.upsert_comment(
                {"cid": "r1", "text": "回复", "user": {"sec_uid": "r1"}},
                aweme_id,
                reply_level=1,
                root_comment_id="c1",
            )
            store.set_progress(
                "replies",
                f"{aweme_id}:c1",
                0,
                True,
                {"done_reason": "exhausted"},
            )
            snapshot = reply_floor_snapshot(store, aweme_id)
            self.assertEqual(snapshot["total_floors"], 2)
            self.assertEqual(snapshot["terminal_floors"], 1)
            self.assertEqual(snapshot["pending_floors"], 1)
            self.assertEqual(snapshot["pending_ids"], ["c2"])
            self.assertEqual(snapshot["saved_replies"], 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
