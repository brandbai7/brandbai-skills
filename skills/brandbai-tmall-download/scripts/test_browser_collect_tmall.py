from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import browser_collect_tmall as collector


ITEM_URL = "https://detail.tmall.com/item.htm?id=123456789&skuId=987654&spm=synthetic"


class FakeBody:
    def inner_text(self, timeout: int) -> str:
        return ""


class FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.navigated_url = ""

    def goto(self, url: str, **_: object) -> None:
        self.url = url
        self.navigated_url = url

    def wait_for_timeout(self, _: int) -> None:
        return None

    def locator(self, selector: str) -> FakeBody:
        if selector != "body":
            raise AssertionError(f"Unexpected selector: {selector}")
        return FakeBody()


class FakeCards:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.expressions: list[str] = []

    def evaluate_all(self, expression: str) -> list[dict[str, object]]:
        self.expressions.append(expression)
        return self.rows


class FakeReviewRoot:
    def __init__(self, cards: FakeCards) -> None:
        self.cards = cards

    def locator(self, selector: str) -> FakeCards:
        self.assert_comment_selector(selector)
        return self.cards

    @staticmethod
    def assert_comment_selector(selector: str) -> None:
        if selector != '[class*="Comment--"]':
            raise AssertionError(f"Unexpected selector: {selector}")

    def evaluate(self, expression: str) -> object:
        if "scrollTop" in expression and "scrollHeight" in expression:
            return {"top": 900, "height": 1000, "client": 100}
        return None


class BrowserCollectTmallTests(unittest.TestCase):
    def test_reviews_mode_keeps_selected_sku_in_navigation(self) -> None:
        page = FakePage()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            with patch.object(collector, "_open_review_panel", return_value=None):
                result = collector.collect_reviews(
                    page,
                    object(),
                    ITEM_URL,
                    Path(temp),
                    assets=[],
                    max_asset_bytes=1024,
                    limit=0,
                    max_scroll_actions=1,
                    retain_masked_author=False,
                    resume=False,
                )
        self.assertEqual(
            page.navigated_url,
            "https://detail.tmall.com/item.htm?id=123456789&skuId=987654",
        )
        self.assertEqual(result["state"], "partial_requires_full_review_panel")

    def test_questions_mode_keeps_selected_sku_and_requires_full_panel(self) -> None:
        page = FakePage()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            with patch.object(collector, "_open_question_panel", return_value=None):
                result = collector.collect_questions(
                    page,
                    ITEM_URL,
                    Path(temp),
                    limit=0,
                    max_scroll_actions=1,
                    retain_masked_author=False,
                    resume=False,
                )
        self.assertEqual(
            page.navigated_url,
            "https://detail.tmall.com/item.htm?id=123456789&skuId=987654",
        )
        self.assertEqual(result["state"], "partial_requires_full_question_panel")

    def test_long_review_panel_uses_overlapping_batch_evaluation(self) -> None:
        raw_card = {
            "username": "synthetic_masked_user",
            "contents": [
                {"text": "synthetic primary review", "role": "review", "relative_event": ""},
                {"text": "synthetic follow-up", "role": "followup", "relative_event": "2 days later"},
            ],
            "dates": ["2026-08-01"],
            "purchased_sku": "synthetic sku",
            "platform_review_id": "synthetic-review-1",
            "media": [],
        }
        cards = FakeCards([raw_card])
        root = FakeReviewRoot(cards)
        page = FakePage("https://detail.tmall.com/item.htm?id=123456789&skuId=987654")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            with patch.object(collector, "_open_review_panel", return_value=root):
                result = collector.collect_reviews(
                    page,
                    object(),
                    ITEM_URL,
                    Path(temp),
                    assets=[],
                    max_asset_bytes=1024,
                    limit=0,
                    max_scroll_actions=10,
                    retain_masked_author=False,
                    resume=False,
                )
        self.assertEqual(result["state"], "complete_visible_panel_exhausted")
        self.assertEqual(result["saved_reviews"], 2)
        self.assertGreaterEqual(len(cards.expressions), 4)
        self.assertTrue(all("cards.length - 250" in value for value in cards.expressions))


if __name__ == "__main__":
    unittest.main()
