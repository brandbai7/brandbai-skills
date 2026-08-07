from __future__ import annotations

import unittest

from collector_core import (
    CollectionError,
    canonical_item_url,
    choose_review_status,
    derived_review_id,
    extract_item_id,
    navigation_item_url,
    pseudonymize_author,
    sanitize_media_url,
)


class CollectorCoreTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
