from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import workspace_temp

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


class EmptyTextLocator:
    def count(self) -> int:
        return 0


class FakeProductPage(FakePage):
    def __init__(self, *, position_restored: bool = True) -> None:
        super().__init__()
        self.position_restored = position_restored
        self.evaluations: list[str] = []

    def get_by_text(self, _label: str, exact: bool = False) -> EmptyTextLocator:
        return EmptyTextLocator()

    def evaluate(self, expression: str, argument: object | None = None) -> dict[str, object]:
        if expression == collector.DETAIL_MODULE_LOAD_SCRIPT:
            self.evaluations.append("detail_loader")
            return {"steps": 2, "status": "detail_module_observed", "position_restored": self.position_restored}
        if expression != collector.PRODUCT_SCRIPT:
            raise AssertionError("Unexpected page script")
        module = str((argument or [""])[0])
        self.evaluations.append(module)
        if module == "product_data":
            return {
                "item_id": "123456789",
                "selected_sku_id": "987654",
                "title": "合成模块边界商品",
                "shop": {"text": "合成旗舰店", "href": ""},
                "parameters": [{"name": "品牌", "value": "合成品牌"}],
                "sku_groups": [{"name": "规格", "values": ["规格A"], "selected_value": "规格A"}],
                "snapshot": {"price_candidates": [{"text": "到手价￥79.9", "context": "商品交易区", "product_scope": True}]},
                "media": {"images": [], "videos": []},
                "module_states": {"product_data": {"status": "observed", "count": 2}},
            }
        if module == "detail_images":
            return {
                "item_id": "123456789",
                "media": {"images": [{
                    "kind": "detail_image",
                    "src": "https://img.alicdn.com/synthetic/detail.jpg",
                    "width": 750,
                    "height": 1000,
                }], "videos": []},
                "module_states": {"detail_images": {"status": "observed", "count": 1}},
            }
        raise AssertionError(f"Unexpected product module: {module}")


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
    def test_response_content_type_overrides_misleading_url_suffix(self) -> None:
        self.assertEqual(
            collector._extension_from_response("https://img.alicdn.com/a.png", "image/jpeg", "image"),
            ".jpg",
        )

    def test_product_script_has_a_narrow_price_leaf_fallback(self) -> None:
        self.assertIn("const priceLeaves = leaves.filter", collector.PRODUCT_SCRIPT)
        self.assertIn("平台加补后|到手价|券后价", collector.PRODUCT_SCRIPT)
        self.assertIn("isProductTradePriceElement", collector.PRODUCT_SCRIPT)
        self.assertIn("isCurrentProductTradeElement", collector.PRODUCT_SCRIPT)
        self.assertIn("highlightPrice--", collector.PRODUCT_SCRIPT)
        self.assertIn("pageTop > 2200 && !productScope", collector.PRODUCT_SCRIPT)
        self.assertIn("product_scope: productScope", collector.PRODUCT_SCRIPT)
        self.assertIn("const tradeLeaves = leaves.filter", collector.PRODUCT_SCRIPT)
        self.assertIn("recommendationBoundaryTop", collector.PRODUCT_SCRIPT)
        self.assertIn("isInsideRecommendationSurface", collector.PRODUCT_SCRIPT)

    def test_product_surfaces_are_collected_as_independent_modules(self) -> None:
        self.assertIn("requestedModules", collector.PRODUCT_SCRIPT)
        self.assertIn("moduleRoots", collector.PRODUCT_SCRIPT)
        self.assertIn("paramsInfoArea", collector.PRODUCT_SCRIPT)
        self.assertIn("headingModuleRoot('图文详情')", collector.PRODUCT_SCRIPT)
        self.assertIn("data-src", collector.PRODUCT_SCRIPT)
        self.assertIn("module_states", collector.PRODUCT_SCRIPT)
        source = Path(collector.__file__).read_text(encoding="utf-8")
        product_source = source[source.index("def collect_product"):source.index("def _folded_count")]
        self.assertNotIn("window.scrollTo", product_source)
        self.assertNotIn("DETAIL_LOAD_STATE_SCRIPT", product_source)
        self.assertIn('requested_modules = ["product_data"]', product_source)
        self.assertIn('requested_modules.append("main_images")', product_source)
        self.assertIn('requested_modules.append("detail_images")', product_source)
        self.assertIn('requested_modules.append("video")', product_source)

    def test_detail_lazy_load_is_bounded_to_module_and_restores_position(self) -> None:
        script = collector.DETAIL_MODULE_LOAD_SCRIPT
        self.assertIn("const originalScrollY = window.scrollY", script)
        self.assertIn("headingModuleRoot('图文详情')", script)
        self.assertIn("recommendationBoundaryTop(rootTop)", script)
        self.assertIn("const boundedBottom = Math.min(detailRootBottom, recommendationTop)", script)
        self.assertIn("attempt < 24", script)
        self.assertIn("finally", script)
        self.assertIn("window.scrollTo({top: originalScrollY", script)
        self.assertIn("position_restored", script)
        self.assertNotIn("document.body.scrollHeight", script)
        source = Path(collector.__file__).read_text(encoding="utf-8")
        product_source = source[source.index("def collect_product"):source.index("def _folded_count")]
        self.assertIn('if module == "detail_images"', product_source)
        self.assertIn("page.evaluate(DETAIL_MODULE_LOAD_SCRIPT)", product_source)

    def test_product_collection_records_bounded_detail_load_evidence(self) -> None:
        page = FakeProductPage(position_restored=True)
        with workspace_temp() as temp:
            with patch.object(collector, "download_asset", side_effect=lambda _context, _source, target, **_kwargs: {
                "file": str(target.with_suffix(".jpg")),
                "source_url": "https://img.alicdn.com/synthetic/detail.jpg",
                "source_url_query_redacted": False,
                "content_type": "image/jpeg",
                "bytes": 12,
                "status": "downloaded",
            }):
                product = collector.collect_product(
                    page,
                    object(),
                    ITEM_URL,
                    Path(temp),
                    assets=["detail_images"],
                    max_asset_bytes=1024,
                )
        self.assertEqual(page.evaluations, ["product_data", "detail_loader", "detail_images"])
        self.assertEqual(product["detail_load_steps"], 2)
        self.assertTrue(product["detail_scroll_restored"])
        self.assertEqual(product["completion_state"], "complete_observed_product")

    def test_product_collection_downgrades_when_detail_position_is_not_restored(self) -> None:
        page = FakeProductPage(position_restored=False)
        with workspace_temp() as temp:
            with patch.object(collector, "download_asset", side_effect=lambda _context, _source, target, **_kwargs: {
                "file": str(target.with_suffix(".jpg")),
                "source_url": "https://img.alicdn.com/synthetic/detail.jpg",
                "source_url_query_redacted": False,
                "content_type": "image/jpeg",
                "bytes": 12,
                "status": "downloaded",
            }):
                product = collector.collect_product(
                    page,
                    object(),
                    ITEM_URL,
                    Path(temp),
                    assets=["detail_images"],
                    max_asset_bytes=1024,
                )
        self.assertFalse(product["detail_scroll_restored"])
        self.assertEqual(product["completion_state"], "partial_detail_scroll_not_restored")

    def test_excluded_detail_strip_keeps_its_original_page_order(self) -> None:
        class StripPage(FakeProductPage):
            def evaluate(self, expression: str, argument: object | None = None) -> dict[str, object]:
                if expression != collector.PRODUCT_SCRIPT:
                    return super().evaluate(expression, argument)
                module = str((argument or [""])[0])
                if module != "detail_images":
                    return super().evaluate(expression, argument)
                self.evaluations.append(module)
                return {
                    "item_id": "123456789",
                    "media": {"images": [{
                        "kind": "detail_image",
                        "src": "https://img.alicdn.com/synthetic/strip.jpg",
                        "width": 1500,
                        "height": 2,
                        "index": 7,
                    }], "videos": []},
                    "module_states": {"detail_images": {"status": "observed", "count": 1}},
                }

        page = StripPage()
        with workspace_temp() as temp:
            product = collector.collect_product(
                page,
                object(),
                ITEM_URL,
                Path(temp),
                assets=["detail_images"],
                max_asset_bytes=1024,
            )
        excluded = next(row for row in product["media_records"] if row["status"] == "excluded_quality")
        self.assertEqual(excluded["order"], 8)
        self.assertEqual(excluded["download_order"], 0)

    def test_module_merge_does_not_erase_other_surfaces(self) -> None:
        base = {
            "item_id": "123",
            "title": "synthetic",
            "parameters": [{"name": "brand", "value": "synthetic"}],
            "media": {
                "images": [
                    {"kind": "main_image", "src": "https://img.alicdn.com/main.jpg"},
                    {"kind": "detail_image", "src": "https://img.alicdn.com/detail-old.jpg"},
                ],
                "videos": ["https://cloud.video.taobao.com/old.mp4"],
            },
            "module_states": {"main_images": {"status": "observed", "count": 1}},
        }
        incoming = {
            "item_id": "123",
            "media": {"images": [{"kind": "detail_image", "src": "https://img.alicdn.com/detail-new.jpg"}], "videos": []},
            "module_states": {"detail_images": {"status": "observed", "count": 1}},
        }
        merged = collector._merge_product_module_raw(base, incoming, "detail_images")
        self.assertEqual([row["src"] for row in merged["media"]["images"]], [
            "https://img.alicdn.com/main.jpg",
            "https://img.alicdn.com/detail-new.jpg",
        ])
        self.assertEqual(merged["media"]["videos"], ["https://cloud.video.taobao.com/old.mp4"])
        self.assertEqual(merged["parameters"][0]["value"], "synthetic")

    def test_product_video_supports_transient_tmall_media_without_persisting_signature(self) -> None:
        source = Path(collector.__file__).read_text(encoding="utf-8")
        self.assertIn("tbm-auth", source)
        self.assertIn("alicdn", source)
        self.assertIn("sanitize_transient_video_url", source)
        self.assertIn("video_probe", source)
        self.assertIn("script:not([src])", collector.PRODUCT_SCRIPT)

    def test_reviews_mode_keeps_selected_sku_in_navigation(self) -> None:
        page = FakePage()
        with workspace_temp() as temp:
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
        with workspace_temp() as temp:
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
        with workspace_temp() as temp:
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
