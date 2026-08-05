import unittest
from pathlib import Path
from types import SimpleNamespace

from download_creator_works import (
    collect_visible_works,
    download_from_candidates,
    signature_kind,
    normalize_work,
    sanitize_name,
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
