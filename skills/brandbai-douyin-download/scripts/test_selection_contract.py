import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from openpyxl import Workbook

from selection_contract import load_selection, seed_from_url


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_selection_test_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


class SelectionContractTests(unittest.TestCase):
    def test_loads_v1_json_and_deduplicates(self):
        with workspace_temp() as temp:
            path = temp / "selection.json"
            path.write_text(json.dumps({
                "contract": "brandbai.douyin.selection/v1",
                "source": {"page_type": "search", "keyword": "测试关键词"},
                "selection": {"mode": "manual"},
                "works": [
                    {"aweme_id": "12345678901", "type": "video", "title": "A"},
                    {"aweme_id": "12345678901", "type": "video", "title": "duplicate"},
                    {"aweme_id": "22345678901", "type": "note", "title": "B"},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            rows, metadata = load_selection(path)
            self.assertEqual([row["aweme_id"] for row in rows], ["12345678901", "22345678901"])
            self.assertEqual(rows[1]["source_url"], "https://www.douyin.com/note/22345678901")
            self.assertEqual(metadata["keyword"], "测试关键词")

    def test_loads_current_plugin_works_excel(self):
        with workspace_temp() as temp:
            path = temp / "works.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "作品清单"
            sheet.append([
                "序号", "作品ID", "类型", "作者", "标题/发布文案", "发布时间",
                "点赞数", "分享数", "评论数", "收藏数", "是否置顶", "作品链接",
                "来源页面类型", "来源关键词", "来源排序",
            ])
            sheet.append([
                1, "32345678901", "视频", "测试作者", "测试标题", "2026-08-06T10:00:00+08:00",
                10, 2, 3, 4, "否", "https://www.douyin.com/video/32345678901",
                "search", "测试关键词", 1,
            ])
            book.save(path)
            book.close()
            rows, metadata = load_selection(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["author"], "测试作者")
            self.assertEqual(rows[0]["source_keyword"], "测试关键词")
            self.assertEqual(metadata["selection_mode"], "manual_excel")

    def test_modal_url_is_an_explicit_work(self):
        seed = seed_from_url(
            "https://www.douyin.com/user/test?from_tab_name=main&modal_id=42345678901",
            1,
        )
        self.assertEqual(seed["aweme_id"], "42345678901")
        self.assertEqual(seed["type"], "视频")


if __name__ == "__main__":
    unittest.main()
