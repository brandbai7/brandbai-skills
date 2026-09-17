from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

import compile_live_interaction_evidence as dut


class InteractionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".test-live-interaction-evidence"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir()

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    @staticmethod
    def write_jsonl(path: Path, rows):
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def make_legacy_inputs(self):
        comments = self.root / "comments.jsonl"
        products = self.root / "products.jsonl"
        snapshots = self.root / "snapshots.jsonl"
        transcripts = self.root / "transcripts.jsonl"
        self.write_jsonl(
            snapshots,
            [
                {"snapshot_id": "s1", "media_offset_seconds": 10.0, "within_recording_window": True, "online_viewers": 120},
                {"snapshot_id": "s2", "media_offset_seconds": 15.0, "within_recording_window": True, "online_viewers": 118},
                {"snapshot_id": "s3", "media_offset_seconds": 20.0, "within_recording_window": True, "online_viewers": 115},
            ],
        )
        self.write_jsonl(
            comments,
            [
                {"comment_event_id": "c1", "masked_user": "测***", "text": "测试库存没抢到还能加吗", "observation_kind": "new_visible", "media_offset_seconds": 15.0, "within_recording_window": True},
                {"comment_event_id": "c2", "masked_user": "例***", "text": "还能补测试库存吗", "observation_kind": "new_visible", "media_offset_seconds": 15.0, "within_recording_window": True},
                {"comment_event_id": "c3", "masked_user": "样***", "text": "测试订单什么时候发货", "observation_kind": "new_visible", "media_offset_seconds": 20.0, "within_recording_window": True},
            ],
        )
        self.write_jsonl(
            products,
            [
                {"product_event_id": "p1", "event_type": "baseline_visible", "product_title": "测试礼盒", "display_price": "500", "media_offset_seconds": 10.0, "within_recording_window": True},
                {"product_event_id": "p2", "event_type": "visible_product_changed", "product_title": "测试礼盒活动版", "display_price": "300", "media_offset_seconds": 20.0, "within_recording_window": True},
            ],
        )
        self.write_jsonl(
            transcripts,
            [
                {"status": "completed", "media_start_seconds": 10.0, "media_end_seconds": 20.0, "text": "没抢到的最后两单还能加，准备捡漏", "resolved_model": "synthetic-lite", "human_review_status": "NOT_REVIEWED"},
                {"status": "completed", "media_start_seconds": 20.0, "media_end_seconds": 30.0, "text": "三二一拍一号链接，多送测试面霜", "resolved_model": "synthetic-lite", "human_review_status": "NOT_REVIEWED"},
            ],
        )
        return comments, products, snapshots, transcripts

    def test_legacy_compilation_preserves_windows_and_noncausal_relations(self):
        comments, products, snapshots, transcripts = self.make_legacy_inputs()
        output = self.root / "result"
        args = dut.build_parser().parse_args(
            [
                "--legacy-comments", str(comments),
                "--legacy-products", str(products),
                "--legacy-room-snapshots", str(snapshots),
                "--transcript-segments", str(transcripts),
                "--out", str(output),
            ]
        )
        self.assertEqual(dut.run(args), dut.EXIT_COMPLETE)
        comment_rows = [json.loads(line) for line in (output / "data" / "comment_host_relations.jsonl").read_text(encoding="utf-8").splitlines()]
        stock = next(row for row in comment_rows if row["category"] == "stock_restock")
        shipping = next(row for row in comment_rows if row["category"] == "shipping_fulfilment")
        self.assertEqual(stock["first_seen_lower_bound_seconds"], 10.0)
        self.assertEqual(stock["first_seen_upper_bound_seconds"], 15.0)
        self.assertEqual(stock["relation_level"], "GROUP_RESPONSE_CANDIDATE")
        self.assertFalse(stock["causal_claim_allowed"])
        self.assertEqual(shipping["relation_level"], "NOT_OBSERVED_IN_WINDOW")
        product_rows = [json.loads(line) for line in (output / "data" / "product_host_relations.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(product_rows), 1)
        self.assertTrue(product_rows[0]["cta_observed"])
        self.assertFalse(product_rows[0]["spoken_price_verified"])
        manifest = json.loads((output / "data" / "interaction_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete_evidence_compilation")
        self.assertFalse(manifest["frame_accurate_alignment"])
        self.assertFalse(manifest["causal_claim_allowed"])

    def test_unified_event_input_is_supported(self):
        visible = self.root / "visible.jsonl"
        transcripts = self.root / "transcripts.jsonl"
        rows = [
            {"visible_event_id": "v1", "event_type": "room_snapshot", "recording_offset_seconds": 5.0, "within_recording_window": True, "payload": {"online_viewers": 50}, "time_alignment_status": "wall_clock_approximate_uncalibrated"},
            {"visible_event_id": "v2", "event_type": "comment_visible", "recording_offset_seconds": 6.0, "within_recording_window": True, "payload": {"masked_user": "测***", "text": "还能加测试库存吗", "observation_kind": "new_visible"}, "time_alignment_status": "wall_clock_approximate_uncalibrated"},
            {"visible_event_id": "v3", "event_type": "product_state", "recording_offset_seconds": 7.0, "within_recording_window": True, "payload": {"visible": True, "product_title": "测试礼盒", "display_price": "100", "change_kind": "visible_product_changed"}, "time_alignment_status": "wall_clock_approximate_uncalibrated"},
        ]
        self.write_jsonl(visible, rows)
        self.write_jsonl(transcripts, [{"status": "completed", "media_start_seconds": 5.0, "media_end_seconds": 10.0, "text": "最后一单还能加，拍测试链接"}])
        output = self.root / "unified-result"
        args = dut.build_parser().parse_args(["--visible-events", str(visible), "--transcript-segments", str(transcripts), "--out", str(output)])
        self.assertEqual(dut.run(args), dut.EXIT_COMPLETE)
        manifest = json.loads((output / "data" / "interaction_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_mode"], "unified_visible_page_events")
        self.assertEqual(manifest["counts"]["comments_aligned"], 1)


if __name__ == "__main__":
    unittest.main()
