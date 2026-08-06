#!/usr/bin/env python3
"""Validate a completed BrandBAI Douyin account-analysis delivery."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ORDINARY_FILES = (
    "01_账号深度分析.md",
    "02_D1评论语义证据包.xlsx",
    "03_分析说明与资料缺口.md",
)
INTERNAL_FILES = (
    "data/analysis_manifest.json",
    "data/works_sample.json",
    "data/comment_inventory.json",
    "data/delivery_manifest.json",
    "data/video_analysis.jsonl",
    "data/evidence_ledger.jsonl",
    "data/claim_cards.jsonl",
)
REQUIRED_SHEETS = ("阅读说明", "作品与对齐", "评论语义证据", "结论证据卡")

VIDEO_REQUIRED = {
    "video_id", "sample_role", "observation_level", "observed_sources",
    "performance_level", "comparison_group", "user_task",
    "opening", "key_action", "visual_anchor", "video_message", "comment_reception_center",
    "alignment_level", "attention_owner", "commercial_memory", "mechanism_candidate",
    "counterexample", "alternative_explanations", "completeness", "source_url",
}
EVIDENCE_REQUIRED = {
    "evidence_id", "video_id", "comment_id", "source_role", "comment_text", "digg_count",
    "reply_count", "comment_time", "parent_id", "source_file", "source_row", "completeness",
    "main_semantic", "auxiliary_tags", "reception_depth",
}
CLAIM_REQUIRED = {
    "claim_id", "topic", "claim", "evidence_status", "reception_level",
    "supporting_video_ids", "supporting_evidence_ids", "evidence_summary", "counterevidence",
    "alternative_explanations", "usable_scope", "prohibited_scope", "validation_next",
}

ALLOWED = {
    "analysis_status": {"complete", "partial", "insufficient"},
    "analysis_mode": {"lightweight_no_asr", "enhanced_media"},
    "sample_role": {"pinned", "recent_non_pinned"},
    "observation_level": {"cover_metadata", "sampled_frames", "direct_media", "text_only"},
    "performance_level": {"high", "normal", "low", "outlier", "unknown"},
    "alignment_level": {"high", "partial", "split", "low", "unknown"},
    "completeness": {"complete", "partial", "unknown"},
    "source_role": {"top_level", "viewer_reply", "creator_reply"},
    "main_semantic": {"C", "P", "R", "V", "B", "E", "A"},
    "reception_depth": {f"S{value}" for value in range(7)},
    "evidence_status": {"F", "P", "H", "U"},
    "reception_level": {"high", "partial", "split", "low", "unknown", "not_applicable"},
}

REPORT_HEADINGS = (
    "## 一、结论先看",
    "## 二、样本与数据边界",
    "## 三、账号近期基线",
    "## 四、置顶作品代表什么",
    "## 五、用户真正接收了什么",
    "## 六、代表作品的视频—评论对齐",
    "## 七、高表现候选机制与失效条件",
    "## 八、一般商业承载与信任边界",
    "## 九、仍未知什么",
)
NOTES_HEADINGS = (
    "## 一、本次分析范围",
    "## 二、输入完成状态",
    "## 三、分析完成状态",
    "## 四、资料缺口",
    "## 五、口径说明",
    "## 六、建议补充",
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--delivery", required=True, help="Completed analysis delivery directory")
    return value


def read_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot read JSON {path.name}: {exc}")
        return None


def read_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        errors.append(f"Cannot read JSONL {path.name}: {exc}")
        return rows
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name} line {line_number} is invalid JSON: {exc.msg}")
            continue
        if not isinstance(row, dict):
            errors.append(f"{path.name} line {line_number} must be an object")
            continue
        rows.append(row)
    return rows


def require_fields(rows: list[dict[str, Any]], required: set[str], label: str, errors: list[str]) -> None:
    for index, row in enumerate(rows, 1):
        missing = sorted(required - row.keys())
        if missing:
            errors.append(f"{label} row {index} is missing fields: {', '.join(missing)}")


def unique_values(rows: list[dict[str, Any]], key: str, label: str, errors: list[str]) -> set[str]:
    values: list[str] = []
    for index, row in enumerate(rows, 1):
        value = str(row.get(key) or "").strip()
        if not value:
            errors.append(f"{label} row {index} has an empty {key}")
        else:
            values.append(value)
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        errors.append(f"{label} has duplicate {key}: {', '.join(duplicates)}")
    return set(values)


def check_enum(rows: list[dict[str, Any]], field: str, label: str, errors: list[str]) -> None:
    allowed = ALLOWED[field]
    for index, row in enumerate(rows, 1):
        value = row.get(field)
        if value not in allowed:
            errors.append(f"{label} row {index} has invalid {field}: {value!r}")


def check_list_fields(rows: list[dict[str, Any]], fields: tuple[str, ...], label: str, errors: list[str]) -> None:
    for index, row in enumerate(rows, 1):
        for field in fields:
            if not isinstance(row.get(field), list):
                errors.append(f"{label} row {index} field {field} must be a JSON array")


def validate_markdown(path: Path, headings: tuple[str, ...], minimum: int, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        errors.append(f"Cannot read {path.name}: {exc}")
        return
    if len(text.strip()) < minimum:
        errors.append(f"{path.name} is too short to be a completed delivery")
    if "{{" in text or "}}" in text:
        errors.append(f"{path.name} still contains template placeholders")
    for heading in headings:
        if heading not in text:
            errors.append(f"{path.name} is missing heading: {heading}")


def workbook_rows(path: Path, errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
            if not required <= names:
                errors.append(f"{path.name} is not a readable XLSX workbook")
                return counts
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rel_map = {
                node.attrib.get("Id", ""): node.attrib.get("Target", "")
                for node in relationships
            }
            relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            sheet_paths: dict[str, str] = {}
            for node in workbook.iter():
                if not node.tag.endswith("}sheet"):
                    continue
                sheet_name = node.attrib.get("name", "")
                relation_id = node.attrib.get(f"{{{relationship_ns}}}id", "")
                target = rel_map.get(relation_id, "").lstrip("/")
                if target and not target.startswith("xl/"):
                    target = f"xl/{target}"
                sheet_paths[sheet_name] = target
            missing_sheets = [name for name in REQUIRED_SHEETS if name not in sheet_paths]
            if missing_sheets:
                errors.append(f"{path.name} is missing sheets: {', '.join(missing_sheets)}")
            xml_text = "".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names if name.endswith(".xml")
            )
            if "{{" in xml_text or "}}" in xml_text:
                errors.append(f"{path.name} still contains template placeholders")
            if re.search(r"#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A", xml_text):
                errors.append(f"{path.name} contains a spreadsheet error value")
            for sheet_name in REQUIRED_SHEETS:
                target = sheet_paths.get(sheet_name, "")
                if not target or target not in names:
                    continue
                sheet = ET.fromstring(archive.read(target))
                data_rows = 0
                for row in sheet.iter():
                    if not row.tag.endswith("}row") or int(row.attrib.get("r", "0") or 0) < 6:
                        continue
                    has_value = False
                    for cell in row:
                        if not cell.tag.endswith("}c"):
                            continue
                        for child in cell.iter():
                            if child.tag.endswith(("}v", "}t")) and child.text not in (None, ""):
                                has_value = True
                                break
                        if has_value:
                            break
                    if has_value:
                        data_rows += 1
                counts[sheet_name] = data_rows
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        errors.append(f"Cannot validate workbook {path.name}: {exc}")
    return counts


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.delivery).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        print(json.dumps({"status": "invalid", "errors": ["Delivery directory does not exist"]}))
        return 2

    missing = [name for name in (*ORDINARY_FILES, *INTERNAL_FILES) if not (root / name).is_file()]
    if missing:
        errors.append(f"Missing required files: {', '.join(missing)}")
        print(json.dumps({"status": "invalid", "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    delivery_manifest = read_json(root / "data/delivery_manifest.json", errors) or {}
    works_payload = read_json(root / "data/works_sample.json", errors) or {}
    video_rows = read_jsonl(root / "data/video_analysis.jsonl", errors)
    evidence_rows = read_jsonl(root / "data/evidence_ledger.jsonl", errors)
    claim_rows = read_jsonl(root / "data/claim_cards.jsonl", errors)

    require_fields(video_rows, VIDEO_REQUIRED, "video_analysis", errors)
    require_fields(evidence_rows, EVIDENCE_REQUIRED, "evidence_ledger", errors)
    require_fields(claim_rows, CLAIM_REQUIRED, "claim_cards", errors)
    video_ids = unique_values(video_rows, "video_id", "video_analysis", errors)
    evidence_ids = unique_values(evidence_rows, "evidence_id", "evidence_ledger", errors)
    unique_values(claim_rows, "claim_id", "claim_cards", errors)

    for field in ("sample_role", "observation_level", "performance_level", "alignment_level", "completeness"):
        check_enum(video_rows, field, "video_analysis", errors)
    for field in ("source_role", "completeness", "main_semantic", "reception_depth"):
        check_enum(evidence_rows, field, "evidence_ledger", errors)
    for field in ("evidence_status", "reception_level"):
        check_enum(claim_rows, field, "claim_cards", errors)
    check_list_fields(video_rows, ("observed_sources", "alternative_explanations"), "video_analysis", errors)
    check_list_fields(evidence_rows, ("auxiliary_tags",), "evidence_ledger", errors)
    check_list_fields(
        claim_rows,
        ("supporting_video_ids", "supporting_evidence_ids", "alternative_explanations"),
        "claim_cards",
        errors,
    )

    status = delivery_manifest.get("analysis_status")
    if status not in ALLOWED["analysis_status"]:
        errors.append(f"delivery_manifest has invalid analysis_status: {status!r}")
    analysis_mode = delivery_manifest.get("analysis_mode")
    if analysis_mode not in ALLOWED["analysis_mode"]:
        errors.append(f"delivery_manifest has invalid analysis_mode: {analysis_mode!r}")
    deep_review_ids = delivery_manifest.get("deep_review_video_ids")
    if not isinstance(deep_review_ids, list):
        errors.append("delivery_manifest deep_review_video_ids must be a JSON array")
        deep_review_ids = []
    declared_ids = {str(value) for value in deep_review_ids if str(value)}
    if declared_ids != video_ids:
        errors.append("delivery_manifest deep_review_video_ids must exactly match video_analysis rows")
    limitations = delivery_manifest.get("limitations")
    if not isinstance(limitations, list):
        errors.append("delivery_manifest limitations must be a JSON array")
    elif status == "partial" and not limitations:
        errors.append("A partial analysis must list at least one limitation")

    works = works_payload.get("works") if isinstance(works_payload, dict) else None
    if not isinstance(works, list):
        errors.append("works_sample.json must contain a works array")
        works = []
    sample_ids = {str(row.get("video_id") or row.get("aweme_id") or "") for row in works if isinstance(row, dict)}
    pinned_ids = {
        str(row.get("video_id") or row.get("aweme_id") or "")
        for row in works if isinstance(row, dict) and row.get("sample_role") == "pinned"
    }
    if not video_ids <= sample_ids:
        errors.append("video_analysis contains video IDs outside works_sample.json")
    missing_pinned = sorted(pinned_ids - video_ids)
    if missing_pinned:
        errors.append(f"All pinned works require a video analysis card: {', '.join(missing_pinned)}")
    recent_reviewed = [row for row in video_rows if row.get("sample_role") == "recent_non_pinned"]
    if len(recent_reviewed) > 10:
        errors.append("More than 10 non-pinned works were selected for deep review")

    top_level_counts: Counter[str] = Counter()
    for index, row in enumerate(evidence_rows, 1):
        if str(row.get("video_id") or "") not in video_ids:
            errors.append(f"evidence_ledger row {index} references a work that was not deep-reviewed")
        if row.get("source_role") == "top_level":
            top_level_counts[str(row.get("video_id") or "")] += 1
        for numeric in ("digg_count", "reply_count", "source_row"):
            if not isinstance(row.get(numeric), int) or row.get(numeric, 0) < 0:
                errors.append(f"evidence_ledger row {index} field {numeric} must be a non-negative integer")
    over_limit = sorted(video_id for video_id, count in top_level_counts.items() if count > 200)
    if over_limit:
        errors.append(f"More than 200 top-level comments were encoded for: {', '.join(over_limit)}")

    for index, row in enumerate(claim_rows, 1):
        supporting_videos = row.get("supporting_video_ids") if isinstance(row.get("supporting_video_ids"), list) else []
        supporting_evidence = row.get("supporting_evidence_ids") if isinstance(row.get("supporting_evidence_ids"), list) else []
        if not set(map(str, supporting_videos)) <= video_ids:
            errors.append(f"claim_cards row {index} references an unknown supporting video")
        if not set(map(str, supporting_evidence)) <= evidence_ids:
            errors.append(f"claim_cards row {index} references an unknown evidence ID")
        if row.get("evidence_status") == "P":
            if len(set(map(str, supporting_videos))) < 2:
                errors.append(f"claim_cards row {index} marks P without at least two supporting videos")
            if not supporting_evidence:
                errors.append(f"claim_cards row {index} marks P without comment evidence")

    if not claim_rows:
        errors.append("At least one claim card is required, including for an insufficient analysis")
    if status == "complete":
        if not video_rows:
            errors.append("A complete analysis must include deep-reviewed works")
        if any(row.get("completeness") != "complete" for row in video_rows):
            errors.append("A complete analysis cannot contain partial or unknown video cards")
        if any(row.get("observation_level") == "text_only" for row in video_rows):
            errors.append("A complete analysis requires visual evidence for every deep-reviewed work")
        if not evidence_rows:
            errors.append("A complete analysis must include encoded comment evidence")

    validate_markdown(root / "01_账号深度分析.md", REPORT_HEADINGS, 800, errors)
    validate_markdown(root / "03_分析说明与资料缺口.md", NOTES_HEADINGS, 400, errors)
    rows_by_sheet = workbook_rows(root / "02_D1评论语义证据包.xlsx", errors)
    expected_rows = {
        "作品与对齐": len(video_rows),
        "评论语义证据": len(evidence_rows),
        "结论证据卡": len(claim_rows),
    }
    for sheet_name, expected in expected_rows.items():
        actual = rows_by_sheet.get(sheet_name, 0)
        if actual < expected:
            errors.append(f"Workbook sheet {sheet_name} has {actual} data rows but requires at least {expected}")

    result = {
        "status": "valid" if not errors else "invalid",
        "analysis_status": status,
        "counts": {
            "sample_works": len(works),
            "deep_review_works": len(video_rows),
            "evidence_rows": len(evidence_rows),
            "claim_cards": len(claim_rows),
        },
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
