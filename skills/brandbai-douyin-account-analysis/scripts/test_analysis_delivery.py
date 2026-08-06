#!/usr/bin/env python3
"""Synthetic tests for delivery initialization and validation."""

from __future__ import annotations

import io
import csv
import json
import shutil
import unittest
import uuid
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from build_analysis_dataset import main as build_main
from build_d1_workbook import main as build_d1_main
from init_analysis_delivery import main as init_main
from validate_analysis_delivery import main as validate_main


TEST_ROOT = Path(__file__).resolve().parent / "_analysis_delivery_test_artifacts"
SHEETS = ("阅读说明", "作品与对齐", "评论语义证据", "结论证据卡")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_minimal_xlsx(path: Path, rows_by_sheet: dict[str, int], placeholder: bool = False) -> None:
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    sheet_nodes = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(SHEETS, 1)
    )
    workbook = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>{sheet_nodes}</sheets></workbook>'
    )
    relation_nodes = "".join(
        f'<Relationship Id="rId{index}" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(SHEETS) + 1)
    )
    relationships = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{package_rel}">{relation_nodes}</Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        for index, sheet_name in enumerate(SHEETS, 1):
            row_count = rows_by_sheet.get(sheet_name, 0)
            rows = "".join(
                f'<row r="{row_number + 6}"><c r="A{row_number + 6}" t="inlineStr"><is><t>'
                f'{"{{unfinished}}" if placeholder else f"synthetic-{row_number}"}'
                f'</t></is></c></row>'
                for row_number in range(row_count)
            )
            sheet_xml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<worksheet xmlns="{main}"><sheetData>{rows}</sheetData></worksheet>'
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml)


def video_row(video_id: str, role: str) -> dict:
    return {
        "video_id": video_id,
        "sample_role": role,
        "observation_level": "cover_metadata",
        "observed_sources": ["metadata", "cover", "comments"],
        "performance_level": "high" if role == "pinned" else "normal",
        "comparison_group": "synthetic-task",
        "user_task": "合成用户任务",
        "opening": "合成开头",
        "key_action": "合成动作",
        "visual_anchor": "合成视觉锚点",
        "video_message": "合成视频主旨",
        "comment_reception_center": "合成评论接收中心",
        "alignment_level": "high",
        "attention_owner": "content",
        "commercial_memory": "none",
        "mechanism_candidate": "合成候选机制",
        "counterexample": "合成反例",
        "alternative_explanations": ["synthetic alternative"],
        "completeness": "complete",
        "source_url": f"https://example.invalid/video/{video_id}",
    }


def evidence_row(evidence_id: str, video_id: str, source_row: int) -> dict:
    return {
        "evidence_id": evidence_id,
        "video_id": video_id,
        "comment_id": f"comment-{source_row}",
        "source_role": "top_level",
        "comment_text": "合成评论证据",
        "digg_count": 1,
        "reply_count": 0,
        "comment_time": "2026-08-05T12:00:00+08:00",
        "parent_id": "",
        "source_file": "synthetic/comments.csv",
        "source_row": source_row,
        "completeness": "complete",
        "main_semantic": "C",
        "auxiliary_tags": ["复述观点"],
        "reception_depth": "S2",
    }


