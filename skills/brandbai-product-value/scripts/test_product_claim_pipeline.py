from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPTS = Path(__file__).parent
PREPARE = SCRIPTS / "prepare_product_claim_candidates.py"
BUILD = SCRIPTS / "build_product_claim_ledger_from_selections.py"

from prepare_product_claim_candidates import bind_footnotes, suggested_claim_type, text_candidates


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_xlsx(path: Path) -> None:
    workbook = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets>
  <sheet name="商品概览" sheetId="1" r:id="rId1"/>
  <sheet name="采集说明" sheetId="2" r:id="rId2"/>
 </sheets>
</workbook>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/>
 <Relationship Id="rId2" Target="worksheets/sheet2.xml" Type="x"/>
</Relationships>"""

    def inline_cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    sheet1 = f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1">{inline_cell('A1', '字段')}{inline_cell('B1', '值')}</row>
 <row r="2">{inline_cell('A2', '商品标题')}{inline_cell('B2', '测试商品')}</row>
 <row r="3">{inline_cell('A3', '价格识别状态')}{inline_cell('B3', 'complete')}</row>
 <row r="4">{inline_cell('A4', '当前选中规格')}{inline_cell('B4', '100g*10袋')}</row>
</sheetData></worksheet>"""
    sheet2 = f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1">{inline_cell('A1', '说明')}{inline_cell('B1', '不要进入候选')}</row>
</sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet1)
        archive.writestr("xl/worksheets/sheet2.xml", sheet2)


