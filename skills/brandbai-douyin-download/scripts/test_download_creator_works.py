import unittest
from pathlib import Path
from types import SimpleNamespace

from download_creator_works import (
    collect_seeded_works,
    collect_visible_works,
    discovery_scroll_budget,
    download_from_candidates,
    final_works_status,
    signature_kind,
    normalize_work,
    page_type,
    parse_assets,
    pick_posts,
    sanitize_name,
    search_keyword,
    search_dom_work_ids,
    select_visible,
    select_pinned_and_recent,
    url_list,
)


def fake_work(aweme_id: str, create_time: int, is_top: bool = False, images: bool = False):
    item = {
        "aweme_id": aweme_id,
        "create_time": create_time,
        "is_top": is_top,
        "desc": f"work {aweme_id}",
        "author": {"nickname": "达人"},
        "statistics": {
            "digg_count": 10,
            "share_count": 2,
            "comment_count": 3,
            "collect_count": 4,
            "recommend_count": 5,
        },
        "video": {
            "play_addr": {"url_list": [f"https://media.example/{aweme_id}.mp4"]},
            "cover": {"url_list": [f"https://image.example/{aweme_id}.jpg"]},
        },
        "music": {"play_url": {"url_list": [f"https://music.example/{aweme_id}.mp3"]}},
    }
    if images:
        item["images"] = [
            {"display_image": {"url_list": [f"https://image.example/{aweme_id}_1.webp"]}}
        ]
    return item


