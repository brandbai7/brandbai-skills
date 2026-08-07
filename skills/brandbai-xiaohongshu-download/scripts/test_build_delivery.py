from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from build_delivery import build_delivery


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class BuildDeliveryTests(unittest.TestCase):
    def test_builds_three_workbooks_and_notes(self) -> None:
        out = Path(__file__).resolve().parent / ".xhs_delivery_test_runtime"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir()
        try:
            write_jsonl(out / "data" / "notes.jsonl", [{
                "note_id": "note-1", "title": "合成笔记", "body": "仅用于测试", "author_id": "author-1",
                "author_name": "测试作者", "note_type": "image", "topics": ["#测试"], "mentions": [],
                "metrics": {"likes": 12, "collects": 3, "comments": 1, "shares": 0}, "is_pinned": False,
                "canonical_url": "https://www.xiaohongshu.com/explore/note-1", "collected_at": "2026-08-07T00:00:00Z",
                "completion_state": "complete_observed_note",
            }])
            write_jsonl(out / "data" / "comments.jsonl", [{
                "comment_id": "comment-1", "comment_id_type": "platform", "note_id": "note-1", "level": 1,
                "author_id": "xhs_user_test", "content": "合成评论", "declared_reply_count": 0,
                "saved_reply_count": 0, "reply_expansion_status": "not_applicable",
            }])
            write_jsonl(out / "data" / "search_snapshots.jsonl", [{
                "search_snapshot_id": "search-1", "keyword": "测试", "tab": "全部", "filters": ["综合"],
                "captured_at": "2026-08-07T00:00:00Z", "state": "complete_first_n_visible_results",
                "results": [{"rank": 1, "note_id": "note-1", "title": "合成笔记", "author": "测试作者"}],
                "related_queries": ["相关词"],
            }])
            (out / "data" / "run_manifest.json").write_text(json.dumps({"state": "complete"}), encoding="utf-8")

            summary = build_delivery(out)
            self.assertEqual(summary["notes"], 1)
            self.assertTrue((out / "01_笔记清单.xlsx").is_file())
            self.assertTrue((out / "02_评论明细.xlsx").is_file())
            self.assertTrue((out / "03_搜索快照.xlsx").is_file())
            self.assertTrue((out / "05_采集说明.md").is_file())
        finally:
            if out.exists():
                shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()
