from __future__ import annotations

import unittest

from collector_core import (
    CollectionError,
    canonical_item_url,
    choose_product_completion_state,
    choose_review_status,
    derived_review_id,
    derived_question_id,
    derived_answer_id,
    extract_item_id,
    navigation_item_url,
    pseudonymize_author,
    pseudonymize_qa_author,
    sanitize_media_url,
    sku_mapping_status,
    sku_parameter_warnings,
    canonical_image_asset_key,
    image_is_usable,
    image_content_status,
    is_usable_sku_option,
    is_platform_notice_image_url,
    media_request_url,
    normalize_price_candidates,
    sanitize_transient_video_url,
)


class CollectorCoreTests(unittest.TestCase):
    def test_legacy_http_media_is_requested_over_https_after_allowlist_check(self) -> None:
        source = "http://img.alicdn.com/imgextra/synthetic-detail.jpg?quality=80#fragment"
        self.assertEqual(
            media_request_url(source, kind="image"),
            "https://img.alicdn.com/imgextra/synthetic-detail.jpg?quality=80",
        )
        clean, redacted = sanitize_media_url(source, kind="image")
        self.assertEqual(clean, "https://img.alicdn.com/imgextra/synthetic-detail.jpg")
        self.assertTrue(redacted)
        with self.assertRaises(CollectionError):
            media_request_url("http://example.com/not-allowed.jpg", kind="image")
        with self.assertRaises(CollectionError):
            media_request_url("https://user:secret@img.alicdn.com/a.jpg", kind="image")

    def test_real_page_price_noise_is_separated_and_filtered(self) -> None:
        rows = normalize_price_candidates([
            {"text": "平台加补后￥27.78优惠前￥45.98", "context": "商品价格", "page_top": 520},
            {"text": "优惠前￥45.9", "context": "商品价格", "page_top": 530},
            {"text": "¥1专属平台礼金", "context": "购买可用", "page_top": 600},
            {"text": "推荐商品 ¥138", "context": "更多宝贝", "page_top": 6800},
        ])
        self.assertEqual([(row["role"], row["amount"]) for row in rows], [
            ("promotion_price", "27.78"),
            ("original_price", "45.98"),
            ("benefit_amount", "1"),
        ])

    def test_price_parser_separates_glued_chinese_campaign_date(self) -> None:
        rows = normalize_price_candidates([
            {"text": "店铺优惠后￥258优惠前￥3998月19日 24点结束", "context": "商品交易区", "product_scope": True},
        ])
        self.assertEqual([(row["role"], row["amount"], row["text"]) for row in rows], [
            ("promotion_price", "258", "店铺优惠后 ￥258"),
            ("original_price", "399", "优惠前 ￥399"),
        ])
        genuine_four_digit_price = normalize_price_candidates([
            {"text": "优惠前￥3998", "context": "商品交易区", "product_scope": True},
        ])
        self.assertEqual(genuine_four_digit_price[0]["amount"], "3998")
        for text, expected in [
            ("优惠前￥1008月19日结束", "100"),
            ("优惠前￥798月19日结束", "79"),
            ("优惠前￥39910月19日结束", "399"),
            ("优惠前￥66.88月19日结束", "66.8"),
        ]:
            with self.subTest(text=text):
                parsed = normalize_price_candidates([{"text": text, "context": "商品交易区", "product_scope": True}])
                self.assertEqual(parsed[0]["amount"], expected)

    def test_price_parser_prefers_self_contained_row_over_noisy_parent_context(self) -> None:
        rows = normalize_price_candidates([{
            "text": "平台加补后￥208优惠前￥250",
            "context": "平台加补后￥208 优惠前￥250 页面其他价格￥183",
            "product_scope": True,
        }])
        self.assertEqual([(row["role"], row["amount"]) for row in rows], [
            ("promotion_price", "208"), ("original_price", "250"),
        ])
        coupon = normalize_price_candidates([{
            "text": "页面价格￥183 ￥25优惠券",
            "context": "商品交易区",
            "product_scope": True,
        }])
        self.assertEqual([(row["role"], row["amount"]) for row in coupon], [
            ("current_price", "183"), ("benefit_amount", "25"),
        ])

    def test_price_parser_keeps_bare_subsidy_after_as_promotion_context(self) -> None:
        rows = normalize_price_candidates([
            {"text": "补贴后￥17.9优惠前￥20.2", "context": "商品交易区", "product_scope": True},
            {"text": "¥2.3百亿补贴", "context": "指定规格可用", "product_scope": True},
        ])
        self.assertEqual([(row["role"], row["amount"], row["text"]) for row in rows], [
            ("promotion_price", "17.9", "补贴后 ￥17.9"),
            ("original_price", "20.2", "优惠前 ￥20.2"),
            ("benefit_amount", "2.3", "百亿补贴 ￥2.3"),
        ])

    def test_sku_mapping_status_preserves_unmapped_identity_as_partial(self) -> None:
        self.assertEqual(
            sku_mapping_status("987654", [{"name": "规格", "values": ["A", "B"], "selected_value": ""}]),
            "sku_id_unmapped",
        )
        self.assertEqual(
            choose_product_completion_state(
                sku_status="sku_id_unmapped",
                detail_requested=False,
                detail_status="not_requested",
            ),
            "partial_product_identity",
        )
        self.assertEqual(
            sku_mapping_status("987654", [{"name": "规格", "values": ["A", "B"], "selected_value": "A"}]),
            "selected_sku_mapped",
        )
        self.assertEqual(
            sku_mapping_status("", [{"name": "规格", "values": ["A", "B"], "selected_value": "A"}]),
            "visible_selection_without_sku_id",
        )

    def test_sku_option_filter_rejects_page_actions_and_membership_controls(self) -> None:
        for value in ["点击查看大图", "查看详情", "加入会员", "会员权益", "加入店铺会员尊享特权", "领取优惠券", "加入购物车"]:
            self.assertFalse(is_usable_sku_option(value))
        for value in ["W24 桃皮荔枝", "NB21片 5kg以下", "原味400g", "黑胡椒味"]:
            self.assertTrue(is_usable_sku_option(value))

    def test_selected_sku_and_page_parameters_surface_explicit_conflicts(self) -> None:
        warnings = sku_parameter_warnings(
            [
                {"name": "颜色分类", "value": "W24 桃皮荔枝"},
                {"name": "尺码", "value": "NB21片 5kg以下 纸尿裤"},
            ],
            [
                {"name": "备案色号", "value": "EM05"},
                {"name": "总片数", "value": "15片"},
                {"name": "适合体重", "value": "15kg以下"},
                {"name": "产品形态", "value": "拉拉裤"},
            ],
        )
        self.assertEqual({row["reason"] for row in warnings}, {
            "color_code_conflict", "same_unit_value_conflict", "product_form_conflict",
        })
        self.assertEqual(sku_parameter_warnings(
            [{"name": "规格", "value": "400g"}], [{"name": "净含量", "value": "400g"}],
        ), [])

    def test_product_completion_keeps_detail_and_asset_failures_explicit(self) -> None:
        self.assertEqual(
            choose_product_completion_state(
                sku_status="selected_sku_mapped",
                detail_requested=True,
                detail_status="not_observed",
            ),
            "partial_detail_images_not_observed",
        )
        self.assertEqual(
            choose_product_completion_state(
                sku_status="selected_sku_mapped",
                detail_requested=True,
                detail_status="observed",
                detail_position_restored=False,
            ),
            "partial_detail_scroll_not_restored",
        )
        self.assertEqual(
            choose_product_completion_state(
                sku_status="selected_sku_mapped",
                detail_requested=False,
                detail_status="not_requested",
                failed_asset_records=True,
            ),
            "partial_asset_failure",
        )

    def test_image_variants_and_detail_spacers_have_quality_guards(self) -> None:
        compressed = "https://gw.alicdn.com/imgextra/a.jpg_q50.jpg_.webp"
        original = "https://gw.alicdn.com/imgextra/a.jpg_.webp"
        self.assertEqual(canonical_image_asset_key(compressed), canonical_image_asset_key(original))
        self.assertFalse(image_is_usable(1500, 2, "detail_image"))
        self.assertTrue(image_is_usable(750, 1200, "detail_image"))
        self.assertEqual(image_content_status(1500, 234, "detail_image", downloaded_bytes=2400), "separator_candidate")
        self.assertEqual(image_content_status(790, 126, "detail_image", downloaded_bytes=6800), "separator_candidate")

    def test_platform_notice_is_not_product_detail_content(self) -> None:
        url = "https://img.alicdn.com/imgextra/O1CN01XU1Y2d1Sk7fIMOkeU_!!6000000002290-2-tps-1125-1446.png"
        self.assertTrue(is_platform_notice_image_url(url))
        self.assertFalse(image_is_usable(1125, 1446, "detail_image", url))

    def test_temporary_video_url_is_allowed_only_with_signature_redaction(self) -> None:
        clean, redacted = sanitize_transient_video_url(
            "https://tbm-auth.alicdn.com/example/main-video.mp4?auth_key=temporary-secret"
        )
        self.assertEqual(clean, "https://tbm-auth.alicdn.com/example/main-video.mp4")
        self.assertTrue(redacted)
        with self.assertRaises(CollectionError):
            sanitize_media_url("https://tbm-auth.alicdn.com/example/main-video.mp4?auth_key=temporary-secret", kind="video")

    def test_canonical_url_removes_tracking_and_sku(self) -> None:
        value = "https://detail.tmall.com/item.htm?id=123456789&skuId=987654&spm=private"
        self.assertEqual(extract_item_id(value), "123456789")
        self.assertEqual(canonical_item_url(value), "https://detail.tmall.com/item.htm?id=123456789")
        self.assertEqual(
            navigation_item_url(value),
            "https://detail.tmall.com/item.htm?id=123456789&skuId=987654",
        )

    def test_numeric_item_id_is_supported(self) -> None:
        self.assertEqual(canonical_item_url("123456789"), "https://detail.tmall.com/item.htm?id=123456789")

    def test_non_item_hosts_are_rejected(self) -> None:
        with self.assertRaises(CollectionError):
            canonical_item_url("https://example.test/item.htm?id=123456789")

    def test_media_query_is_redacted(self) -> None:
        clean, redacted = sanitize_media_url("http://img.alicdn.com/example/a.webp?token=secret#x", kind="image")
        self.assertEqual(clean, "https://img.alicdn.com/example/a.webp")
        self.assertTrue(redacted)

    def test_account_and_extension_sources_are_rejected(self) -> None:
        for value in [
            "https://pass.tmall.com/example.gif?synthetic=1",
            "chrome-extension://extension-id/icon.png",
            "data:image/png;base64,abc",
        ]:
            with self.subTest(value=value), self.assertRaises(CollectionError):
                sanitize_media_url(value)

    def test_review_status_keeps_platform_folded_partial(self) -> None:
        self.assertEqual(
            choose_review_status(exhausted=True, folded_count=37),
            "partial_platform_folded",
        )
        self.assertEqual(
            choose_review_status(exhausted=True, folded_count=0),
            "complete_visible_panel_exhausted",
        )
        self.assertEqual(
            choose_review_status(exhausted=True, folded_count=0, limit_reached=True),
            "partial_limit_sample",
        )

    def test_pseudonym_and_derived_id_are_stable_without_exposing_name(self) -> None:
        first = pseudonymize_author("某**用户")
        second = pseudonymize_author("某**用户")
        self.assertEqual(first, second)
        self.assertNotIn("用户", first)
        review_id = derived_review_id("123456789", "某**用户", "2026-08-01", "规格A", "合成评价")
        self.assertTrue(review_id.startswith("derived:"))

    def test_question_answer_ids_and_qa_pseudonym_are_stable(self) -> None:
        question_id = derived_question_id("123456789", "合成问题：如何冲泡？")
        self.assertEqual(question_id, derived_question_id("123456789", "合成问题：如何冲泡？"))
        answer_id = derived_answer_id("123456789", question_id, "合成回答者", "合成回答内容", "已购")
        self.assertEqual(
            answer_id,
            derived_answer_id("123456789", question_id, "合成回答者", "合成回答内容", "已购"),
        )
        author_id = pseudonymize_qa_author("合成回答者")
        self.assertNotIn("回答者", author_id)


if __name__ == "__main__":
    unittest.main()
