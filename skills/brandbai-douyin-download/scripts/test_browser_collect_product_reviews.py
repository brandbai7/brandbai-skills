"""Synthetic transport/persistence tests; no browser or platform network."""
import copy
import json
import shutil
import uuid
from contextlib import contextmanager
import unittest
from pathlib import Path
from openpyxl import load_workbook

from browser_collect_product_reviews import collect_product_reviews, normalize_review, source_image, ProductReviewError

WORK = "7000000000000000001"
PRODUCT = {"title": "合成测试商品标题", "shop_name": "合成旗舰店"}
LEASE = {"documentToken": "doc", "contextKey": "work:" + WORK, "generation": "doc:1", "sourceWorkId": WORK,
         "sourceSurfaceInstance": "work-1", "productPanelInstanceId": "product-1", "reviewSurfaceInstanceId": "reviews-1", "filterKey": "all"}


@contextmanager
def workspace_temp():
    path = Path(__file__).resolve().parent / ("_review_test_" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def review(index=1, content=None):
    return {"reviewId": "", "reviewerName": "合成用户" + str(index), "dateText": "2天前", "purchasedSku": "50g",
            "content": "合成评价" + str(index) if content is None else content, "images": [], "helpfulCount": 0}


class FakePage:
    def __init__(self, out, rows=None, reason="source_exhausted", lease=None):
        self.out = Path(out); self.rows = rows if rows is not None else [review()]
        self.surface = {"mode": "product", "ready": True, "lease": copy.deepcopy(lease or LEASE),
                        "product": {"title": PRODUCT["title"], "shopName": PRODUCT["shop_name"], "productId": ""},
                        "filterLabel": "全部", "visibleReviewCount": len(self.rows), "declaredReviewCount": 9000}
        self.reason = reason; self.pending = []; self.calls = []; self.pause_requested = False
        self.raise_interrupt = False; self.raise_prepare = False; self.bad_capture_lease = False

    def evaluate(self, script, value=None):
        if not script.startswith("value =>"):
            return None
        method = script.split("V060.")[1].split("(")[0]
        self.calls.append(method)
        if method == "configure":
            if self.raise_prepare:
                raise RuntimeError("platform warning with https://private/?cookie=DO_NOT_EXPORT")
            return self.surface
        if method == "open":
            self.surface["lease"] = copy.deepcopy(LEASE); return self.surface
        if method == "start":
            self.task = value
            base = {"taskId": value["id"], "runId": value["runId"], "lease": copy.deepcopy(value["lease"]),
                    "visibleReviewCount": len(self.rows), "declaredReviewCount": 9000}
            self.pending = [dict(base, type="CAPTURE_DOUYIN_COMMERCE_REVIEWS", rows=self.rows),
                            dict(base, type="FINISH_DOUYIN_COMMERCE_REVIEWS", status="finished" if self.reason == "source_exhausted" else "interrupted",
                                 doneReason=self.reason, completeness="complete_visible_panel_exhausted" if self.reason == "source_exhausted" else "partial_" + self.reason,
                                 exhausted=self.reason == "source_exhausted", emptyConfirmed=not self.rows)]
            if self.bad_capture_lease:
                self.pending[0]["lease"]["filterKey"] = "foreign"
            return {"ok": True}
        if method == "pause":
            self.pause_requested = True
            if self.pending:
                self.pending[-1].update(status="paused", doneReason="user_paused", completeness="partial_user_paused", exhausted=False)
            return {"ok": True}
        if method == "poll":
            if self.pending:
                item = self.pending.pop(0)
                return {"active": True, "items": [{"id": len(self.calls), "message": item}]}
            return {"active": False, "items": []}
        if method == "ack":
            if value["response"].get("ok"):
                manifest = json.loads((self.out / "product_review_manifest.json").read_text(encoding="utf-8"))
                rows = (self.out / "product_reviews.jsonl").read_text(encoding="utf-8").splitlines()
                assert manifest["review_count"] == value["response"]["task"]["reviewCount"] == len(rows)
            return None
        raise AssertionError(method)

    def wait_for_timeout(self, value):
        if self.raise_interrupt:
            self.raise_interrupt = False
            raise KeyboardInterrupt()


class ProductReviewTests(unittest.TestCase):
    def run_case(self, page, path, **kwargs):
        result = collect_product_reviews(page, WORK, PRODUCT, path, **kwargs)
        manifest = json.loads((Path(path) / "product_review_manifest.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (Path(path) / "product_reviews.jsonl").read_text(encoding="utf-8").splitlines()]
        return result, manifest, rows

    def test_saved_ack_export_and_anonymization(self):
        with workspace_temp() as path:
            raw = review(content="=HYPERLINK(\"untrusted\")")
            page = FakePage(path, [raw, copy.deepcopy(raw)])
            result, manifest, rows = self.run_case(page, path)
            self.assertEqual(result, 0); self.assertEqual(len(rows), 1)
            self.assertEqual(manifest["declared_review_count"], 9000); self.assertEqual(manifest["review_count"], 1)
            self.assertNotIn("合成用户", json.dumps(rows, ensure_ascii=False))
            book = load_workbook(Path(path) / "商品评价.xlsx")
            self.assertEqual(book["商品评价"]["A2"].data_type, "s")
            self.assertEqual(book["商品评价"]["N2"].value, WORK)

    def test_media_only_signed_evidence_keeps_count_without_credentials(self):
        with workspace_temp() as path:
            row = review(content="")
            row["images"] = ["https://p11-sign.douyinpic.com/synthetic.jpg?signature=DO_NOT_EXPORT", "data:image/svg+xml,ICON"]
            result, _, rows = self.run_case(FakePage(path, [row]), path)
            self.assertEqual(result, 0); self.assertEqual(rows[0]["content"], "")
            self.assertEqual(rows[0]["image_count"], 1); self.assertEqual(rows[0]["images"], [])
            self.assertEqual(rows[0]["omitted_image_link_count"], 1)
            self.assertNotIn("DO_NOT_EXPORT", (Path(path) / "product_reviews.jsonl").read_text())
            self.assertNotIn("signature", (Path(path) / "product_review_manifest.json").read_text())

    def test_pause_control_and_same_document_resume_do_not_duplicate(self):
        with workspace_temp() as path:
            control = Path(path) / "product_review_control.json"
            control.write_text('{"action":"pause"}')
            page = FakePage(path)
            result, manifest, rows = self.run_case(page, path)
            self.assertEqual(result, 3); self.assertEqual(manifest["status"], "paused"); self.assertEqual(len(rows), 1)
            control.unlink()
            page.rows = [review(), review(2)]
            result, manifest, rows = self.run_case(page, path, resume=True)
            self.assertEqual(result, 0); self.assertEqual(len(rows), 2)

    def test_keyboard_interrupt_flushes_and_exports_paused(self):
        with workspace_temp() as path:
            page = FakePage(path); page.raise_interrupt = True
            result, manifest, rows = self.run_case(page, path)
            self.assertEqual(result, 3); self.assertEqual(manifest["status"], "paused"); self.assertEqual(len(rows), 1)
            self.assertTrue((Path(path) / "商品评价.xlsx").exists())

    def test_cross_session_unknown_product_and_changed_filter_leave_old_files_untouched(self):
        for field in ("documentToken", "filterKey", "productPanelInstanceId"):
            with self.subTest(field=field), workspace_temp() as path:
                self.run_case(FakePage(path, reason="user_paused"), path)
                before = {name: (Path(path) / name).read_bytes() for name in ("product_reviews.jsonl", "product_review_manifest.json")}
                lease = dict(LEASE); lease[field] += "-changed"
                with self.assertRaises(ProductReviewError):
                    self.run_case(FakePage(path, lease=lease), path, resume=True)
                for name, value in before.items():
                    self.assertEqual((Path(path) / name).read_bytes(), value)

    def test_hidden_warning_and_selector_failures_never_complete(self):
        for reason in ("page_hidden", "selector_drift", "product_panel_closed", "loading_stalled", "run_budget"):
            with self.subTest(reason=reason), workspace_temp() as path:
                result, manifest, rows = self.run_case(FakePage(path, reason=reason), path)
                self.assertEqual(result, 3); self.assertEqual(manifest["status"], "partial"); self.assertEqual(len(rows), 1)

    def test_preparation_failure_retains_partial_without_error_urls(self):
        with workspace_temp() as path:
            page = FakePage(path); page.raise_prepare = True
            with self.assertRaises(ProductReviewError):
                self.run_case(page, path)
            saved = (Path(path) / "product_review_manifest.json").read_text()
            self.assertNotIn("DO_NOT_EXPORT", saved); self.assertIn("partial_browser_error", saved)

    def test_full_positive_page_count_never_makes_zero_saved_success(self):
        with workspace_temp() as path:
            page = FakePage(path); page.bad_capture_lease = True
            result, manifest, rows = self.run_case(page, path)
            self.assertEqual(result, 3); self.assertEqual(rows, []); self.assertNotEqual(manifest["status"], "complete")

    def test_budget_preserves_only_requested_rows_and_partial(self):
        with workspace_temp() as path:
            result, manifest, rows = self.run_case(FakePage(path, [review(1), review(2)]), path, max_reviews=1)
            self.assertEqual(result, 3); self.assertEqual(len(rows), 1); self.assertEqual(manifest["done_reason"], "run_budget")

    def test_source_validation_and_signed_rotation_have_stable_dedupe(self):
        manifest = {"task_id": "task", "source_work_id": WORK, "product": {"product_id": ""}, "privacy_mode": "hash"}
        first = review(content=""); first["images"] = ["https://p3.ecombdimg.com/image.jpg?token=a"]
        second = dict(first, images=["https://p3.ecombdimg.com/image.jpg?token=b"])
        self.assertEqual(normalize_review(first, manifest)["review_id"], normalize_review(second, manifest)["review_id"])
        for url in ("https://p3.ecombdimg.com.evil.example/x", "https://evil-ecombdimg.com/x", "http://p3.ecombdimg.com/x", "https://u:p@p3.ecombdimg.com/x"):
            self.assertIsNone(source_image(url))
        self.assertIsNone(normalize_review(review(content=""), manifest))

    def test_completed_resume_preserves_complete_and_does_not_start_again(self):
        with workspace_temp() as path:
            page = FakePage(path)
            self.assertEqual(self.run_case(page, path, max_reviews=1)[0], 0)
            before = (path / "product_review_manifest.json").read_bytes()
            page.calls.clear()
            self.assertEqual(self.run_case(page, path, max_reviews=1, resume=True)[0], 0)
            self.assertNotIn('start', page.calls)
            self.assertEqual((path / "product_review_manifest.json").read_bytes(), before)

    def test_late_media_reply_and_helpful_updates_keep_fallback_review_identity(self):
        manifest = {"task_id":"task", "source_work_id":WORK, "product":{"product_id":""}, "privacy_mode":"hash"}
        initial = review()
        later = dict(initial,images=['https://p3.ecombdimg.com/late.jpg'],merchantReply='已收到',helpfulCount=18)
        self.assertEqual(normalize_review(initial,manifest)['review_id'],normalize_review(later,manifest)['review_id'])


if __name__ == "__main__":
    unittest.main()
