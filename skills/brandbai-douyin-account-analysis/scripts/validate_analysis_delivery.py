#!/usr/bin/env python3
"""Validate a completed BrandBAI Douyin account-analysis delivery."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from statistics import median
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
    "data/work_classification.jsonl",
    "data/baseline_ledger.jsonl",
    "data/video_analysis.jsonl",
    "data/evidence_ledger.jsonl",
    "data/comment_collection_ledger.jsonl",
    "data/claim_cards.jsonl",
    "data/account_assets.jsonl",
    "data/creation_space.jsonl",
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
CLASSIFICATION_REQUIRED = {
    "video_id", "content_task", "content_type", "commercial_status", "account_window",
    "comparison_group", "classification_status", "excluded_reason",
}
BASELINE_REQUIRED = {
    "baseline_id", "comparison_group", "content_task", "content_type", "commercial_status",
    "account_window", "video_ids", "sample_size", "comparable_status", "digg_median",
    "comment_median", "collect_median", "share_median", "boundary",
}
COMMENT_COLLECTION_REQUIRED = {
    "video_id", "platform_comment_count", "encoded_top_level_count", "encoded_reply_count",
    "collected_at", "sort_order", "completeness", "activity_pollution", "anomalies",
    "stopping_status", "stopping_reason",
}
ACCOUNT_ASSET_REQUIRED = {
    "asset_id", "asset_type", "statement", "evidence_status", "supporting_video_ids",
    "supporting_evidence_ids", "counterevidence", "alternative_explanations",
    "usable_scope", "prohibited_scope",
}
CREATION_SPACE_REQUIRED = {
    "space_id", "zone", "statement", "evidence_status", "supporting_video_ids",
    "supporting_evidence_ids", "conditions", "counterevidence", "boundary",
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
    "commercial_status": {"natural", "commercial", "activity", "live_preview", "unknown"},
    "classification_status": {"included", "excluded"},
    "comparable_status": {"comparable", "conditional"},
    "stopping_status": {"sufficient", "continue", "blocked"},
    "asset_type": {
        "people_judgment", "content_action", "method_value", "relationship_asset",
        "commercial_boundary",
    },
    "zone": {"stable", "expandable", "episodic", "commercial_high_risk"},
}

REPORT_HEADINGS = (
    "## 一、结论先看",
    "## 二、样本与数据边界",
    "## 三、账号近期基线",
    "## 四、置顶作品代表什么",
    "## 五、五类稳定资产与账号定位",
    "## 六、原生内容语法与创作空间地图",
    "## 七、用户真正接收了什么",
    "## 八、代表作品的视频—评论对齐",
    "## 九、高表现候选机制与失效条件",
    "## 十、一般商业承载与信任边界",
    "## 十一、仍未知什么",
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


def non_negative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def as_count(value: Any) -> int:
    try:
        return max(0, int(float(str(value or 0).replace(",", "").strip())))
    except (TypeError, ValueError):
        return 0


def normalized_median(values: list[int]) -> int | float:
    result = median(values)
    return int(result) if float(result).is_integer() else float(result)


def require_exact_taxonomy(
    rows: list[dict[str, Any]],
    field: str,
    expected: set[str],
    label: str,
    errors: list[str],
) -> None:
    values = [str(row.get(field) or "") for row in rows]
    missing = sorted(expected - set(values))
    unexpected = sorted(set(values) - expected)
    duplicates = sorted(value for value, count in Counter(values).items() if value and count > 1)
    if missing:
        errors.append(f"{label} is missing {field} values: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{label} has unexpected {field} values: {', '.join(unexpected)}")
    if duplicates:
        errors.append(f"{label} has duplicate {field} values: {', '.join(duplicates)}")


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
    classification_rows = read_jsonl(root / "data/work_classification.jsonl", errors)
    baseline_rows = read_jsonl(root / "data/baseline_ledger.jsonl", errors)
    video_rows = read_jsonl(root / "data/video_analysis.jsonl", errors)
    evidence_rows = read_jsonl(root / "data/evidence_ledger.jsonl", errors)
    comment_collection_rows = read_jsonl(root / "data/comment_collection_ledger.jsonl", errors)
    claim_rows = read_jsonl(root / "data/claim_cards.jsonl", errors)
    account_asset_rows = read_jsonl(root / "data/account_assets.jsonl", errors)
    creation_space_rows = read_jsonl(root / "data/creation_space.jsonl", errors)

    require_fields(classification_rows, CLASSIFICATION_REQUIRED, "work_classification", errors)
    require_fields(baseline_rows, BASELINE_REQUIRED, "baseline_ledger", errors)
    require_fields(video_rows, VIDEO_REQUIRED, "video_analysis", errors)
    require_fields(evidence_rows, EVIDENCE_REQUIRED, "evidence_ledger", errors)
    require_fields(
        comment_collection_rows,
        COMMENT_COLLECTION_REQUIRED,
        "comment_collection_ledger",
        errors,
    )
    require_fields(claim_rows, CLAIM_REQUIRED, "claim_cards", errors)
    require_fields(account_asset_rows, ACCOUNT_ASSET_REQUIRED, "account_assets", errors)
    require_fields(creation_space_rows, CREATION_SPACE_REQUIRED, "creation_space", errors)
    classification_ids = unique_values(
        classification_rows, "video_id", "work_classification", errors
    )
    unique_values(baseline_rows, "baseline_id", "baseline_ledger", errors)
    video_ids = unique_values(video_rows, "video_id", "video_analysis", errors)
    evidence_ids = unique_values(evidence_rows, "evidence_id", "evidence_ledger", errors)
    comment_collection_ids = unique_values(
        comment_collection_rows, "video_id", "comment_collection_ledger", errors
    )
    unique_values(claim_rows, "claim_id", "claim_cards", errors)
    unique_values(account_asset_rows, "asset_id", "account_assets", errors)
    unique_values(creation_space_rows, "space_id", "creation_space", errors)

    for field in ("commercial_status", "classification_status"):
        check_enum(classification_rows, field, "work_classification", errors)
    for field in ("commercial_status", "comparable_status"):
        check_enum(baseline_rows, field, "baseline_ledger", errors)
    for field in ("sample_role", "observation_level", "performance_level", "alignment_level", "completeness"):
        check_enum(video_rows, field, "video_analysis", errors)
    for field in ("source_role", "completeness", "main_semantic", "reception_depth"):
        check_enum(evidence_rows, field, "evidence_ledger", errors)
    for field in ("completeness", "stopping_status"):
        check_enum(comment_collection_rows, field, "comment_collection_ledger", errors)
    for field in ("evidence_status", "reception_level"):
        check_enum(claim_rows, field, "claim_cards", errors)
    for field in ("evidence_status", "asset_type"):
        check_enum(account_asset_rows, field, "account_assets", errors)
    for field in ("evidence_status", "zone"):
        check_enum(creation_space_rows, field, "creation_space", errors)
    check_list_fields(baseline_rows, ("video_ids",), "baseline_ledger", errors)
    check_list_fields(video_rows, ("observed_sources", "alternative_explanations"), "video_analysis", errors)
    check_list_fields(evidence_rows, ("auxiliary_tags",), "evidence_ledger", errors)
    check_list_fields(comment_collection_rows, ("anomalies",), "comment_collection_ledger", errors)
    check_list_fields(
        claim_rows,
        ("supporting_video_ids", "supporting_evidence_ids", "alternative_explanations"),
        "claim_cards",
        errors,
    )
    check_list_fields(
        account_asset_rows,
        ("supporting_video_ids", "supporting_evidence_ids", "alternative_explanations"),
        "account_assets",
        errors,
    )
    check_list_fields(
        creation_space_rows,
        ("supporting_video_ids", "supporting_evidence_ids"),
        "creation_space",
        errors,
    )
    require_exact_taxonomy(
        account_asset_rows, "asset_type", ALLOWED["asset_type"], "account_assets", errors
    )
    require_exact_taxonomy(
        creation_space_rows, "zone", ALLOWED["zone"], "creation_space", errors
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
    works_by_id = {
        str(row.get("video_id") or row.get("aweme_id") or ""): row
        for row in works if isinstance(row, dict)
    }
    recent_ids = {
        video_id for video_id, row in works_by_id.items()
        if video_id and row.get("sample_role") == "recent_non_pinned"
    }
    pinned_ids = {
        str(row.get("video_id") or row.get("aweme_id") or "")
        for row in works if isinstance(row, dict) and row.get("sample_role") == "pinned"
    }
    if not video_ids <= sample_ids:
        errors.append("video_analysis contains video IDs outside works_sample.json")
    if classification_ids != recent_ids:
        missing_classification = sorted(recent_ids - classification_ids)
        unknown_classification = sorted(classification_ids - recent_ids)
        if missing_classification:
            errors.append(
                "work_classification does not cover recent non-pinned works: "
                + ", ".join(missing_classification)
            )
        if unknown_classification:
            errors.append(
                "work_classification references works outside the recent non-pinned baseline: "
                + ", ".join(unknown_classification)
            )

    included_ids: set[str] = set()
    classification_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(classification_rows, 1):
        classification_by_id[str(row.get("video_id") or "")] = row
        if row.get("classification_status") == "included":
            included_ids.add(str(row.get("video_id") or ""))
            for field in ("content_task", "content_type", "account_window", "comparison_group"):
                if not str(row.get(field) or "").strip():
                    errors.append(f"work_classification row {index} has empty {field}")
        elif not str(row.get("excluded_reason") or "").strip():
            errors.append(f"work_classification row {index} excludes a work without excluded_reason")

    baseline_video_ids: list[str] = []
    for index, row in enumerate(baseline_rows, 1):
        group_video_ids = [str(value) for value in row.get("video_ids", [])]
        baseline_video_ids.extend(group_video_ids)
        if not group_video_ids:
            errors.append(f"baseline_ledger row {index} has no video_ids")
            continue
        if not set(group_video_ids) <= recent_ids:
            errors.append(f"baseline_ledger row {index} references a non-baseline work")
        for identity_field in (
            "comparison_group", "content_task", "content_type", "commercial_status", "account_window"
        ):
            classified_values = {
                classification_by_id.get(video_id, {}).get(identity_field)
                for video_id in group_video_ids
            }
            if classified_values != {row.get(identity_field)}:
                errors.append(
                    f"baseline_ledger row {index} field {identity_field} does not match work_classification"
                )
        if row.get("sample_size") != len(group_video_ids):
            errors.append(f"baseline_ledger row {index} sample_size does not match video_ids")
        expected_comparable = "comparable" if len(group_video_ids) >= 2 else "conditional"
        if row.get("comparable_status") != expected_comparable:
            errors.append(f"baseline_ledger row {index} has incorrect comparable_status")
        for metric_field, work_field in (
            ("digg_median", "digg_count"),
            ("comment_median", "comment_count"),
            ("collect_median", "collect_count"),
            ("share_median", "share_count"),
        ):
            value = row.get(metric_field)
            if not non_negative_number(value):
                errors.append(f"baseline_ledger row {index} field {metric_field} must be non-negative")
                continue
            expected_value = normalized_median(
                [as_count(works_by_id.get(video_id, {}).get(work_field)) for video_id in group_video_ids]
            )
            if value != expected_value:
                errors.append(
                    f"baseline_ledger row {index} field {metric_field} is not reproducible from works_sample"
                )
    duplicate_baseline_ids = sorted(
        value for value, count in Counter(baseline_video_ids).items() if count > 1
    )
    if duplicate_baseline_ids:
        errors.append(
            "baseline_ledger assigns works to more than one group: "
            + ", ".join(duplicate_baseline_ids)
        )
    if set(baseline_video_ids) != included_ids:
        errors.append("baseline_ledger video_ids must exactly match included classifications")
    missing_pinned = sorted(pinned_ids - video_ids)
    if missing_pinned:
        errors.append(f"All pinned works require a video analysis card: {', '.join(missing_pinned)}")
    recent_reviewed = [row for row in video_rows if row.get("sample_role") == "recent_non_pinned"]
    if len(recent_reviewed) > 10:
        errors.append("More than 10 non-pinned works were selected for deep review")

    top_level_counts: Counter[str] = Counter()
    reply_counts: Counter[str] = Counter()
    for index, row in enumerate(evidence_rows, 1):
        if str(row.get("video_id") or "") not in video_ids:
            errors.append(f"evidence_ledger row {index} references a work that was not deep-reviewed")
        if row.get("source_role") == "top_level":
            top_level_counts[str(row.get("video_id") or "")] += 1
        else:
            reply_counts[str(row.get("video_id") or "")] += 1
        for numeric in ("digg_count", "reply_count", "source_row"):
            if not isinstance(row.get(numeric), int) or row.get(numeric, 0) < 0:
                errors.append(f"evidence_ledger row {index} field {numeric} must be a non-negative integer")
    over_limit = sorted(video_id for video_id, count in top_level_counts.items() if count > 200)
    if over_limit:
        errors.append(f"More than 200 top-level comments were encoded for: {', '.join(over_limit)}")

    if comment_collection_ids != video_ids:
        errors.append("comment_collection_ledger must contain exactly one row per deep-reviewed work")
    for index, row in enumerate(comment_collection_rows, 1):
        video_id = str(row.get("video_id") or "")
        for field in ("platform_comment_count", "encoded_top_level_count", "encoded_reply_count"):
            if not isinstance(row.get(field), int) or row.get(field, 0) < 0:
                errors.append(
                    f"comment_collection_ledger row {index} field {field} must be a non-negative integer"
                )
        if row.get("encoded_top_level_count") != top_level_counts[video_id]:
            errors.append(
                f"comment_collection_ledger row {index} encoded_top_level_count does not match evidence_ledger"
            )
        if row.get("encoded_reply_count") != reply_counts[video_id]:
            errors.append(
                f"comment_collection_ledger row {index} encoded_reply_count does not match evidence_ledger"
            )
        if not str(row.get("stopping_reason") or "").strip():
            errors.append(f"comment_collection_ledger row {index} has empty stopping_reason")

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

    for label, rows in (("account_assets", account_asset_rows), ("creation_space", creation_space_rows)):
        for index, row in enumerate(rows, 1):
            supporting_videos = (
                row.get("supporting_video_ids")
                if isinstance(row.get("supporting_video_ids"), list) else []
            )
            supporting_evidence = (
                row.get("supporting_evidence_ids")
                if isinstance(row.get("supporting_evidence_ids"), list) else []
            )
            if not set(map(str, supporting_videos)) <= video_ids:
                errors.append(f"{label} row {index} references an unknown supporting video")
            if not set(map(str, supporting_evidence)) <= evidence_ids:
                errors.append(f"{label} row {index} references an unknown evidence ID")
            if row.get("evidence_status") == "P":
                if len(set(map(str, supporting_videos))) < 2:
                    errors.append(f"{label} row {index} marks P without at least two supporting videos")
                if not supporting_evidence:
                    errors.append(f"{label} row {index} marks P without comment evidence")
            if row.get("evidence_status") in {"F", "P", "H"} and not str(row.get("statement") or "").strip():
                errors.append(f"{label} row {index} has an empty statement")

    if not claim_rows:
        errors.append("At least one claim card is required, including for an insufficient analysis")
    if status == "complete":
        if not baseline_rows:
            errors.append("A complete analysis must include at least one classified-median baseline")
        if not video_rows:
            errors.append("A complete analysis must include deep-reviewed works")
        if any(row.get("completeness") != "complete" for row in video_rows):
            errors.append("A complete analysis cannot contain partial or unknown video cards")
        if any(row.get("observation_level") == "text_only" for row in video_rows):
            errors.append("A complete analysis requires visual evidence for every deep-reviewed work")
        if not evidence_rows:
            errors.append("A complete analysis must include encoded comment evidence")
        if any(row.get("stopping_status") != "sufficient" for row in comment_collection_rows):
            errors.append("A complete analysis requires sufficient comment stopping status for every deep-reviewed work")

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
            "classified_recent_works": len(classification_rows),
            "baseline_groups": len(baseline_rows),
            "deep_review_works": len(video_rows),
            "evidence_rows": len(evidence_rows),
            "comment_collection_rows": len(comment_collection_rows),
            "claim_cards": len(claim_rows),
            "account_assets": len(account_asset_rows),
            "creation_space_zones": len(creation_space_rows),
        },
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