class ProductClaimPipelineTests(unittest.TestCase):
    def test_beauty_claim_type_suggestions(self) -> None:
        self.assertEqual(suggested_claim_type("EM08 赤陶土色"), "sku")
        self.assertEqual(suggested_claim_type("化妆品备案编号/注册证号：沪G妆网备字2025006397"), "evidence")
        self.assertEqual(suggested_claim_type("指腹余色可点涂两颊或眼部 用作腮红和眼影"), "usage")
        self.assertEqual(suggested_claim_type("泥巴质地 上嘴丝滑绵密 延展性强"), "sensory")
        self.assertEqual(suggested_claim_type("不同屏幕显示可能存在细微色差"), "warning")

    def test_high_density_labels_split_into_atomic_candidates(self) -> None:
        rows = text_candidates(
            "产品名称：测试油 净含量：5升 配料表：大豆油 贮存条件：阴凉干燥处",
            "瓶身标签",
        )
        self.assertEqual(
            [row["verbatim_text"] for row in rows],
            ["产品名称：测试油", "净含量：5升", "配料表：大豆油", "贮存条件：阴凉干燥处"],
        )

    def test_page_claim_binds_matching_footnote(self) -> None:
        rows = bind_footnotes(
            text_candidates(
                "累计销量突破50亿份*1；*1数据来源：页面后台累计销售件数",
                "页面可见文字摘录",
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["linked_footnote_indexes"], [1])
        self.assertEqual(rows[1]["claim_unit_kind"], "footnote")

    def make_fixture(self, root: Path) -> dict[str, Path]:
        delivery = root / "delivery"
        data = delivery / "data"
        source_root = root / "source"
        candidates = root / "candidates"
        selections = root / "selections"
        parts = root / "parts"
        source_root.mkdir(parents=True)
        build_xlsx(source_root / "source.xlsx")
        (source_root / "page.webp").write_bytes(b"synthetic")
        inventory = [
            {
                "source_file_id": "SF-001",
                "filename": "source.xlsx",
                "relative_path": "source.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size_bytes": (source_root / "source.xlsx").stat().st_size,
                "sha256": "1" * 64,
                "status": "indexed",
            },
            {
                "source_file_id": "SF-002",
                "filename": "page.webp",
                "relative_path": "page.webp",
                "media_type": "image/webp",
                "size_bytes": 9,
                "sha256": "2" * 64,
                "status": "indexed",
            },
        ]
        observations = [
            {
                "observation_id": "OBS-001",
                "source_file_id": "SF-001",
                "inspection_status": "inspected",
                "visible_text_excerpt": "商品资料表",
            },
            {
                "observation_id": "OBS-002",
                "source_file_id": "SF-002",
                "inspection_status": "inspected",
                "visible_heading": "页面主标题",
                "visible_text_excerpt": "累计销量突破50亿份*；0添加蔗糖",
            },
        ]
        events = [
            {
                "event_id": "AUD-001",
                "source_file_id": "SF-001",
                "relative_path": "source.xlsx",
                "phase": "claim_extract",
                "sequence": 1,
                "recorded_at": "2026-08-16T10:00:00+08:00",
                "source_sha256": "1" * 64,
                "audit_card_sha256": "",
            },
            {
                "event_id": "AUD-002",
                "source_file_id": "SF-002",
                "relative_path": "page.webp",
                "phase": "claim_extract",
                "sequence": 2,
                "recorded_at": "2026-08-16T10:01:00+08:00",
                "source_sha256": "2" * 64,
                "audit_card_sha256": "a" * 64,
            },
            {
                "event_id": "AUD-003",
                "source_file_id": "SF-002",
                "relative_path": "page.webp",
                "phase": "claim_recheck",
                "sequence": 1,
                "recorded_at": "2026-08-16T10:02:00+08:00",
                "source_sha256": "2" * 64,
                "audit_card_sha256": "a" * 64,
            },
            {
                "event_id": "AUD-004",
                "source_file_id": "SF-001",
                "relative_path": "source.xlsx",
                "phase": "claim_recheck",
                "sequence": 2,
                "recorded_at": "2026-08-16T10:03:00+08:00",
                "source_sha256": "1" * 64,
                "audit_card_sha256": "",
            },
        ]
        write_jsonl(data / "source_inventory.jsonl", inventory)
        write_jsonl(data / "source_observation.jsonl", observations)
        write_jsonl(data / "tool_audit_events.jsonl", events)
        return {
            "delivery": delivery,
            "source_root": source_root,
            "candidates": candidates,
            "selections": selections,
            "parts": parts,
        }

    def run_script(self, script: Path, *arguments: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(script), *arguments],
            cwd=SCRIPTS,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if expect_ok and result.returncode != 0:
            self.fail(f"{script.name} failed: {result.stdout}\n{result.stderr}")
        return result

    def test_end_to_end_candidates_and_claim_parts(self) -> None:
        with tempfile.TemporaryDirectory(dir=SCRIPTS) as temporary:
            paths = self.make_fixture(Path(temporary))
            self.run_script(
                PREPARE,
                "--delivery", str(paths["delivery"]),
                "--source-root", str(paths["source_root"]),
                "--out-dir", str(paths["candidates"]),
            )
            spreadsheet = json.loads((paths["candidates"] / "SF-001.json").read_text(encoding="utf-8"))
            self.assertEqual(spreadsheet["candidate_count"], 2)
            self.assertEqual(
                [row["suggested_claim_type"] for row in spreadsheet["candidates"]],
                ["identity", "sku"],
            )
            self.assertNotIn("价格识别状态", json.dumps(spreadsheet, ensure_ascii=False))
            image = json.loads((paths["candidates"] / "SF-002.json").read_text(encoding="utf-8"))
            self.assertEqual(image["candidate_count"], 3)
            self.assertEqual(image["candidates"][0]["verbatim_text"], "页面主标题")
            self.assertEqual(image["candidates"][0]["visual_locator"], "页面可见标题")
            self.assertNotIn("2023年", json.dumps(image, ensure_ascii=False))

            paths["selections"].mkdir()
            (paths["selections"] / "SF-001.json").write_text(
                json.dumps(
                    {
                        "source_file_id": "SF-001",
                        "selected_claims": [
                            {"candidate_id": "CAND-002"},
                            {"candidate_id": "CAND-001"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (paths["selections"] / "SF-002.json").write_text(
                json.dumps(
                    {
                        "source_file_id": "SF-002",
                        "selected_claims": [
                            {"candidate_id": "CAND-001"},
                            {"candidate_id": "CAND-003", "claim_type_override": "ingredient"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_script(
                BUILD,
                "--delivery", str(paths["delivery"]),
                "--candidates-dir", str(paths["candidates"]),
                "--selections-dir", str(paths["selections"]),
                "--parts-dir", str(paths["parts"]),
                "--expected-source-count", "2",
                "--dry-run",
            )
            self.run_script(
                BUILD,
                "--delivery", str(paths["delivery"]),
                "--candidates-dir", str(paths["candidates"]),
                "--selections-dir", str(paths["selections"]),
                "--parts-dir", str(paths["parts"]),
                "--expected-source-count", "2",
            )
            claims = []
            for part in sorted(paths["parts"].glob("*.jsonl")):
                claims.extend(json.loads(line) for line in part.read_text(encoding="utf-8").splitlines())
            self.assertEqual([row["claim_id"] for row in claims], ["CLM-001", "CLM-002", "CLM-003", "CLM-004"])
            self.assertEqual([row["claim_type"] for row in claims[:2]], ["identity", "sku"])
            self.assertTrue(claims[1]["critical"])
            self.assertTrue(claims[3]["critical"])
            self.assertEqual(claims[2]["claimed_at"], "2026-08-16T10:01:00+08:00")
            self.assertEqual(claims[2]["rechecked_at"], "2026-08-16T10:02:00+08:00")

    def test_unknown_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=SCRIPTS) as temporary:
            paths = self.make_fixture(Path(temporary))
            self.run_script(
                PREPARE,
                "--delivery", str(paths["delivery"]),
                "--source-root", str(paths["source_root"]),
                "--out-dir", str(paths["candidates"]),
            )
            paths["selections"].mkdir()
            for source_id in ("SF-001", "SF-002"):
                selected = "CAND-999" if source_id == "SF-001" else "CAND-001"
                (paths["selections"] / f"{source_id}.json").write_text(
                    json.dumps(
                        {"source_file_id": source_id, "selected_claims": [{"candidate_id": selected}]}
                    ),
                    encoding="utf-8",
                )
            result = self.run_script(
                BUILD,
                "--delivery", str(paths["delivery"]),
                "--candidates-dir", str(paths["candidates"]),
                "--selections-dir", str(paths["selections"]),
                "--parts-dir", str(paths["parts"]),
                "--expected-source-count", "2",
                expect_ok=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不存在的候选", result.stderr)

    def test_compiler_auto_includes_bound_footnote(self) -> None:
        with tempfile.TemporaryDirectory(dir=SCRIPTS) as temporary:
            paths = self.make_fixture(Path(temporary))
            observation_path = paths["delivery"] / "data" / "source_observation.jsonl"
            observations = [json.loads(line) for line in observation_path.read_text(encoding="utf-8").splitlines()]
            observations[1]["visible_text_excerpt"] = (
                "累计销量突破50亿份*1；*1数据来源：页面后台累计销售件数"
            )
            write_jsonl(observation_path, observations)
            self.run_script(
                PREPARE,
                "--delivery", str(paths["delivery"]),
                "--source-root", str(paths["source_root"]),
                "--out-dir", str(paths["candidates"]),
            )
            image = json.loads((paths["candidates"] / "SF-002.json").read_text(encoding="utf-8"))
            self.assertEqual(image["format_version"], "1.1")
            self.assertEqual(image["candidates"][1]["linked_footnote_candidate_ids"], ["CAND-003"])
            paths["selections"].mkdir()
            (paths["selections"] / "SF-001.json").write_text(
                json.dumps({"source_file_id": "SF-001", "selected_claims": []}),
                encoding="utf-8",
            )
            (paths["selections"] / "SF-002.json").write_text(
                json.dumps(
                    {"source_file_id": "SF-002", "selected_claims": [{"candidate_id": "CAND-002"}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_script(
                BUILD,
                "--delivery", str(paths["delivery"]),
                "--candidates-dir", str(paths["candidates"]),
                "--selections-dir", str(paths["selections"]),
                "--parts-dir", str(paths["parts"]),
                "--expected-source-count", "2",
            )
            claims = [
                json.loads(line)
                for part in sorted(paths["parts"].glob("*.jsonl"))
                for line in part.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["verbatim_text"] for row in claims], [
                "累计销量突破50亿份*1",
                "*1数据来源：页面后台累计销售件数",
            ])
            self.assertEqual(claims[1]["claim_type"], "evidence")

    def test_unreadable_source_gets_empty_candidate_packet(self) -> None:
        with tempfile.TemporaryDirectory(dir=SCRIPTS) as temporary:
            paths = self.make_fixture(Path(temporary))
            media_path = paths["source_root"] / "video.mp4"
            media_path.write_bytes(b"synthetic-video")
            inventory_path = paths["delivery"] / "data" / "source_inventory.jsonl"
            observation_path = paths["delivery"] / "data" / "source_observation.jsonl"
            event_path = paths["delivery"] / "data" / "tool_audit_events.jsonl"
            with inventory_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "source_file_id": "SF-003",
                    "filename": "video.mp4",
                    "relative_path": "video.mp4",
                    "media_type": "video/mp4",
                    "size_bytes": media_path.stat().st_size,
                    "sha256": "3" * 64,
                    "status": "indexed",
                }, ensure_ascii=False) + "\n")
            with observation_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "observation_id": "OBS-003",
                    "source_file_id": "SF-003",
                    "inspection_status": "unreadable",
                    "visible_text_excerpt": "该文件类型不能在固定工具内直接预览",
                }, ensure_ascii=False) + "\n")
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "event_id": "AUD-005",
                    "source_file_id": "SF-003",
                    "relative_path": "video.mp4",
                    "phase": "claim_extract",
                    "sequence": 3,
                    "recorded_at": "2026-08-16T10:04:00+08:00",
                    "source_sha256": "3" * 64,
                    "audit_card_sha256": "",
                }, ensure_ascii=False) + "\n")
            self.run_script(
                PREPARE,
                "--delivery", str(paths["delivery"]),
                "--source-root", str(paths["source_root"]),
                "--out-dir", str(paths["candidates"]),
                "--source-file-id", "SF-003",
            )
            packet = json.loads((paths["candidates"] / "SF-003.json").read_text(encoding="utf-8"))
            self.assertEqual(packet["inspection_status"], "unreadable")
            self.assertEqual(packet["candidate_count"], 0)
            self.assertEqual(packet["candidates"], [])


if __name__ == "__main__":
    unittest.main()