class DownloadCreatorWorksTests(unittest.TestCase):
    def test_visible_works_can_use_an_existing_browser_context(self):
        item = fake_work("10000000009", 900)

        class FakeResponse:
            url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
            status = 200

            @staticmethod
            def json():
                return {"aweme_list": [item]}

        class FakeMouse:
            @staticmethod
            def wheel(_x, _y):
                return None

        class FakePage:
            def __init__(self):
                self.mouse = FakeMouse()
                self.handlers = {}

            def set_default_timeout(self, _timeout):
                return None

            def on(self, event, handler):
                self.handlers[event] = handler

            def remove_listener(self, event, _handler):
                self.handlers.pop(event, None)

            def goto(self, *_args, **_kwargs):
                self.handlers["response"](FakeResponse())

            def wait_for_timeout(self, _timeout):
                return None

        page = FakePage()
        context = SimpleNamespace(pages=[page])
        selected, responses, visible = collect_visible_works(
            context,
            SimpleNamespace(
                creator="https://www.douyin.com/user/test",
                login_wait=0,
                scrolls=1,
                recent=1,
            ),
        )
        self.assertEqual([row["aweme_id"] for row in selected], ["10000000009"])
        self.assertEqual(responses, 1)
        self.assertEqual(visible, 1)
        self.assertEqual(page.handlers, {})

    def test_creator_page_reloads_after_login_wait_when_first_page_is_short(self):
        first_batch = [fake_work(str(10000000000 + index), index) for index in range(1, 6)]
        refreshed_batch = [fake_work(str(20000000000 + index), index) for index in range(1, 19)]

        class FakeResponse:
            url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
            status = 200

            def __init__(self, items):
                self.items = items

            def json(self):
                return {"aweme_list": self.items}

        class FakeMouse:
            @staticmethod
            def wheel(_x, _y):
                return None

        class FakePage:
            def __init__(self):
                self.mouse = FakeMouse()
                self.handlers = {}
                self.reloads = 0

            def set_default_timeout(self, _timeout):
                return None

            def on(self, event, handler):
                self.handlers[event] = handler

            def remove_listener(self, event, _handler):
                self.handlers.pop(event, None)

            def goto(self, *_args, **_kwargs):
                self.handlers["response"](FakeResponse(first_batch))

            def reload(self, *_args, **_kwargs):
                self.reloads += 1
                self.handlers["response"](FakeResponse(refreshed_batch))

            def wait_for_timeout(self, _timeout):
                return None

        page = FakePage()
        selected, responses, visible = collect_visible_works(
            SimpleNamespace(pages=[page]),
            SimpleNamespace(
                creator="https://www.douyin.com/user/test",
                login_wait=0,
                scrolls=5,
                recent=12,
            ),
        )
        self.assertEqual(page.reloads, 1)
        self.assertEqual(len(selected), 12)
        self.assertEqual(responses, 2)
        self.assertEqual(visible, 23)

    def test_discovery_budget_grows_with_recent_n(self):
        self.assertEqual(discovery_scroll_budget(5, 5), 10)
        self.assertEqual(discovery_scroll_budget(30, 5), 60)
        self.assertEqual(discovery_scroll_budget(200, 5), 120)

    def test_search_page_and_keyword_are_detected(self):
        url = "https://www.douyin.com/search/%E6%B5%8B%E8%AF%95?type=general"
        self.assertEqual(page_type(url), "search")
        self.assertEqual(search_keyword(url), "测试")

    def test_nested_search_payload_finds_aweme_info(self):
        item = fake_work("10000000008", 80)
        self.assertEqual(
            [row["aweme_id"] for row in pick_posts({"data": [{"aweme_info": item}]})],
            ["10000000008"],
        )

    def test_search_dom_fallback_deduplicates_visible_work_ids(self):
        class FakeLocator:
            @staticmethod
            def evaluate_all(_script):
                return ["7629304613908529329", "", "7629304613908529329", "bad"]

        class FakePage:
            @staticmethod
            def locator(selector):
                self = selector
                return FakeLocator()

        self.assertEqual(search_dom_work_ids(FakePage()), ["7629304613908529329"])

    def test_manual_visible_selection_reports_missing_ids(self):
        items = [fake_work("10000000001", 10), fake_work("10000000002", 20)]
        selected, missing = select_visible(
            items,
            selected_ids=["10000000002", "99999999999"],
            reason="页面选择",
        )
        self.assertEqual([row["aweme_id"] for row in selected], ["10000000002"])
        self.assertEqual(missing, ["99999999999"])

    def test_visible_selection_preserves_page_order(self):
        items = [
            fake_work("10000000001", 10),
            fake_work("10000000002", 30),
            fake_work("10000000003", 20),
        ]
        selected, missing = select_visible(items, limit=2, reason="搜索结果")
        self.assertEqual([row["aweme_id"] for row in selected], ["10000000001", "10000000002"])
        self.assertEqual(missing, [])

    def test_explicit_metadata_only_still_enriches_missing_metadata(self):
        item = fake_work("10000000007", 70)

        class FakeResponse:
            url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
            status = 200

            @staticmethod
            def json():
                return {"aweme_detail": item}

        class FakePage:
            def __init__(self):
                self.handlers = {}
                self.visited = []

            def set_default_timeout(self, _timeout):
                return None

            def on(self, event, handler):
                self.handlers[event] = handler

            def remove_listener(self, event, _handler):
                self.handlers.pop(event, None)

            def goto(self, url, **_kwargs):
                self.visited.append(url)
                self.handlers["response"](FakeResponse())

            def wait_for_timeout(self, _timeout):
                return None

        page = FakePage()
        args = SimpleNamespace(
            selection_file="",
            video=["https://www.douyin.com/video/10000000007"],
            assets="none",
            login_wait=0,
        )
        selected, responses, visible = collect_seeded_works(SimpleNamespace(pages=[page]), args)
        self.assertEqual(page.visited, ["https://www.douyin.com/video/10000000007"])
        self.assertEqual(selected[0]["title"], "work 10000000007")
        self.assertTrue(selected[0]["_metadata_observed"])
        self.assertEqual(responses, 1)
        self.assertEqual(visible, 1)

    def test_asset_selection_supports_metadata_only(self):
        self.assertEqual(parse_assets("none"), set())
        self.assertEqual(parse_assets("video,cover,text"), {"primary", "cover", "caption"})

    def test_selection_shortfall_is_never_marked_complete(self):
        self.assertEqual(final_works_status(False, 5, 30), "partial_selection_shortfall")
        self.assertEqual(
            final_works_status(True, 5, 30),
            "partial_selection_and_download_errors",
        )
        self.assertEqual(final_works_status(False, 30, 30), "complete")

    def test_sanitize_windows_name(self):
        self.assertEqual(sanitize_name('  A:B/C*D?  '), "A_B_C_D")

    def test_url_list_deduplicates(self):
        self.assertEqual(
            url_list({"url_list": ["https://a", "https://a", "https://b"]}),
            ["https://a", "https://b"],
        )

    def test_missing_public_asset_is_not_a_download_failure(self):
        result = download_from_candidates([], Path("unused.mp3"), "", 1)
        self.assertEqual(result["status"], "not_available")

    def test_mp4_audio_signature_is_detected(self):
        self.assertEqual(signature_kind(b"\x00\x00\x00\x1cftypM4A "), "mp4")

    def test_normalize_video(self):
        work = normalize_work(fake_work("10000000001", 100))
        self.assertEqual(work["type"], "视频")
        self.assertEqual(work["source_url"], "https://www.douyin.com/video/10000000001")
        self.assertEqual(work["recommend_count"], 5)
        self.assertEqual(len(work["_video_urls"]), 1)

    def test_normalize_note(self):
        work = normalize_work(fake_work("10000000002", 100, images=True))
        self.assertEqual(work["type"], "图文")
        self.assertEqual(work["source_url"], "https://www.douyin.com/note/10000000002")
        self.assertEqual(len(work["_image_urls"]), 1)

    def test_select_all_pinned_plus_recent_without_overlap(self):
        items = [
            fake_work("10000000001", 10, is_top=True),
            fake_work("10000000002", 20, is_top=True),
            fake_work("10000000003", 50),
            fake_work("10000000004", 40),
            fake_work("10000000005", 30),
        ]
        selected = select_pinned_and_recent(items, 2)
        self.assertEqual([row["aweme_id"] for row in selected], [
            "10000000002", "10000000001", "10000000003", "10000000004"
        ])
        self.assertEqual([row["selection_reason"] for row in selected], [
            "置顶", "置顶", "最近", "最近"
        ])


if __name__ == "__main__":
    unittest.main()
