import copy
import json
import unittest
import threading
from datetime import datetime
from pathlib import Path

from product_evidence import validate_snapshot, public_url, check_detail_binding, write_product_evidence
from local_service import _validate_event_payload, ServiceInputError, TaskManager, TaskStore
from recorder_core import RecordingResult
from test_local_service import scratch_dir, payload


def card():
    return dict(visible=True, product_title="合成商品完整测试标题", display_price="¥39",
                change_kind="baseline_visible", card_observation_id="card-test-1",
                product_url=None, shop_name="合成旗舰店", offer_texts=["7天无理由退货"],
                images=[dict(url="https://p3.ecombdimg.com/synthetic.webp", kind="card_image")],
                identity_status="unconfirmed", source="live_visible_product_card")


def detail():
    p = card()
    for key in ("visible", "display_price", "change_kind"):
        p.pop(key)
    p.update(price_texts=["¥49"], sku_groups=[{"name": "容量", "options": [{"value": "50g", "selected": True}]}],
             parameter_texts=["产品参数", "品名", "合成样品"], images=[],
             source="user_opened_live_product_panel", association="fresh_panel_after_card_click",
             clicked_at_epoch_ms=1500, completeness="visible_snapshot_only")
    return p


def event(payload, kind="product_state", at=1000, sequence=1):
    return dict(payload=payload, event_type=kind, observed_at_epoch_ms=at, sequence=sequence,
                collector_session_id="page-test-123", room_url="https://live.douyin.com/123456",
                observed_at="2026-01-01T00:00:00+08:00", recording_offset_seconds=sequence,
                within_recording_window=True, visible_event_id=f"event-{sequence}")


def list_item():
    p = card()
    for key in ('visible', 'change_kind', 'card_observation_id'): p.pop(key)
    p.update(list_observation_id='list-test-1', list_position=1, explaining=True,
             source='live_visible_product_list', images=[])
    return p


def list_detail():
    p = detail(); p.pop('card_observation_id')
    p.update(list_observation_id='list-test-1', association='fresh_panel_after_list_click')
    return p


