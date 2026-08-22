#!/usr/bin/env python3
"""Synthetic tests for classified-median account baselines."""

from __future__ import annotations

import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path

from build_account_baseline import main as baseline_main


TEST_ROOT = Path(__file__).resolve().parent / "_account_baseline_test_artifacts"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def work(video_id: str, digg: int, role: str = "recent_non_pinned") -> dict:
    return {
        "video_id": video_id,
        "sample_role": role,
        "digg_count": digg,
        "comment_count": digg // 2,
        "collect_count": digg // 4,
        "share_count": digg // 5,
    }


def classification(video_id: str, group: str = "method", status: str = "natural") -> dict:
    return {
        "video_id": video_id,
        "content_task": "帮助用户完成合成任务",
        "content_type": "合成方法内容",
        "commercial_status": status,
        "account_window": "current",
        "comparison_group": group,
        "classification_status": "included",
        "excluded_reason": "",
    }


class AccountBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def fresh(self) -> Path:
        root = TEST_ROOT / uuid.uuid4().hex
        root.mkdir(parents=True)
        return root

    def run_quietly(self, argv: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = baseline_main(argv)
        return code, stream.getvalue()

    def test_builds_reproducible_group_medians(self):
        root = self.fresh()
        write_json(root / "data/works_sample.json", {
            "works": [
                work("pinned-1", 999, "pinned"),
                work("recent-1", 10),
                work("recent-2", 30),
                work("recent-3", 20),
            ]
        })
        write_jsonl(root / "data/work_classification.jsonl", [
            classification("recent-1"),
            classification("recent-2"),
            classification("recent-3"),
        ])
        code, output = self.run_quietly(["--delivery", str(root), "--dry-run"])
        self.assertEqual(code, 0, output)
        self.assertFalse((root / "data/baseline_ledger.jsonl").exists())
        code, output = self.run_quietly(["--delivery", str(root)])
        self.assertEqual(code, 0, output)
        row = json.loads((root / "data/baseline_ledger.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["digg_median"], 20)
        self.assertEqual(row["sample_size"], 3)
        self.assertEqual(row["comparable_status"], "comparable")
        self.assertNotIn("pinned-1", row["video_ids"])

    def test_rejects_missing_recent_classification(self):
        root = self.fresh()
        write_json(root / "data/works_sample.json", {
            "works": [work("recent-1", 10), work("recent-2", 20)]
        })
        write_jsonl(root / "data/work_classification.jsonl", [classification("recent-1")])
        code, output = self.run_quietly(["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("not classified", output)

    def test_rejects_mixed_commercial_status_inside_group(self):
        root = self.fresh()
        write_json(root / "data/works_sample.json", {
            "works": [work("recent-1", 10), work("recent-2", 20)]
        })
        write_jsonl(root / "data/work_classification.jsonl", [
            classification("recent-1", status="natural"),
            classification("recent-2", status="commercial"),
        ])
        code, output = self.run_quietly(["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("mixes multiple commercial_status", output)


if __name__ == "__main__":
    unittest.main()
