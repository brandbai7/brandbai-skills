from __future__ import annotations

import json
import shutil
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from room_metrics import RoomMetricsCollector, extract_safe_room_metrics


@contextmanager
def scratch_dir():
    path = Path(__file__).resolve().parent / f".room-metrics-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class RoomMetricExtractionTests(unittest.TestCase):
    def test_only_allowlisted_room_metrics_are_extracted(self) -> None:
        raw = {
            "room_view_stats": {"display_value": 649, "display_short": "600+"},
            "like_count": 1_537_872,
            "has_commerce_goods": True,
            "room_cart": {"show_cart": True, "total": 18, "cart_icon": "https://private"},
            "owner": {"id": "private-user-id"},
            "stream_url": {"flv": "https://signed.example/private"},
            "cookie": "private-cookie",
        }
        metrics = extract_safe_room_metrics(raw)
        self.assertEqual(metrics["online_viewers"], 649)
        self.assertEqual(metrics["online_viewers_display"], "600+")
        self.assertEqual(metrics["likes_count"], 1_537_872)
        self.assertTrue(metrics["has_commerce_goods"])
        self.assertEqual(metrics["cart_total"], 18)
        rendered = json.dumps(metrics)
        self.assertNotIn("private", rendered)
        self.assertNotIn("stream_url", rendered)
        self.assertNotIn("owner", rendered)

    def test_missing_values_remain_unknown(self) -> None:
        metrics = extract_safe_room_metrics({"room_cart": {}})
        self.assertIsNone(metrics["online_viewers"])
        self.assertIsNone(metrics["likes_count"])
        self.assertIsNone(metrics["has_commerce_goods"])
        self.assertIsNone(metrics["cart_total"])


class RoomMetricCollectorTests(unittest.TestCase):
    def test_collector_writes_timestamped_snapshot_without_raw_response(self) -> None:
        with scratch_dir() as temporary:
            output = temporary / "room_metrics.jsonl"

            def fetcher(_: str) -> dict[str, object]:
                return {
                    "room_view_stats": {"display_value": 123},
                    "like_count": 456,
                    "stream_url": {"flv": "https://signed.example/private"},
                }

            collector = RoomMetricsCollector(
                room_url="https://live.douyin.com/123",
                output_path=output,
                recording_started_epoch_ms=int(time.time() * 1000) - 100,
                interval_seconds=10,
                fetcher=fetcher,
            )
            collector.start()
            deadline = time.monotonic() + 2
            while collector.sample_count < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            collector.stop()

            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            snapshots = [row for row in rows if row["event_type"] == "room_snapshot"]
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["payload"]["online_viewers"], 123)
            self.assertGreaterEqual(snapshots[0]["recording_offset_seconds"], 0)
            rendered = json.dumps(rows)
            self.assertNotIn("signed.example", rendered)


if __name__ == "__main__":
    unittest.main()
