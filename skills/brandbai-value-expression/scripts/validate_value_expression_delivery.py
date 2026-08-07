"""Validate a BrandBAI Value Expression delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from value_expression_common import (
    ACTIVE_VALUE_LAYERS,
    ANALYSIS_STATUSES,
    ASSET_GROUPS,
    CONTENT_OBJECTS,
    DECISION_TASKS,
    DELIVERY_STATUSES,
    ROUTES,
    ROUTE_ROLES,
    SLOT_STATUSES,
    TEST_STATUSES,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    VIS_STATUSES,
    delivery_paths,
    read_json,
    read_jsonl,
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
    "expression_id", "value_ids", "source_statement", "source_id", "locator",
    "page_says", "page_shows", "current_perception", "reusable", "gap",
    "status", "boundary",
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
    "primary_metrics", "writeback", "status", "requirements", "boundary",
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
        ("existing_expression_ledger", existing, "expression_id", EXISTING_FIELDS, r"EX-\d{3,}"),
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
    expression_ids = {str(item) for item in upstream.get("expression_ids", [])}
    existing_ids = {str(item.get("expression_id", "")) for item in existing}
    if not existing_ids <= expression_ids:
        errors.append(f"现有页面表达不是上游 EX 资产: {', '.join(sorted(existing_ids - expression_ids))}")
    for record in existing:
        unknown_values = set(map(str, list_value(record, "value_ids"))) - set(upstream_values)
        if unknown_values:
            errors.append(f"{record.get('expression_id')} 引用了未知价值: {', '.join(sorted(unknown_values))}")

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
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - expression_ids
        if unknown_ex:
            errors.append(f"{record.get('scan_id')} 引用了未知页面表达: {', '.join(sorted(unknown_ex))}")

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
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - expression_ids
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
        priority = record.get("external_priority")
        if priority is not None:
            if not isinstance(priority, int) or not 1 <= priority <= 5:
                errors.append(f"{vis_id} external_priority 必须为空或 1—5 整数")
            else:
                priorities.append(priority)
    if len(priorities) != len(set(priorities)):
        errors.append("external_priority 1—5 不能重复")
    if len(priorities) > 5:
        errors.append("普通版最多选择 5 个核心呈现资产")
    if manifest.get("analysis_status") in {"complete", "partial"}:
        for value_id in sorted(active_values):
            if not vis_by_value.get(value_id):
                errors.append(f"{value_id} 是可沟通价值，但没有可调用 VIS")
        recommended = str(upstream.get("recommended_value_id", ""))
        if not any(item.get("external_priority") for item in vis_by_value.get(recommended, [])):
            errors.append("普通版核心呈现资产必须至少包含上游推荐 P0 的一个 VIS")

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
    for record in validations:
        test_id = str(record.get("test_id", ""))
        unknown_vis = set(map(str, list_value(record, "vis_ids"))) - vis_ids
        if unknown_vis:
            errors.append(f"{test_id} 引用了未知 VIS: {', '.join(sorted(unknown_vis))}")
        if not list_value(record, "vis_ids"):
            errors.append(f"{test_id} 至少关联一个 VIS")
        if not list_value(record, "primary_metrics"):
            errors.append(f"{test_id} 必须给出与任务匹配的观察指标")
        for field in ("validation_task", "must_keep", "single_variable", "writeback", "requirements", "boundary"):
            if not nonempty_text(record, field):
                errors.append(f"{test_id} 缺少必填内容 {field}")
        if record.get("status") not in TEST_STATUSES:
            errors.append(f"{test_id} status 不在允许范围")

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
