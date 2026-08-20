import unittest

from browser_collect_tiktok import (
    comments_from_payload, items_from_payload, missing_requested_asset_records,
    normalize_assets, page_kind, search_url,
)


class BrowserCollectorTests(unittest.TestCase):
    def test_routes_and_assets(self):
        self.assertEqual(page_kind("https://www.tiktok.com/@demo/photo/7654321098765432101"), "work")
        self.assertEqual(page_kind("https://www.tiktok.com/search/photo?q=x"), "search")
        self.assertEqual(page_kind("https://www.tiktok.com/@demo"), "profile")
        self.assertEqual(search_url("skin care", "photo"), "https://www.tiktok.com/search/photo?q=skin+care")
        self.assertEqual(normalize_assets("media,cover,media"), ["media", "cover"])

    def test_normalizes_video_and_photo_payloads(self):
        payload = {"itemList": [
            {"id": "7654321098765432101", "desc": "video #care", "author": {"uniqueId": "demo", "nickname": "Demo"},
             "authorStats": {"followerCount": 0, "heartCount": 12},
             "stats": {"playCount": 9, "diggCount": 2},
             "video": {"playAddr": "https://v16.tiktokcdn.com/v.mp4", "cover": "https://p16.tiktokcdn.com/c.jpg"}},
            {"id": "7654321098765432102", "desc": "photo", "author": {"uniqueId": "demo"},
             "imagePost": {"images": [
                 {"imageURL": {"urlList": ["https://p16.tiktokcdn.com/1.jpg"]}},
                 {"imageURL": {"urlList": ["https://p16.tiktokcdn.com/2.jpg"]}},
             ]}},
        ]}
        rows = items_from_payload(payload, "https://www.tiktok.com/@demo/video/7654321098765432101")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["work_type"], "video")
        self.assertEqual(rows[1]["work_type"], "photo")
        self.assertEqual(len([asset for asset in rows[1]["assets"] if asset["kind"] == "photo"]), 2)
        self.assertEqual(rows[0]["creator_snapshot"]["followers"], 0)
        self.assertEqual(rows[0]["creator_snapshot"]["total_likes"], 12)
        self.assertEqual(rows[0]["creator_snapshot"]["profile_url"], "https://www.tiktok.com/@demo")

    def test_comment_payload_tracks_terminal(self):
        payload = {"comments": [{"cid": "c1", "text": "synthetic comment", "user": {"uid": "u1"},
                                  "reply_comment_total": 2}], "has_more": 0}
        rows, exhausted = comments_from_payload(payload, "7654321098765432101")
        self.assertTrue(exhausted)
        self.assertEqual(rows[0]["author_display"], "")
        self.assertEqual(rows[0]["declared_reply_count"], 2)

    def test_missing_independent_audio_is_not_a_download_failure(self):
        work = {
            "work_id": "7654321098765432101", "work_type": "video",
            "assets": [{"kind": "video", "order": 1, "url": "https://v16.tiktokcdn.com/v.mp4"}],
        }
        rows = missing_requested_asset_records(work, ["media", "audio"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "audio")
        self.assertEqual(rows[0]["status"], "not_provided")
        self.assertIn("embedded audio", rows[0]["error_reason"])


if __name__ == "__main__":
    unittest.main()
