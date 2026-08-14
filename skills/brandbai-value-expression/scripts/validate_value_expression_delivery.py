"""Validate a BrandBAI Value Expression delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_value_expression_report import build_report_01, build_report_02
from value_expression_common import (
    ACTIVE_VALUE_LAYERS,
    ANALYSIS_STATUSES,
    ASSET_GROUPS,
    CONTENT_OBJECTS,
    DECISION_TASKS,
    DELIVERY_STATUSES,
    EXPRESSION_ORIGINS,
    EXPRESSION_SOURCE_FORMS,
    EXPRESSION_STATUSES,
    ROUTES,
    ROUTE_ROLES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    SLOT_STATUSES,
    TEST_STATUSES,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    VIS_STATUSES,
    delivery_paths,
    read_json,
    read_jsonl,
    value_expression_id,
)


MANIFEST_FIELDS = {
    "schema_version", "skill_version", "value_expression_id", "product_value_id",
    "brand", "product", "category", "sku", "upstream_output_version",
    "output_version", "source_materials", "analysis_status", "delivery_status",
    "limitations", "created_at", "updated_at",
}
UPSTREAM_FIELDS = {
    "product_value_id", "upstream_output_version", "upstream_updated_at",
    "upstream_analysis_status", "upstream_delivery_status", "decision_id",
    "p0_status", "recommended_value_id", "source_delivery_name",
    "source_materials_name", "values", "fact_ids", "facts", "expression_ids",
    "anchor_ids", "file_hashes", "captured_at",
}
EXISTING_FIELDS = {
    "expression_id", "expression_origin", "source_form", "value_ids", "fact_ids",
    "source_statement", "source_id", "locator", "page_says", "page_shows",
    "current_perception", "reusable", "gap", "status", "boundary",
}
PATH_FIELDS = {
    "scan_id", "value_id", "route", "role", "translation", "reason",
    "fact_ids", "expression_ids", "boundary",
}
SLOT_FIELDS = {
    "slot_id", "slot_number", "asset_group", "slot_name", "status",
    "reason", "vis_ids",
}
VIS_FIELDS = {
    "vis_id", "value_id", "secondary_value_ids", "asset_group", "slot_number",
    "user_question", "target_perception", "decision_task", "primary_route",
    "supporting_routes", "fact_ids", "expression_ids", "human_language",
    "visual_track", "action_track", "sound_track", "subtitle_track",
    "prop_track", "scene_track", "effect_bgm_track", "commerce_handoff_track",
    "must_keep", "variable_parts", "misuse", "applicable_objects",
    "must_preserve_tracks", "adaptable_tracks", "validation_status", "boundary",
    "external_priority",
}
VALIDATION_FIELDS = {
    "test_id", "vis_ids", "validation_task", "must_keep", "single_variable",
    "control_version", "test_version", "primary_metrics", "measurement_method",
    "decision_rule", "writeback", "status", "requirements", "boundary",
}
GAP_FIELDS = {"gap_id", "category", "missing", "impact", "minimum_needed", "priority", "state"}
TRACK_FIELDS = (
    "visual_track", "action_track", "sound_track", "subtitle_track", "prop_track",
    "scene_track", "effect_bgm_track", "commerce_handoff_track",
)
SLOT_GROUPS = {
    "01": "欲望建立", "02": "欲望建立", "03": "欲望建立", "04": "欲望建立",
    "05": "欲望建立", "06": "欲望建立", "07": "欲望建立", "08": "欲望建立",
    "09": "阻力解除", "10": "阻力解除", "11": "阻力解除", "12": "氛围连接",
}

EXACT_FIELD_PATTERNS = (
    re.compile(r"(?:GB\s*/\s*T|GB|ISO|FSSC)\s*-?\s*\d[0-9A-Za-z./-]*", re.IGNORECASE),
    re.compile(r"CNAS(?:[0-9A-Za-z./-]+)?", re.IGNORECASE),
    re.compile(r"(?:单位|限值|报告编号|签发日期|检测方法(?:标准)?)[：:\s]*[0-9A-Za-z.μµ/%°℃_-]+", re.IGNORECASE),
)
ORIGINAL_ASSET_RE = re.compile(r"(?:报告|证书|检测单|文件)原件|原始报告|原件报告")
SINGLE_PACK_CLAIM_RE = re.compile(
    r"(?:(?:一包|单包|一袋|单袋).{0,24}(?:全部|同时|五味|多种|内容物)|"
    r"(?:全部|同时|五味|多种|内容物).{0,24}(?:一包|单包|一袋|单袋))"
)
SUBTITLE_QUOTE_RE = re.compile(
    r"字幕(?:仅)?(?:写|为|保持)?[：:\s]*[\"'“‘]([^\"'”’]+)[\"'”’]"
)
VISUAL_EVIDENCE_VARIABLE_RE = re.compile(r"截图|证据画面|报告画面|证明画面")
PREARRANGED_RE = re.compile(r"预先?摆盘|预摆|提前摆盘")
SIGNIFICANCE_RE = re.compile(r"显著性?|p\s*值|p-value", re.IGNORECASE)
STATISTICAL_DESIGN_RE = re.compile(r"样本量|统计检验|显著性检验|置信区间|p\s*值|p-value", re.IGNORECASE)
NONEXISTENT_VISUAL_RE = re.compile(r"不得虚构([^。；\n]+?)(?:等)?实际不存在")
USAGE_PERIOD_RE = re.compile(r"(?:\d+\s*(?:天|周|个月|月)|一整天|整天|一周|整周|一个月|整月)")


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s:：,，;；()（）]+", "", text)


def joined_text(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for field in fields:
        value = record.get(field, "")
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return "\n".join(parts)


def exact_field_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for pattern in EXACT_FIELD_PATTERNS:
        tokens.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(tokens))


def unsupported_exact_tokens(
    record: dict[str, Any],
    fields: tuple[str, ...],
    fact_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    linked = [fact_lookup[item] for item in map(str, list_value(record, "fact_ids")) if item in fact_lookup]
    if not any(item.get("exact_fields_verified") is False for item in linked):
        return []
    support_parts: list[str] = []
    for fact in linked:
        support_parts.append(str(fact.get("statement", "")))
        quotes = fact.get("source_quotes", [])
        if isinstance(quotes, list):
            support_parts.extend(str(item) for item in quotes)
    support = normalized(" ".join(support_parts))
    return [token for token in exact_field_tokens(joined_text(record, fields)) if normalized(token) not in support]


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def duplicate_ids(records: list[dict[str, Any]], key: str) -> list[str]:
    values = [str(item.get(key, "")) for item in records]
    return sorted(value for value, count in Counter(values).items() if value and count > 1)


def nonempty_text(record: dict[str, Any], field: str) -> bool:
    return bool(str(record.get(field, "")).strip())


def list_value(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field)
    return value if isinstance(value, list) else []


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"缺少必需文件 {name}: {path}")
    if errors:
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}

    try:
        manifest = read_json(paths["manifest"])
        upstream = read_json(paths["upstream"])
        existing = read_jsonl(paths["existing"])
        scans = read_jsonl(paths["paths"])
        slots = read_jsonl(paths["slots"])
        vis = read_jsonl(paths["vis"])
        validations = read_jsonl(paths["validation"])
        gaps = read_jsonl(paths["gaps"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}

    counts = {
        "existing_expressions": len(existing), "six_path_rows": len(scans),
        "slot_rows": len(slots), "vis": len(vis), "validation_tasks": len(validations),
        "gaps": len(gaps),
    }

    missing = missing_fields(manifest, MANIFEST_FIELDS)
    if missing:
        errors.append(f"expression_manifest.json 缺少字段: {', '.join(missing)}")
    if not re.fullmatch(r"VE-[0-9a-f]{12}", str(manifest.get("value_expression_id", ""))):
        errors.append("value_expression_id 必须使用 VE- 加 12 位小写十六进制")
    output_version = str(manifest.get("output_version", ""))
    if not re.fullmatch(r"V[1-9]\d*", output_version):
        errors.append("output_version 必须使用 V1、V2、V3 等正整数版本")
    elif manifest.get("product_value_id"):
        expected_id = value_expression_id(str(manifest.get("product_value_id")), output_version)
        if manifest.get("value_expression_id") != expected_id:
            errors.append("value_expression_id 与 product_value_id / output_version 不一致")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}；旧交付需要用当前版本重新初始化")
    if manifest.get("skill_version") != SKILL_VERSION:
        errors.append(f"skill_version 必须为 {SKILL_VERSION}；不得用新校验器给旧Skill交付补签")
    if not re.fullmatch(r"PV-[0-9a-f]{12}", str(manifest.get("product_value_id", ""))):
        errors.append("product_value_id 格式无效")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        errors.append("analysis_status 不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        errors.append("delivery_status 不在允许范围")
    if manifest.get("analysis_status") == "draft":
        errors.append("analysis_status=draft，不得作为正式交付")
    if not isinstance(manifest.get("limitations"), list):
        errors.append("limitations 必须是数组")

    upstream_missing = missing_fields(upstream, UPSTREAM_FIELDS)
    if upstream_missing:
        errors.append(f"upstream_snapshot.json 缺少字段: {', '.join(upstream_missing)}")
    if manifest.get("product_value_id") != upstream.get("product_value_id"):
        errors.append("manifest 与 upstream_snapshot 的 product_value_id 不一致")
    if manifest.get("upstream_output_version") != upstream.get("upstream_output_version"):
        errors.append("manifest 与 upstream_snapshot 的上游版本不一致")
    if upstream.get("upstream_analysis_status") not in UPSTREAM_ANALYSIS_STATUSES:
        errors.append("上游 analysis_status 当前不可调用")
    if upstream.get("upstream_delivery_status") not in UPSTREAM_DELIVERY_STATUSES:
        errors.append("上游 delivery_status 当前不可调用")
    if upstream.get("p0_status") in {"P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
        errors.append("上游 P0 已重开、替换或停止，当前卖点呈现必须标记 stale")
    if not isinstance(upstream.get("values"), list):
        errors.append("upstream values 必须是数组")
    if not isinstance(upstream.get("fact_ids"), list):
        errors.append("upstream fact_ids 必须是数组")
    if not isinstance(upstream.get("facts"), list):
        errors.append("upstream facts 必须是数组")
    if not isinstance(upstream.get("file_hashes"), dict):
        errors.append("upstream file_hashes 必须是对象")

    ledger_specs = (
        ("existing_expression_ledger", existing, "expression_id", EXISTING_FIELDS, r"(?:EX|PEX)-\d{3,}"),
        ("six_path_ledger", scans, "scan_id", PATH_FIELDS, r"PATH-\d{3,}"),
        ("slot_scan_ledger", slots, "slot_id", SLOT_FIELDS, r"SLOT-(?:0[1-9]|1[0-2])"),
        ("vis_ledger", vis, "vis_id", VIS_FIELDS, r"VIS-\d{3,}"),
        ("validation_ledger", validations, "test_id", VALIDATION_FIELDS, r"TEST-\d{3,}"),
        ("gap_ledger", gaps, "gap_id", GAP_FIELDS, r"GAP-\d{3,}"),
    )
    for ledger_name, records, key, fields, pattern in ledger_specs:
        for index, record in enumerate(records, start=1):
            item_missing = missing_fields(record, fields)
            if item_missing:
                errors.append(f"{ledger_name} 第 {index} 条缺少字段: {', '.join(item_missing)}")
            if not re.fullmatch(pattern, str(record.get(key, ""))):
                errors.append(f"{ledger_name} 第 {index} 条 {key} 格式无效")
        duplicates = duplicate_ids(records, key)
        if duplicates:
            errors.append(f"{ledger_name} 存在重复 ID: {', '.join(duplicates)}")

    upstream_values = {
        str(item.get("value_id", "")): item
        for item in upstream.get("values", [])
        if isinstance(item, dict) and item.get("value_id")
    }
    active_values = {
        value_id
        for value_id, item in upstream_values.items()
        if item.get("layer") in ACTIVE_VALUE_LAYERS and item.get("downstream_readiness") != "blocked"
    }
    fact_ids = {str(item) for item in upstream.get("fact_ids", [])}
    fact_lookup = {
        str(item.get("fact_id", "")): item
        for item in upstream.get("facts", [])
        if isinstance(item, dict) and item.get("fact_id")
    }
    upstream_expression_ids = {str(item) for item in upstream.get("expression_ids", [])}
    existing_ids = {str(item.get("expression_id", "")) for item in existing}
    source_expression_count = 0
    for record in existing:
        expression_id = str(record.get("expression_id", ""))
        origin = str(record.get("expression_origin", ""))
        source_form = str(record.get("source_form", ""))
        if origin not in EXPRESSION_ORIGINS:
            errors.append(f"{expression_id} expression_origin 不在允许范围")
        if source_form not in EXPRESSION_SOURCE_FORMS:
            errors.append(f"{expression_id} source_form 不在允许范围")
        if record.get("status") not in EXPRESSION_STATUSES:
            errors.append(f"{expression_id} status 不在允许范围")
        if origin == "upstream":
            if expression_id not in upstream_expression_ids or not expression_id.startswith("EX-"):
                errors.append(f"{expression_id} 标为上游表达时必须继承有效 EX 资产")
            if source_form != "upstream_registered":
                errors.append(f"{expression_id} 上游表达的 source_form 必须为 upstream_registered")
        if origin == "source_material":
            source_expression_count += 1
            if not expression_id.startswith("PEX-") or expression_id in upstream_expression_ids:
                errors.append(f"{expression_id} 补充素材表达必须使用独立 PEX- 编号")
            if source_form == "upstream_registered":
                errors.append(f"{expression_id} 补充素材表达不得标为 upstream_registered")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{expression_id} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        if origin == "source_material" and not list_value(record, "fact_ids"):
            errors.append(f"{expression_id} 补充素材表达至少回指一个上游事实")
        unknown_values = set(map(str, list_value(record, "value_ids"))) - set(upstream_values)
        if unknown_values:
            errors.append(f"{expression_id} 引用了未知价值: {', '.join(sorted(unknown_values))}")
        if manifest.get("analysis_status") in {"complete", "partial"}:
            for field in ("source_statement", "source_id", "locator", "current_perception", "boundary"):
                if not nonempty_text(record, field):
                    errors.append(f"{expression_id} 正式盘点缺少 {field}")
            if not nonempty_text(record, "page_says") and not nonempty_text(record, "page_shows"):
                errors.append(f"{expression_id} 必须填写 page_says 或 page_shows")
            if not nonempty_text(record, "reusable") and not nonempty_text(record, "gap"):
                errors.append(f"{expression_id} 必须填写 reusable 或 gap")
            if record.get("status") == "inventory_pending":
                errors.append(f"{expression_id} 仍为 inventory_pending，不得正式交付")

    source_materials = str(manifest.get("source_materials", "")).strip()
    if (
        manifest.get("analysis_status") in {"complete", "partial"}
        and source_materials not in {"", "not_provided", "未提供"}
        and source_expression_count == 0
    ):
        errors.append("已提供补充商品素材，但 existing_expression_ledger 没有 source_material / PEX 页面表达盘点")

    visible_page_text = normalized("\n".join(str(item.get("page_shows", "")) for item in existing))
    boundary_text = "\n".join(
        [joined_text(item, ("translation", "reason", "boundary")) for item in scans]
        + [
            joined_text(item, ("human_language", "visual_track", "prop_track", "misuse", "boundary"))
            for item in vis
        ]
        + [
            joined_text(item, ("validation_task", "control_version", "test_version", "boundary"))
            for item in validations
        ]
    )
    for match in NONEXISTENT_VISUAL_RE.finditer(boundary_text):
        for item in re.split(r"[、,/和及]", match.group(1)):
            token = normalized(item.removesuffix("等"))
            if len(token) >= 2 and token in visible_page_text:
                errors.append(f"页面盘点已登记可见元素“{item.strip()}”，不得同时把它写成实际不存在")

    scans_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scan_role_lookup: dict[tuple[str, str], str] = {}
    for record in scans:
        value_id = str(record.get("value_id", ""))
        route = str(record.get("route", ""))
        role = str(record.get("role", ""))
        scans_by_value[value_id].append(record)
        scan_role_lookup[(value_id, route)] = role
        if value_id not in active_values:
            errors.append(f"{record.get('scan_id')} 引用了不可调用或未知价值 {value_id}")
        if route not in ROUTES:
            errors.append(f"{record.get('scan_id')} route 不在六条路径范围")
        if role not in ROUTE_ROLES:
            errors.append(f"{record.get('scan_id')} role 不在允许范围")
        if not all(nonempty_text(record, field) for field in ("translation", "reason", "boundary")):
            errors.append(f"{record.get('scan_id')} 必须填写 translation、reason 和 boundary")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{record.get('scan_id')} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - existing_ids
        if unknown_ex:
            errors.append(f"{record.get('scan_id')} 引用了未知页面表达: {', '.join(sorted(unknown_ex))}")
        unsupported = unsupported_exact_tokens(record, ("translation",), fact_lookup)
        if unsupported:
            errors.append(f"{record.get('scan_id')} 使用了上游未核验的精确字段: {', '.join(unsupported)}")

    if manifest.get("analysis_status") in {"complete", "partial"}:
        if not active_values:
            errors.append("上游没有可进入沟通的 P0/P1/P2 价值")
        for value_id in sorted(active_values):
            rows = scans_by_value.get(value_id, [])
            route_counts = Counter(str(item.get("route", "")) for item in rows)
            if set(route_counts) != ROUTES or any(count != 1 for count in route_counts.values()):
                errors.append(f"{value_id} 必须逐项且仅一次扫描六条翻译路径")
            roles = Counter(str(item.get("role", "")) for item in rows)
            if roles["primary"] != 1:
                errors.append(f"{value_id} 必须选择且只选择 1 条主路径")
            if roles["supporting"] not in {1, 2}:
                errors.append(f"{value_id} 必须选择 1—2 条辅助路径")

    slot_numbers = [str(item.get("slot_number", "")) for item in slots]
    if manifest.get("analysis_status") in {"complete", "partial"}:
        if set(slot_numbers) != set(SLOT_GROUPS) or len(slot_numbers) != 12:
            errors.append("slot_scan_ledger 必须完整扫描 01—12 十二类槽位")
    slot_map = {str(item.get("slot_number", "")): item for item in slots}
    for record in slots:
        number = str(record.get("slot_number", ""))
        status = str(record.get("status", ""))
        if str(record.get("slot_id", "")) != f"SLOT-{number}":
            errors.append(f"槽位 {number} 的 slot_id 必须为 SLOT-{number}")
        if record.get("asset_group") not in ASSET_GROUPS or record.get("asset_group") != SLOT_GROUPS.get(number):
            errors.append(f"SLOT-{number} 的资产组不正确")
        if status not in SLOT_STATUSES:
            errors.append(f"SLOT-{number} status 不在允许范围")
        if not nonempty_text(record, "slot_name") or not nonempty_text(record, "reason"):
            errors.append(f"SLOT-{number} 必须填写槽位名称和判断理由")
        if status == "applicable" and not list_value(record, "vis_ids"):
            errors.append(f"SLOT-{number} 标为适用时至少关联一个 VIS")
        if status == "not_applicable" and list_value(record, "vis_ids"):
            errors.append(f"SLOT-{number} 标为不适用时不得关联 VIS")

    vis_ids = {str(item.get("vis_id", "")) for item in vis}
    existing_map = {str(item.get("expression_id", "")): item for item in existing}
    vis_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    priorities: list[int] = []
    for record in vis:
        vis_id = str(record.get("vis_id", ""))
        value_id = str(record.get("value_id", ""))
        vis_by_value[value_id].append(record)
        if value_id not in active_values:
            errors.append(f"{vis_id} 主价值不可调用或不存在: {value_id}")
        secondary = set(map(str, list_value(record, "secondary_value_ids")))
        if value_id in secondary:
            errors.append(f"{vis_id} 辅助价值不得重复主价值")
        unknown_secondary = secondary - set(upstream_values)
        if unknown_secondary:
            errors.append(f"{vis_id} 引用了未知辅助价值: {', '.join(sorted(unknown_secondary))}")
        number = str(record.get("slot_number", ""))
        slot = slot_map.get(number)
        if not slot or slot.get("status") != "applicable":
            errors.append(f"{vis_id} 关联的 SLOT-{number} 不存在或不适用")
        elif record.get("asset_group") != slot.get("asset_group"):
            errors.append(f"{vis_id} 的资产组与 SLOT-{number} 不一致")
        if record.get("asset_group") not in ASSET_GROUPS:
            errors.append(f"{vis_id} asset_group 不在允许范围")
        if record.get("decision_task") not in DECISION_TASKS:
            errors.append(f"{vis_id} decision_task 不在允许范围")
        primary_route = str(record.get("primary_route", ""))
        supporting_routes = list(map(str, list_value(record, "supporting_routes")))
        if primary_route not in ROUTES or scan_role_lookup.get((value_id, primary_route)) != "primary":
            errors.append(f"{vis_id} 主路径与 {value_id} 六路扫描不一致")
        if not 1 <= len(supporting_routes) <= 2:
            errors.append(f"{vis_id} 必须引用 1—2 条辅助路径")
        for route in supporting_routes:
            if route not in ROUTES or scan_role_lookup.get((value_id, route)) != "supporting":
                errors.append(f"{vis_id} 辅助路径 {route} 与六路扫描不一致")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{vis_id} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - existing_ids
        if unknown_ex:
            errors.append(f"{vis_id} 引用了未知页面表达: {', '.join(sorted(unknown_ex))}")
        if not list_value(record, "fact_ids"):
            errors.append(f"{vis_id} 至少引用一个上游商品事实")
        for field in ("user_question", "target_perception", "human_language", "must_keep", "variable_parts", "misuse", "boundary", *TRACK_FIELDS):
            if not nonempty_text(record, field):
                errors.append(f"{vis_id} 缺少必填内容 {field}")
        objects = set(map(str, list_value(record, "applicable_objects")))
        if not objects or not objects <= CONTENT_OBJECTS:
            errors.append(f"{vis_id} applicable_objects 必须是五大作业对象的非空子集")
        if record.get("validation_status") not in VIS_STATUSES:
            errors.append(f"{vis_id} validation_status 不在允许范围")
        positive_fields = (
            "user_question", "target_perception", "human_language", "visual_track",
            "action_track", "sound_track", "subtitle_track", "prop_track", "scene_track",
            "effect_bgm_track", "commerce_handoff_track", "must_keep", "variable_parts",
        )
        unsupported = unsupported_exact_tokens(record, positive_fields, fact_lookup)
        if unsupported:
            errors.append(f"{vis_id} 使用了上游未核验的精确字段: {', '.join(unsupported)}")
        positive_text = joined_text(record, positive_fields)
        linked_fact_text = normalized("\n".join(
            joined_text(fact_lookup[fact_id], ("statement", "source_quotes", "boundary"))
            for fact_id in map(str, list_value(record, "fact_ids"))
            if fact_id in fact_lookup
        ))
        unsupported_periods = sorted({
            match.group(0)
            for match in USAGE_PERIOD_RE.finditer(positive_text)
            if normalized(match.group(0)) not in linked_fact_text
        })
        if unsupported_periods:
            errors.append(f"{vis_id} 使用周期缺少上游事实支持: {', '.join(unsupported_periods)}")
        if ORIGINAL_ASSET_RE.search(positive_text):
            has_original = any(
                existing_map.get(expression_id, {}).get("source_form") == "original_document"
                for expression_id in map(str, list_value(record, "expression_ids"))
            )
            if not has_original:
                errors.append(f"{vis_id} 把截图或页面素材称为原件，但没有 original_document 页面表达依据")
        proof_claim = joined_text(record, ("user_question", "target_perception", "human_language"))
        if SINGLE_PACK_CLAIM_RE.search(proof_claim):
            proof_method = joined_text(record, ("action_track", "must_keep"))
            has_continuity = bool(re.search(r"连续|一镜到底|不中断|不剪辑", proof_method))
            has_no_supplement = bool(re.search(r"未拆封|不补料|不换包|不拼接|单包全部", proof_method))
            if not has_continuity or not has_no_supplement:
                errors.append(f"{vis_id} 声称单包内容物时必须保留未拆封单包、连续展示和不补料/不换包证明")
        priority = record.get("external_priority")
        if priority is not None:
            if type(priority) is not int or not 1 <= priority <= 5:
                errors.append(f"{vis_id} external_priority 必须为空或 1—5 整数")
            else:
                priorities.append(priority)
    if len(priorities) != len(set(priorities)):
        errors.append("external_priority 1—5 不能重复")
    if len(priorities) > 5:
        errors.append("普通版最多选择 5 个核心呈现资产")
    if priorities and set(priorities) != set(range(1, len(priorities) + 1)):
        errors.append("external_priority 必须从 1 开始连续编号")
    core_vis = [item for item in vis if type(item.get("external_priority")) is int]
    for item in core_vis:
        if str(item.get("slot_number", "")) == "02":
            errors.append(f"{item.get('vis_id')} 是一级识别锚，不得进入普通版核心呈现卡")
    if manifest.get("analysis_status") in {"complete", "partial"}:
        for value_id in sorted(active_values):
            if not vis_by_value.get(value_id):
                errors.append(f"{value_id} 是可沟通价值，但没有可调用 VIS")
        recommended = str(upstream.get("recommended_value_id", ""))
        if not any(item.get("external_priority") for item in vis_by_value.get(recommended, [])):
            errors.append("普通版核心呈现资产必须至少包含上游推荐 P0 的一个 VIS")
        if len(active_values) <= 5:
            core_primary_values = {str(item.get("value_id", "")) for item in core_vis}
            missing_core_values = active_values - core_primary_values
            if missing_core_values:
                errors.append(
                    "可沟通价值不超过 5 个时，普通版核心呈现卡必须各覆盖一个主价值；缺少: "
                    + ", ".join(sorted(missing_core_values))
                )

    for record in slots:
        number = str(record.get("slot_number", ""))
        for linked in map(str, list_value(record, "vis_ids")):
            if linked not in vis_ids:
                errors.append(f"SLOT-{number} 引用了未知 VIS: {linked}")
            else:
                linked_record = next(item for item in vis if item.get("vis_id") == linked)
                if str(linked_record.get("slot_number", "")) != number:
                    errors.append(f"SLOT-{number} 与 {linked} 的 slot_number 不一致")

    if len(validations) > 3:
        errors.append("第一轮内容验证最多保留 3 个任务")
    vis_map = {str(item.get("vis_id", "")): item for item in vis}
    for record in validations:
        test_id = str(record.get("test_id", ""))
        unknown_vis = set(map(str, list_value(record, "vis_ids"))) - vis_ids
        if unknown_vis:
            errors.append(f"{test_id} 引用了未知 VIS: {', '.join(sorted(unknown_vis))}")
        if not list_value(record, "vis_ids"):
            errors.append(f"{test_id} 至少关联一个 VIS")
        if not list_value(record, "primary_metrics"):
            errors.append(f"{test_id} 必须给出与任务匹配的观察指标")
        for field in (
            "validation_task", "must_keep", "single_variable", "control_version",
            "test_version", "measurement_method", "decision_rule", "writeback",
            "requirements", "boundary",
        ):
            if not nonempty_text(record, field):
                errors.append(f"{test_id} 缺少必填内容 {field}")
        if record.get("status") not in TEST_STATUSES:
            errors.append(f"{test_id} status 不在允许范围")
        if normalized(record.get("control_version")) == normalized(record.get("test_version")):
            errors.append(f"{test_id} 对照版与测试版不得相同")
        task_text = str(record.get("validation_task", ""))
        variable_text = str(record.get("single_variable", ""))
        if ("上下" in task_text and "左右" in variable_text) or ("左右" in task_text and "上下" in variable_text):
            errors.append(f"{test_id} 验证任务与 single_variable 的方向描述不一致")
        control_text = str(record.get("control_version", ""))
        test_text = str(record.get("test_version", ""))
        if VISUAL_EVIDENCE_VARIABLE_RE.search(variable_text):
            control_subtitle = SUBTITLE_QUOTE_RE.search(control_text)
            test_subtitle = SUBTITLE_QUOTE_RE.search(test_text)
            if (
                control_subtitle
                and test_subtitle
                and normalized(control_subtitle.group(1)) != normalized(test_subtitle.group(1))
            ):
                errors.append(f"{test_id} 把证据画面设为唯一变量时，不得同时改变字幕")
        pack_test_text = joined_text(
            record,
            ("validation_task", "single_variable", "control_version", "test_version", "measurement_method", "writeback"),
        ) + "\n" + "\n".join(map(str, list_value(record, "primary_metrics")))
        if SINGLE_PACK_CLAIM_RE.search(pack_test_text) and PREARRANGED_RE.search(control_text):
            errors.append(f"{test_id} 衡量单包构成时，对照版也必须来自当前 SKU 的真实单包，不得使用预摆盘")
        significance_text = joined_text(record, ("decision_rule", "measurement_method", "requirements"))
        if SIGNIFICANCE_RE.search(significance_text):
            design_text = joined_text(record, ("measurement_method", "requirements"))
            if not STATISTICAL_DESIGN_RE.search(design_text):
                errors.append(f"{test_id} 使用显著性判断但没有登记样本量或统计检验方法")
        for metric in map(str, list_value(record, "primary_metrics")):
            if re.search(r"(?:留存|完播|点击).{0,16}(?:评论|复述)|(?:评论|复述).{0,16}(?:留存|完播|点击)", metric):
                errors.append(f"{test_id} 把平台行为指标与评论语义混成不可直接观测的单一指标: {metric}")
        linked_vis = [vis_map[item] for item in map(str, list_value(record, "vis_ids")) if item in vis_map]
        proxy = dict(record)
        proxy["fact_ids"] = sorted({
            str(fact_id)
            for item in linked_vis
            for fact_id in list_value(item, "fact_ids")
        })
        unsupported = unsupported_exact_tokens(
            proxy,
            ("validation_task", "must_keep", "single_variable", "control_version", "test_version"),
            fact_lookup,
        )
        if unsupported:
            errors.append(f"{test_id} 使用了上游未核验的精确字段: {', '.join(unsupported)}")
        validation_positive_text = joined_text(
            record,
            ("validation_task", "must_keep", "single_variable", "control_version", "test_version"),
        )
        if ORIGINAL_ASSET_RE.search(validation_positive_text):
            linked_expression_ids = {
                str(expression_id)
                for item in linked_vis
                for expression_id in list_value(item, "expression_ids")
            }
            if not any(existing_map.get(item, {}).get("source_form") == "original_document" for item in linked_expression_ids):
                errors.append(f"{test_id} 把截图或页面素材称为原件，但关联 VIS 没有 original_document 依据")

    if manifest.get("analysis_status") == "insufficient" and not gaps:
        errors.append("analysis_status=insufficient 时至少需要一条资料缺口")
    for report_key in ("report_01", "report_02"):
        text = paths[report_key].read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"{paths[report_key].name} 为空")
        if re.search(r"\{\{[^}]+\}\}|\[TODO|TODO:|待填写", text):
            errors.append(f"{paths[report_key].name} 仍有模板占位符")
        if re.search(r"(?:PV|VE|SRC|ANCHOR|FABE|VIS|PATH|SLOT|TEST|V|F|H|EX|U|DYN|STRAT)-\d", text):
            errors.append(f"{paths[report_key].name} 暴露内部资产 ID")
        if re.search(r"[A-Za-z]:\\(?:Users|Documents|Desktop|Downloads|会稽山|喜纯)", text):
            errors.append(f"{paths[report_key].name} 暴露本地绝对路径")
    report_01 = paths["report_01"].read_text(encoding="utf-8")
    for heading in (
        "## 1｜卖点感知化总览", "## 2｜品牌语言翻译为用户语言",
        "## 3｜核心卖点感知化呈现卡", "## 4｜内容功能位置怎么调用",
        "## 5｜五大作业对象调用地图", "## 6｜第一轮内容验证",
        "## 7｜资产回写闭环",
    ):
        if heading not in report_01:
            errors.append(f"01_卖点可视化呈现.md 缺少章节: {heading}")
    if report_01.count("### 呈现卡") > 5:
        errors.append("普通版核心呈现卡超过 5 张")

    report_data = {
        "manifest": manifest,
        "upstream": upstream,
        "existing": existing,
        "scans": scans,
        "slots": slots,
        "vis": vis,
        "validations": validations,
        "gaps": gaps,
    }
    expected_reports = {
        "report_01": build_report_01(report_data).rstrip() + "\n",
        "report_02": build_report_02(report_data).rstrip() + "\n",
    }
    for report_key, expected in expected_reports.items():
        actual = paths[report_key].read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"{paths[report_key].name} 与 data 账本不同步，请重新运行报告构建器")

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "analysis_status": manifest.get("analysis_status"),
        "delivery_status": manifest.get("delivery_status"),
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_delivery(args.delivery)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
