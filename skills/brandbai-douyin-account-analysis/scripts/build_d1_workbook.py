#!/usr/bin/env python3
"""Build the BrandBAI D1 workbook from the delivery JSON and JSONL ledgers."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("x", MAIN_NS)

SHEET_SPECS = {
    "阅读说明": ("A", "H", 12),
    "作品与对齐": ("A", "S", 45),
    "评论语义证据": ("A", "R", 4005),
    "结论证据卡": ("A", "M", 205),
}

WORK_HEADERS = [
    "video_id（DYV-）", "样本角色", "标题", "发布时间", "观察层级", "表现层级", "用户任务",
    "前3—5秒", "关键动作/视觉锚点", "可观察内容主旨", "评论接收中心", "对齐等级", "注意力归属",
    "商业信息记忆", "候选机制", "反例", "替代解释", "完整性", "来源链接",
]
COMMENT_HEADERS = [
    "evidence_id", "video_id（DYV-）", "comment_id（DYC-）", "来源角色", "评论原文", "点赞数", "回复数",
    "评论时间", "parent_id（DYC-）", "来源文件", "来源行", "完整性", "主语义", "辅助标签", "接收深度",
    "编码说明", "作品标题", "作品链接",
]
CLAIM_HEADERS = [
    "claim_id", "判断主题", "判断", "状态", "评论接收等级", "支持video_ids", "支持evidence_ids",
    "关键证据摘要", "反例", "替代解释", "可用范围", "不可用范围", "下一步验证",
]

ROLE_LABELS = {"pinned": "置顶", "recent_non_pinned": "近期非置顶"}
PERFORMANCE_LABELS = {
    "high": "高", "normal": "常态", "low": "低", "outlier": "异常", "unknown": "未知",
}
ALIGNMENT_LABELS = {
    "high": "高", "partial": "部分", "split": "分裂", "low": "低", "unknown": "未知",
    "not_applicable": "不适用",
}
COMPLETENESS_LABELS = {"complete": "完整", "partial": "部分", "unknown": "未知"}
SOURCE_ROLE_LABELS = {
    "top_level": "一级观众评论", "viewer_reply": "观众回复", "creator_reply": "达人回复",
}


class D1BuildError(RuntimeError):
    """Raised when a D1 workbook cannot be built safely."""


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--delivery", required=True, help="Analysis delivery directory")
    value.add_argument("--dry-run", action="store_true", help="Validate inputs and print the plan")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise D1BuildError(f"Cannot read JSON: {path}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise D1BuildError(f"Cannot read JSONL: {path}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise D1BuildError(f"Invalid JSONL in {path.name} line {line_number}") from exc
        if not isinstance(row, dict):
            raise D1BuildError(f"{path.name} line {line_number} must be a JSON object")
        rows.append(row)
    return rows


def q(name: str) -> str:
    return f"{{{MAIN_NS}}}{name}"


def column_number(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - 64
    return value


def column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def row_for(sheet_data: ET.Element, row_number: int) -> ET.Element:
    for row in sheet_data.findall(q("row")):
        if int(row.attrib.get("r", "0")) == row_number:
            return row
    row = ET.Element(q("row"), {"r": str(row_number)})
    inserted = False
    for index, current in enumerate(sheet_data.findall(q("row"))):
        if int(current.attrib.get("r", "0")) > row_number:
            sheet_data.insert(index, row)
            inserted = True
            break
    if not inserted:
        sheet_data.append(row)
    return row


def cell_for(sheet_data: ET.Element, reference: str) -> ET.Element:
    row_number = int(re.search(r"(\d+)$", reference).group(1))
    row = row_for(sheet_data, row_number)
    for cell in row.findall(q("c")):
        if cell.attrib.get("r") == reference:
            return cell
    cell = ET.Element(q("c"), {"r": reference})
    target_column = column_number(reference)
    inserted = False
    for index, current in enumerate(row.findall(q("c"))):
        if column_number(current.attrib.get("r", "")) > target_column:
            row.insert(index, cell)
            inserted = True
            break
    if not inserted:
        row.append(cell)
    return cell


def clear_cell(cell: ET.Element) -> None:
    for child in list(cell):
        if child.tag in {q("v"), q("f"), q("is")}:
            cell.remove(child)
    cell.attrib.pop("t", None)


def set_cell(sheet_data: ET.Element, reference: str, value: Any) -> None:
    cell = cell_for(sheet_data, reference)
    clear_cell(cell)
    if value in (None, ""):
        return
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        cell.attrib["t"] = "n"
        ET.SubElement(cell, q("v")).text = str(value)
        return
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, q("is"))
    text = ET.SubElement(inline, q("t"))
    rendered = str(value)
    if rendered[:1].isspace() or rendered[-1:].isspace() or "\n" in rendered:
        text.attrib[f"{{{XML_NS}}}space"] = "preserve"
    text.text = rendered


def write_row(sheet_data: ET.Element, row_number: int, values: Iterable[Any]) -> None:
    for column, value in enumerate(values, 1):
        set_cell(sheet_data, f"{column_name(column)}{row_number}", value)


def clear_data_rows(sheet_data: ET.Element, first_row: int, last_row: int, last_column: int) -> None:
    for row in sheet_data.findall(q("row")):
        row_number = int(row.attrib.get("r", "0"))
        if not first_row <= row_number <= last_row:
            continue
        for cell in row.findall(q("c")):
            if column_number(cell.attrib.get("r", "")) <= last_column:
                clear_cell(cell)


def sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relation_map = {
        node.attrib.get("Id", ""): node.attrib.get("Target", "")
        for node in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    paths: dict[str, str] = {}
    for node in workbook.iter(q("sheet")):
        relation_id = node.attrib.get(f"{{{REL_NS}}}id", "")
        target = relation_map.get(relation_id, "").lstrip("/")
        if target and not target.startswith("xl/"):
            target = f"xl/{target}"
        paths[node.attrib.get("name", "")] = target
    return paths


def display_id(prefix: str, value: Any) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        return ""
    return rendered if rendered.startswith(prefix) else f"{prefix}{rendered}"


def as_int(value: Any) -> int:
    try:
        return max(0, int(float(str(value or 0).replace(",", ""))))
    except (TypeError, ValueError):
        return 0


def joined(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def capacity_check(videos: list[dict[str, Any]], evidence: list[dict[str, Any]], claims: list[dict[str, Any]]) -> None:
    capacities = {
        "video_analysis.jsonl": SHEET_SPECS["作品与对齐"][2] - 5,
        "evidence_ledger.jsonl": SHEET_SPECS["评论语义证据"][2] - 5,
        "claim_cards.jsonl": SHEET_SPECS["结论证据卡"][2] - 5,
    }
    for label, rows in (
        ("video_analysis.jsonl", videos),
        ("evidence_ledger.jsonl", evidence),
        ("claim_cards.jsonl", claims),
    ):
        if len(rows) > capacities[label]:
            raise D1BuildError(f"{label} has {len(rows)} rows; workbook capacity is {capacities[label]}")


def build_payload(root: Path) -> dict[str, Any]:
    data = root / "data"
    required = {
        "analysis_manifest": data / "analysis_manifest.json",
        "works": data / "works_sample.json",
        "delivery": data / "delivery_manifest.json",
        "videos": data / "video_analysis.jsonl",
        "evidence": data / "evidence_ledger.jsonl",
        "claims": data / "claim_cards.jsonl",
    }
    missing = [path.name for path in required.values() if not path.is_file()]
    if missing:
        raise D1BuildError(f"Missing analysis data: {', '.join(missing)}")
    payload = {
        "analysis_manifest": read_json(required["analysis_manifest"]),
        "works_payload": read_json(required["works"]),
        "delivery": read_json(required["delivery"]),
        "videos": read_jsonl(required["videos"]),
        "evidence": read_jsonl(required["evidence"]),
        "claims": read_jsonl(required["claims"]),
    }
    works = payload["works_payload"].get("works") if isinstance(payload["works_payload"], dict) else None
    if not isinstance(works, list):
        raise D1BuildError("works_sample.json must contain a works array")
    if not isinstance(payload["delivery"], dict) or payload["delivery"].get("analysis_status") == "draft":
        raise D1BuildError("delivery_manifest analysis_status must be complete, partial, or insufficient")
    payload["works"] = [row for row in works if isinstance(row, dict)]
    capacity_check(payload["videos"], payload["evidence"], payload["claims"])
    return payload


def build_sheet_matrices(payload: dict[str, Any]) -> dict[str, list[list[Any]]]:
    works = payload["works"]
    videos = payload["videos"]
    evidence = payload["evidence"]
    claims = payload["claims"]
    delivery = payload["delivery"]
    analysis_manifest = payload["analysis_manifest"]
    works_by_id = {
        str(row.get("video_id") or row.get("aweme_id") or ""): row
        for row in works
    }
    sample_counts = analysis_manifest.get("sample_counts", {}) if isinstance(analysis_manifest, dict) else {}
    selected_total = as_int(sample_counts.get("selected_total")) or len(works)
    pinned_count = as_int(sample_counts.get("pinned")) or sum(
        1 for row in works if row.get("sample_role") == "pinned"
    )
    recent_count = as_int(sample_counts.get("recent_non_pinned")) or sum(
        1 for row in works if row.get("sample_role") == "recent_non_pinned"
    )
    status_counts = Counter(str(row.get("evidence_status") or "") for row in claims)
    reply_count = sum(1 for row in evidence if row.get("source_role") != "top_level")

    reading = [
        ["BrandBAI D1 评论语义证据包"] * 8,
        ["账号名称", delivery.get("account_name", ""), "分析状态", delivery.get("analysis_status", ""),
         "分析模式", delivery.get("analysis_mode", "lightweight_no_asr"), "分析时间", delivery.get("analysis_time", "")],
        ["样本概览", "数值", "口径", "说明", "状态计数", "数值", "编码", "定义"],
        ["纳入作品", selected_total, "全部置顶＋最近最多30条非置顶", "来自 works_sample.json", "F 事实", status_counts["F"], "C/P/R/V/B/E/A", "评论主语义，只能单选"],
        ["置顶作品", pinned_count, "当前可见置顶全部纳入", "置顶不占30条名额", "P 模式", status_counts["P"], "S0—S6", "接收深度，不是购买漏斗"],
        ["近期非置顶", recent_count, "用于建立近期基线", "最多30条", "H 假设", status_counts["H"], "高/部分/分裂/低/未知", "内容—评论对齐等级"],
        ["重点观察作品", len(videos), "全部置顶＋最多10条非置顶", "见作品与对齐页", "U 未知", status_counts["U"], "cover_metadata", "不代表看完完整视频"],
        ["编码评论", len(evidence), "单作品一级评论最多200条", "不外推完整粉丝比例", "回复", reply_count, "source_role", "一级评论、观众回复和达人回复分开"],
        ["重要边界：本包默认为轻量无转写分析；封面和标题不等于完整视频。互动高不等于主旨被接收；求链接、自报购买或体验不等于成交。DYV-/DYC- 仅用于避免 Excel 科学计数法，数字主体仍为平台 ID。"] * 8,
    ]

    works_rows: list[list[Any]] = []
    for row in videos:
        video_id = str(row.get("video_id") or "")
        work = works_by_id.get(video_id, {})
        works_rows.append([
            display_id("DYV-", video_id), ROLE_LABELS.get(str(row.get("sample_role")), str(row.get("sample_role") or "")),
            work.get("title", ""), work.get("publish_time") or work.get("create_time") or "",
            row.get("observation_level", ""), PERFORMANCE_LABELS.get(str(row.get("performance_level")), str(row.get("performance_level") or "")),
            row.get("user_task", ""), row.get("opening", ""),
            f"{row.get('key_action', '')}\n视觉锚点：{row.get('visual_anchor', '')}", row.get("video_message", ""),
            row.get("comment_reception_center", ""), ALIGNMENT_LABELS.get(str(row.get("alignment_level")), str(row.get("alignment_level") or "")),
            row.get("attention_owner", ""), row.get("commercial_memory", ""), row.get("mechanism_candidate", ""),
            row.get("counterexample", ""), joined(row.get("alternative_explanations")),
            COMPLETENESS_LABELS.get(str(row.get("completeness")), str(row.get("completeness") or "")),
            row.get("source_url") or work.get("source_url", ""),
        ])

    evidence_rows: list[list[Any]] = []
    for row in evidence:
        video_id = str(row.get("video_id") or "")
        work = works_by_id.get(video_id, {})
        evidence_rows.append([
            row.get("evidence_id", ""), display_id("DYV-", video_id), display_id("DYC-", row.get("comment_id")),
            SOURCE_ROLE_LABELS.get(str(row.get("source_role")), str(row.get("source_role") or "")), row.get("comment_text", ""),
            as_int(row.get("digg_count")), as_int(row.get("reply_count")), row.get("comment_time", ""),
            display_id("DYC-", row.get("parent_id")), row.get("source_file", ""), as_int(row.get("source_row")),
            COMPLETENESS_LABELS.get(str(row.get("completeness")), str(row.get("completeness") or "")),
            row.get("main_semantic", ""), joined(row.get("auxiliary_tags")), row.get("reception_depth", ""),
            "来自 evidence_ledger.jsonl；按互斥主语义编码", work.get("title", ""), work.get("source_url", ""),
        ])

    claim_rows: list[list[Any]] = []
    for row in claims:
        claim_rows.append([
            row.get("claim_id", ""), row.get("topic", ""), row.get("claim", ""), row.get("evidence_status", ""),
            ALIGNMENT_LABELS.get(str(row.get("reception_level")), str(row.get("reception_level") or "")),
            "；".join(display_id("DYV-", value) for value in row.get("supporting_video_ids", [])),
            joined(row.get("supporting_evidence_ids")), row.get("evidence_summary", ""), row.get("counterevidence", ""),
            joined(row.get("alternative_explanations")), row.get("usable_scope", ""), row.get("prohibited_scope", ""),
            row.get("validation_next", ""),
        ])
    return {"reading": reading, "works": works_rows, "evidence": evidence_rows, "claims": claim_rows}


def update_workbook(workbook_path: Path, payload: dict[str, Any]) -> None:
    matrices = build_sheet_matrices(payload)
    try:
        with zipfile.ZipFile(workbook_path) as archive:
            names = set(archive.namelist())
            paths = sheet_paths(archive)
            missing = [name for name in SHEET_SPECS if name not in paths or paths[name] not in names]
            if missing:
                raise D1BuildError(f"Workbook is missing required sheets: {', '.join(missing)}")
            replacements: dict[str, bytes] = {}
            sheets = {name: ET.fromstring(archive.read(paths[name])) for name in SHEET_SPECS}

            reading_data = sheets["阅读说明"].find(q("sheetData"))
            works_data = sheets["作品与对齐"].find(q("sheetData"))
            evidence_data = sheets["评论语义证据"].find(q("sheetData"))
            claims_data = sheets["结论证据卡"].find(q("sheetData"))
            if any(value is None for value in (reading_data, works_data, evidence_data, claims_data)):
                raise D1BuildError("Workbook sheetData is missing")

            write_row(reading_data, 1, matrices["reading"][0])
            write_row(reading_data, 3, matrices["reading"][1])
            write_row(reading_data, 5, matrices["reading"][2])
            for offset, values in enumerate(matrices["reading"][3:8], 6):
                write_row(reading_data, offset, values)
            write_row(reading_data, 12, matrices["reading"][8])

            clear_data_rows(works_data, 6, SHEET_SPECS["作品与对齐"][2], 19)
            write_row(works_data, 1, ["作品样本与内容—评论语义对齐"] * 19)
            write_row(works_data, 3, ["每行一条重点观察作品。默认无音频转写；只写当前观察层级能确认的内容。"] * 19)
            write_row(works_data, 5, WORK_HEADERS)
            for row_number, values in enumerate(matrices["works"], 6):
                write_row(works_data, row_number, values)

            clear_data_rows(evidence_data, 6, SHEET_SPECS["评论语义证据"][2], 18)
            write_row(evidence_data, 1, ["评论语义证据账本"] * 18)
            write_row(evidence_data, 3, ["每条评论只设置一个 C/P/R/V/B/E/A 主语义；S0—S6 只描述接收深度。"] * 18)
            write_row(evidence_data, 5, COMMENT_HEADERS)
            for row_number, values in enumerate(matrices["evidence"], 6):
                write_row(evidence_data, row_number, values)

            clear_data_rows(claims_data, 6, SHEET_SPECS["结论证据卡"][2], 13)
            write_row(claims_data, 1, ["结论证据卡"] * 13)
            write_row(claims_data, 3, ["重要判断必须包含状态、支持证据、反例、替代解释和使用边界。"] * 13)
            write_row(claims_data, 5, CLAIM_HEADERS)
            for row_number, values in enumerate(matrices["claims"], 6):
                write_row(claims_data, row_number, values)

            for name, root in sheets.items():
                replacements[paths[name]] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

            archive_infos = archive.infolist()
            archive_entries = {
                info.filename: archive.read(info.filename)
                for info in archive_infos
            }

        handle, temp_name = tempfile.mkstemp(prefix="d1-", suffix=".xlsx", dir=workbook_path.parent)
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as output:
                for info in archive_infos:
                    output.writestr(info, replacements.get(info.filename, archive_entries[info.filename]))
            with zipfile.ZipFile(temp_path) as output:
                bad = output.testzip()
                if bad:
                    raise D1BuildError(f"Generated workbook failed CRC validation: {bad}")
            temp_path.replace(workbook_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise D1BuildError(f"Cannot update workbook: {workbook_path}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.delivery).expanduser().resolve()
    workbook_path = root / "02_D1评论语义证据包.xlsx"
    try:
        if not root.is_dir():
            raise D1BuildError(f"Delivery directory does not exist: {root}")
        if not workbook_path.is_file():
            raise D1BuildError("Run init_analysis_delivery.py first; D1 workbook template is missing")
        payload = build_payload(root)
        plan = {
            "status": "ready_to_build" if args.dry_run else "built",
            "workbook": str(workbook_path),
            "counts": {
                "sample_works": len(payload["works"]),
                "deep_review_works": len(payload["videos"]),
                "evidence_rows": len(payload["evidence"]),
                "claim_cards": len(payload["claims"]),
            },
        }
        if not args.dry_run:
            update_workbook(workbook_path, payload)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except D1BuildError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