class ProductEvidenceTests(unittest.TestCase):
    def test_list_schema_binding_and_delivery_stay_distinct_from_popup(self):
        a, b = list_item(), list_detail()
        self.assertEqual(_validate_event_payload('product_list_item', a), a)
        self.assertEqual(_validate_event_payload('product_detail', b), b)
        events = [event(a, 'product_list_item'), event(b, 'product_detail', 3000, 2)]
        check_detail_binding(events)
        with scratch_dir() as root:
            write_product_evidence(root, events)
            report = (root / '04_商品资料.md').read_text(encoding='utf-8')
            self.assertIn('不是弹窗事件', report)
            self.assertIn('从商品列表打开的详情', report)
            self.assertIn('页面显示讲解中', report)
        for key, value in [('explaining', False), ('explaining', 1), ('list_position', 0), ('list_position', True), ('card_observation_id', 'card-test-1')]:
            bad = dict(a, **{key:value})
            with self.subTest(key=key), self.assertRaises(ServiceInputError):
                _validate_event_payload('product_list_item', bad)
        for key, value in [('card_observation_id', 'card-test-1'), ('association', 'fresh_panel_after_card_click')]:
            with self.subTest(key=key), self.assertRaises(ServiceInputError):
                _validate_event_payload('product_detail', dict(b, **{key:value}))
        for key, value in [('product_title', '另一件毫不相同的商品标题'), ('shop_name', '另一合成旗舰店')]:
            bad = copy.deepcopy(events); bad[1]['payload'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): check_detail_binding(bad)

    def test_legacy_events_remain_compatible_and_enhanced_events_are_validated(self):
        p = card()
        self.assertEqual(_validate_event_payload("product_state", p), p)
        legacy = {k: p[k] for k in ("visible", "product_title", "display_price", "change_kind")}
        self.assertEqual(_validate_event_payload("product_state", legacy), legacy)
        self.assertEqual(_validate_event_payload("product_detail", detail())["price_texts"], ["¥49"])
        p["change_kind"] = "visible_info_changed"
        self.assertEqual(_validate_event_payload("product_state", p)["change_kind"], "visible_info_changed")

    def test_private_fields_and_bad_links_are_rejected(self):
        for key, value in [("cookie", "secret"), ("shop_name", "收货地址：合成街道"),
                           ("product_url", "https://localhost/item"),
                           ("product_url", "https://haohuo.jinritemai.com/views/product/detail?id=123456&token=test")]:
            p = card(); p[key] = value
            with self.subTest(key=key), self.assertRaises(ServiceInputError):
                _validate_event_payload("product_state", p)
        for url in ["https://p3.ecombdimg.com.evil.test/item.jpg", "https://p3.ecombdimg.com/avatar.jpg", "https://p3.ecombdimg.com/item.jpg?signature=test"]:
            with self.assertRaises(ValueError): public_url(url, "image")

    def test_bounds_and_identity_are_not_inferred(self):
        p = detail(); p["identity_status"] = "public_product_link"
        with self.assertRaises(ValueError): validate_snapshot(p, detail=True)
        p = detail(); p["sku_groups"][0]["options"][0]["stock"] = 5
        with self.assertRaises(ValueError): validate_snapshot(p, detail=True)
        p = detail(); p["images"] = [dict(url="https://p3.ecombdimg.com/x.jpg", kind="unclassified_product_image")] * 41
        with self.assertRaises(ValueError): validate_snapshot(p, detail=True)

    def test_binding_rejects_wrong_card_collector_room_and_future_time(self):
        a, b = event(card()), event(detail(), "product_detail", 3000, 2)
        check_detail_binding([a, b])
        for key, value in [("collector_session_id", "page-other"), ("room_url", "https://live.douyin.com/654321"), ("observed_at_epoch_ms", 12000)]:
            bad = copy.deepcopy(b); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): check_detail_binding([a, bad])
        bad = copy.deepcopy(b); bad["payload"]["card_observation_id"] = "card-other"
        with self.assertRaises(ValueError): check_detail_binding([a, bad])

    def test_delivery_preserves_two_times_prices_and_not_duplicate_on_rebuild(self):
        events = [event(card()), event(detail(), "product_detail", 3000, 2)]
        with scratch_dir() as root:
            write_product_evidence(root, events)
            write_product_evidence(root, events)
            rows = [json.loads(s) for s in (root / "data/product_observations.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["payload"]["display_price"], "¥39")
            self.assertEqual(rows[1]["payload"]["price_texts"], ["¥49"])
            self.assertEqual(rows[1]["payload"]["card_observation_id"], rows[0]["payload"]["card_observation_id"])
            report = (root / "04_商品资料.md").read_text(encoding="utf-8")
            self.assertIn("不是完整商品资料", report)
            self.assertIn("缩略图下载清单.json", report)
            self.assertIn("50g", report)

    def test_task_ingestion_keeps_canonical_comments_and_idempotent_product_files(self):
        started = threading.Event()
        def recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True)
            started.set()
            stop_event.wait(timeout=5)
            return RecordingResult(task_id="ignored", session_id="synthetic-session", outcome="recorded",
                                   completion_status="partial_service_stop", valid_mp4_count=1, segment_count=1,
                                   actual_media_duration_seconds=5.0, output_root=str(config.output_root), test_only=True)
        with scratch_dir() as root:
            manager = TaskManager(store=TaskStore(root / "state/service.sqlite3"), output_root=root / "deliveries",
                                  recorder=recorder, min_free_space_gb=0)
            task, _ = manager.create(payload(collect_product_cards=True))
            try:
                self.assertTrue(started.wait(timeout=2))
                task = manager.get(task["task_id"])
                at = datetime.fromisoformat(task["started_at"]).timestamp() * 1000
                a, b = event(list_item(), 'product_list_item', at=at + 50), event(list_detail(), "product_detail", at + 600, 2)
                b["payload"]["clicked_at_epoch_ms"] = at + 100
                c = event({"masked_user": "测***", "text": "合成评论", "observation_kind": "new_visible"}, "comment_visible", at + 700, 3)
                batch = {"collector_session_id": "page-test-123", "events": [{k: e[k] for k in ("sequence", "event_type", "observed_at_epoch_ms", "room_url", "payload")} for e in (a, b, c)]}
                self.assertEqual(manager.ingest_visible_events(task["task_id"], batch)["accepted"], 3)
                self.assertEqual(manager.ingest_visible_events(task["task_id"], batch)["duplicates"], 3)
                output = Path(task["output_dir"])
                self.assertEqual(len((output / "data/visible_page_events.jsonl").read_text(encoding="utf-8").splitlines()), 3)
                self.assertEqual(len((output / "data/product_observations.jsonl").read_text(encoding="utf-8").splitlines()), 2)
            finally:
                manager.stop(task["task_id"])
                self.assertTrue(manager.wait_for_idle(timeout=3))


if __name__ == "__main__": unittest.main()