def completed_delivery(
    root: Path,
    placeholder_workbook: bool = False,
    preserve_prepared: bool = False,
    preserve_workbook: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    works = [
        {"video_id": "synthetic-001", "sample_role": "pinned", "title": "合成置顶作品"},
        {"video_id": "synthetic-002", "sample_role": "recent_non_pinned", "title": "合成近期作品"},
    ]
    videos = [video_row("synthetic-001", "pinned"), video_row("synthetic-002", "recent_non_pinned")]
    evidence = [evidence_row("E-001", "synthetic-001", 1), evidence_row("E-002", "synthetic-002", 2)]
    claims = [{
        "claim_id": "C-001",
        "topic": "candidate_mechanism",
        "claim": "合成模式只用于测试",
        "evidence_status": "P",
        "reception_level": "high",
        "supporting_video_ids": ["synthetic-001", "synthetic-002"],
        "supporting_evidence_ids": ["E-001", "E-002"],
        "evidence_summary": "两条合成作品均有合成评论证据",
        "counterevidence": "合成反例已记录",
        "alternative_explanations": ["synthetic alternative"],
        "usable_scope": "仅用于合成测试",
        "prohibited_scope": "不得作为真实账号判断",
        "validation_next": "增加合成对照",
    }]
    if not preserve_prepared:
        write_json(root / "data/analysis_manifest.json", {"status": "ready_for_analysis"})
        write_json(root / "data/works_sample.json", {"works": works})
        write_json(root / "data/comment_inventory.json", [])
    write_json(root / "data/delivery_manifest.json", {
        "schema_version": "1.0",
        "analysis_status": "complete",
        "analysis_mode": "lightweight_no_asr",
        "account_name": "合成测试账号",
        "analysis_time": "2026-08-05T12:00:00+08:00",
        "deep_review_video_ids": ["synthetic-001", "synthetic-002"],
        "limitations": [],
    })
    write_jsonl(root / "data/video_analysis.jsonl", videos)
    write_jsonl(root / "data/evidence_ledger.jsonl", evidence)
    write_jsonl(root / "data/claim_cards.jsonl", claims)

    report = "# 合成账号深度分析\n\n" + "\n\n".join(
        heading + "\n\n" + "合成分析内容，仅用于验证结构。" * 20
        for heading in (
            "## 一、结论先看", "## 二、样本与数据边界", "## 三、账号近期基线",
            "## 四、置顶作品代表什么", "## 五、用户真正接收了什么",
            "## 六、代表作品的视频—评论对齐", "## 七、高表现候选机制与失效条件",
            "## 八、一般商业承载与信任边界", "## 九、仍未知什么",
        )
    )
    notes = "# 分析说明与资料缺口\n\n" + "\n\n".join(
        heading + "\n\n" + "合成说明内容，仅用于验证结构。" * 15
        for heading in (
            "## 一、本次分析范围", "## 二、输入完成状态", "## 三、分析完成状态",
            "## 四、资料缺口", "## 五、口径说明", "## 六、建议补充",
        )
    )
    (root / "01_账号深度分析.md").write_text(report, encoding="utf-8")
    (root / "03_分析说明与资料缺口.md").write_text(notes, encoding="utf-8")
    if not preserve_workbook:
        write_minimal_xlsx(
            root / "02_D1评论语义证据包.xlsx",
            {"阅读说明": 1, "作品与对齐": 2, "评论语义证据": 2, "结论证据卡": 1},
            placeholder=placeholder_workbook,
        )


class AnalysisDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def fresh_dir(self, prefix: str) -> Path:
        value = TEST_ROOT / f"{prefix}_{uuid.uuid4().hex}"
        value.mkdir(parents=True)
        return value

    def run_quietly(self, func, argv: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = func(argv)
        return code, stream.getvalue()

    def test_completed_synthetic_delivery_is_valid(self):
        root = self.fresh_dir("valid")
        completed_delivery(root)
        code, output = self.run_quietly(validate_main, ["--delivery", str(root)])
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["status"], "valid")

    def test_end_to_end_dataset_init_fill_and_validate(self):
        source = self.fresh_dir("source")
        works_dir = source / "data" / "作品采集"
        comments_dir = source / "data" / "评论采集"
        works_dir.mkdir(parents=True)
        comments_dir.mkdir(parents=True)
        works = [
            {
                "aweme_id": "synthetic-001", "title": "合成置顶作品", "create_time": 1785900000,
                "publish_time": "2026-08-05T10:00:00+08:00", "is_pinned": True,
                "source_url": "https://example.invalid/video/synthetic-001",
                "local_folder": "03_作品素材/work_synthetic-001",
            },
            {
                "aweme_id": "synthetic-002", "title": "合成近期作品", "create_time": 1785903600,
                "publish_time": "2026-08-05T11:00:00+08:00", "is_pinned": False,
                "source_url": "https://example.invalid/video/synthetic-002",
                "local_folder": "03_作品素材/work_synthetic-002",
            },
        ]
        write_json(works_dir / "works.json", works)
        write_json(works_dir / "download_manifest.json", {"status": "complete"})
        for work in works:
            (source / work["local_folder"]).mkdir(parents=True)
        headers = [
            "aweme_id", "comment_id", "text", "reply_level", "reply_count",
            "digg_count", "id_source", "create_time",
        ]
        with (comments_dir / "comments.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for index, work in enumerate(works, 1):
                writer.writerow({
                    "aweme_id": work["aweme_id"], "comment_id": f"comment-{index}",
                    "text": "合成评论", "reply_level": 0, "reply_count": 0,
                    "digg_count": 1, "id_source": "platform",
                    "create_time": "2026-08-05T12:00:00+08:00",
                })
        write_json(comments_dir / "run_manifest.json", {"status": "complete"})

        delivery = TEST_ROOT / f"delivery_{uuid.uuid4().hex}"
        code, output = self.run_quietly(build_main, ["--input", str(source), "--out", str(delivery)])
        self.assertEqual(code, 0, output)
        code, output = self.run_quietly(init_main, ["--out", str(delivery)])
        self.assertEqual(code, 0, output)
        completed_delivery(delivery, preserve_prepared=True, preserve_workbook=True)
        workbook_path = delivery / "02_D1评论语义证据包.xlsx"
        workbook_before = workbook_path.read_bytes()
        code, output = self.run_quietly(
            build_d1_main, ["--delivery", str(delivery), "--dry-run"]
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(workbook_before, workbook_path.read_bytes())
        self.assertEqual(json.loads(output)["status"], "ready_to_build")
        code, output = self.run_quietly(build_d1_main, ["--delivery", str(delivery)])
        self.assertEqual(code, 0, output)
        with zipfile.ZipFile(workbook_path) as archive:
            workbook_xml = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            )
        self.assertIn("DYV-synthetic-001", workbook_xml)
        self.assertIn("DYC-comment-1", workbook_xml)
        self.assertNotIn("{{", workbook_xml)
        code, output = self.run_quietly(validate_main, ["--delivery", str(delivery)])
        self.assertEqual(code, 0, output)

    def test_pattern_claim_requires_two_videos(self):
        root = self.fresh_dir("pattern")
        completed_delivery(root)
        claims_path = root / "data/claim_cards.jsonl"
        claim = json.loads(claims_path.read_text(encoding="utf-8"))
        claim["supporting_video_ids"] = ["synthetic-001"]
        write_jsonl(claims_path, [claim])
        code, output = self.run_quietly(validate_main, ["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("without at least two supporting videos", output)

    def test_complete_rejects_text_only_observation(self):
        root = self.fresh_dir("text_only")
        completed_delivery(root)
        videos_path = root / "data/video_analysis.jsonl"
        videos = [json.loads(line) for line in videos_path.read_text(encoding="utf-8").splitlines()]
        videos[0]["observation_level"] = "text_only"
        videos[0]["observed_sources"] = ["metadata", "comments"]
        write_jsonl(videos_path, videos)
        code, output = self.run_quietly(validate_main, ["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("requires visual evidence", output)

    def test_all_pinned_works_require_analysis_cards(self):
        root = self.fresh_dir("pinned")
        completed_delivery(root)
        videos_path = root / "data/video_analysis.jsonl"
        write_jsonl(videos_path, [video_row("synthetic-002", "recent_non_pinned")])
        manifest = json.loads((root / "data/delivery_manifest.json").read_text(encoding="utf-8"))
        manifest["deep_review_video_ids"] = ["synthetic-002"]
        write_json(root / "data/delivery_manifest.json", manifest)
        code, output = self.run_quietly(validate_main, ["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("All pinned works require a video analysis card", output)

    def test_workbook_placeholders_are_rejected(self):
        root = self.fresh_dir("placeholder")
        completed_delivery(root, placeholder_workbook=True)
        code, output = self.run_quietly(validate_main, ["--delivery", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("still contains template placeholders", output)

    def test_initializer_dry_run_then_creates_templates_without_overwrite(self):
        root = self.fresh_dir("init")
        write_json(root / "data/analysis_manifest.json", {"status": "ready_for_analysis"})
        code, output = self.run_quietly(init_main, ["--out", str(root), "--dry-run"])
        self.assertEqual(code, 0, output)
        self.assertFalse((root / "01_账号深度分析.md").exists())
        code, output = self.run_quietly(init_main, ["--out", str(root)])
        self.assertEqual(code, 0, output)
        self.assertTrue((root / "02_D1评论语义证据包.xlsx").is_file())
        self.assertEqual(json.loads((root / "data/delivery_manifest.json").read_text(encoding="utf-8"))["analysis_status"], "draft")
        code, _ = self.run_quietly(init_main, ["--out", str(root)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
