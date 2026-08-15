import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from selection_contract import SelectionContractError, load_selection


class SelectionContractTests(unittest.TestCase):
    def test_loads_plugin_workbook_and_preserves_unknown_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "works.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "作品清单"
            sheet.append([
                "序号", "作品ID", "类型", "作者", "标题/发布文案", "发布时间",
                "点赞数", "分享数", "评论数", "收藏数", "播放数", "是否置顶",
                "作品链接", "来源页面类型", "来源关键词", "来源排序",
            ])
            sheet.append([
                1, "7654321098765432101", "视频", "合成作者", "合成标题", "2026-01-01T00:00:00Z",
                10, 2, 3, 4, None, "是",
                "https://www.tiktok.com/@synthetic/video/7654321098765432101",
                "creator", "", 1,
            ])
            book.save(path)
            book.close()
            rows, metadata = load_selection(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["work_id"], "7654321098765432101")
            self.assertTrue(rows[0]["is_pinned"])
            self.assertIsNone(rows[0]["metrics"]["plays"])
            self.assertEqual(metadata["selection_mode"], "plugin_excel")

    def test_loads_v1_json_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps({
                "contract": "brandbai.tiktok.selection/v1",
                "source": {"page_type": "search", "keyword": "synthetic query"},
                "selection": {"mode": "manual"},
                "works": [
                    {"work_id": "7654321098765432101", "work_type": "video",
                     "url": "https://www.tiktok.com/@synthetic/video/7654321098765432101"},
                    {"work_id": "7654321098765432101", "work_type": "video",
                     "url": "https://www.tiktok.com/@synthetic/video/7654321098765432101"},
                    {"work_id": "7654321098765432102", "work_type": "photo",
                     "url": "https://www.tiktok.com/@synthetic/photo/7654321098765432102"},
                ],
            }), encoding="utf-8")
            rows, metadata = load_selection(path)
            self.assertEqual([row["work_id"] for row in rows], [
                "7654321098765432101", "7654321098765432102",
            ])
            self.assertEqual(metadata["keyword"], "synthetic query")

    def test_rejects_mismatched_id_and_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            path.write_text(json.dumps({
                "contract": "brandbai.tiktok.selection/v1",
                "works": [{
                    "work_id": "7654321098765432102",
                    "url": "https://www.tiktok.com/@synthetic/video/7654321098765432101",
                }],
            }), encoding="utf-8")
            with self.assertRaises(SelectionContractError):
                load_selection(path)


if __name__ == "__main__":
    unittest.main()
