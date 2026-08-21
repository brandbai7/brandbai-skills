"""Compile a reviewed compact plan into BrandBAI value-expression ledgers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from value_expression_common import SKILL_VERSION, ROUTES, now_iso, read_json, read_jsonl, write_json, write_jsonl


ROUTE_ORDER = ("数字化", "感官化", "差异化", "情境化", "证据化", "人格化")
SLOT_NAMES = {
    "01": "商品识别／构成开箱", "02": "一级识别锚点", "03": "规格、数量、产地或结构连看",
    "04": "工艺到可见状态／结果", "05": "味觉、触感、气味或使用体感", "06": "省步骤／使用方便",
    "07": "使用方法／多种用法", "08": "到手量、使用周期或价值权衡", "09": "具体检测／证明对应具体顾虑",
    "10": "生产、体系、品牌或质量信息", "11": "商品身份、适用边界与买前确认", "12": "场景、人格与日常仪式",
}
ATOMIC_EXPRESSION_LABEL_RE = re.compile(
    r"(商品标题|产品名称|商品名称|品牌|品名|系列|厂名|生产企业|产地|"
    r"当前选择SKU\s*ID|当前选中规格|规格组|型号|净含量|单件净含量|包装规格|"
    r"配料表|配料|成分|营养成分表|能量|蛋白质|脂肪|碳水化合物|钠|钙|"
    r"保质期|贮存条件|储存条件|储存方法|生产许可证编号|生产许可证|"
    r"执行标准|标准编号|注册证号|备案编号|适用人群|不适宜人群|禁忌|"
    r"注意事项|警示语|使用方法|食用方法|饮用方法)\s*[:：]",
    re.IGNORECASE,
)
ORIGINAL_ASSET_RE = re.compile(r"(?:报告|证书|检测单|文件)原件|原始报告|原件报告")
INTERNAL_PUBLIC_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:PV|VE|SRC|SF|ANCHOR|FABE|VIS|PATH|SLOT|TEST|GAP|V|F|H|EX|U|DYN|STRAT)-\d",
    re.IGNORECASE,
)
VIS_PUBLIC_FIELDS = (
    "user_question", "target_perception", "human_language", "visual_track", "action_track", "sound_track",
    "subtitle_track", "prop_track", "scene_track", "effect_bgm_track", "commerce_handoff_track", "must_keep",
    "variable_parts", "misuse", "boundary",
)
TEST_PUBLIC_FIELDS = (
    "validation_task", "must_keep", "single_variable", "control_version", "test_version", "primary_metrics",
    "measurement_method", "decision_rule", "writeback", "requirements", "boundary",
)


def _public_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(_public_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_public_text(item) for item in value)
    return str(value or "")


def _check_public_text(value: Any, field: str) -> None:
    match = INTERNAL_PUBLIC_ID_RE.search(_public_text(value))
    if match:
        raise ValueError(f"{field} 暴露内部资产 ID：{match.group(0)}")


def _list(value: Any, field: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{field} 必须是{'可为空的' if allow_empty else '非空'}数组")
    return value


def compile_expression_plan(delivery: Path, product_value: Path, plan_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    delivery = delivery.resolve()
    product_value = product_value.resolve()
    data = delivery / "data"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("紧凑方案必须是 JSON 对象")
    manifest = read_json(data / "expression_manifest.json")
    snapshot = read_json(data / "upstream_snapshot.json")
    if product_value.name != snapshot.get("source_delivery_name"):
        raise ValueError("product_value 与当前上游快照不一致")
    valid_values = {str(item.get("value_id", "")) for item in snapshot.get("values") or []}
    valid_facts = {str(item) for item in snapshot.get("fact_ids") or []}

    def check_refs(
        value_ids: Any,
        fact_ids: Any,
        field: str,
        *,
        allow_empty_facts: bool = False,
    ) -> tuple[list[str], list[str]]:
        values = [str(item) for item in _list(value_ids, f"{field}.value_ids")]
        facts = [
            str(item)
            for item in _list(fact_ids, f"{field}.fact_ids", allow_empty=allow_empty_facts)
        ]
        unknown_values = sorted(set(values) - valid_values)
        unknown_facts = sorted(set(facts) - valid_facts)
        if unknown_values or unknown_facts:
            raise ValueError(f"{field} 含未知引用：value={unknown_values}, fact={unknown_facts}")
        return values, facts

    inherited = [item for item in read_jsonl(data / "existing_expression_ledger.jsonl") if item.get("expression_origin") == "upstream"]
    expressions: list[dict[str, Any]] = list(inherited)
    expression_by_key: dict[str, str] = {}
    expression_form_by_key: dict[str, str] = {}
    for index, item in enumerate(_list(plan.get("expressions"), "expressions"), 1):
        key = str(item.get("key", "")).strip()
        if not key or key in expression_by_key:
            raise ValueError("expressions.key 必须非空且唯一")
        values, facts = check_refs(item.get("value_ids"), item.get("fact_ids"), f"expression[{key}]")
        expression_text = "\n".join((str(item.get("source_statement", "")), str(item.get("page_says", ""))))
        field_labels = [match.group(1) for match in ATOMIC_EXPRESSION_LABEL_RE.finditer(expression_text)]
        if len(field_labels) > 1:
            raise ValueError(
                f"expression[{key}].source_statement/page_says 合并了多个高密度字段"
                f"（{'、'.join(field_labels)}）；请按主张单位拆分"
            )
        for field in (
            "source_statement", "locator", "page_says", "page_shows", "current_perception", "reusable", "gap", "boundary",
        ):
            _check_public_text(item.get(field), f"expression[{key}].{field}")
        expression_id = f"PEX-{index:03d}"
        expression_by_key[key] = expression_id
        expression_form_by_key[key] = str(item.get("source_form", "detail_page"))
        expressions.append({
            "expression_id": expression_id,
            "expression_origin": "source_material",
            "source_form": str(item.get("source_form", "detail_page")),
            "value_ids": values, "fact_ids": facts,
            "source_statement": str(item.get("source_statement", "")),
            "source_id": str(item.get("source_id", "")), "locator": str(item.get("locator", "")),
            "page_says": str(item.get("page_says", "")), "page_shows": str(item.get("page_shows", "")),
            "current_perception": str(item.get("current_perception", "")), "reusable": str(item.get("reusable", "")),
            "gap": str(item.get("gap", "")), "status": "page_existing_unvalidated",
            "boundary": str(item.get("boundary", "")),
        })

    def resolve_expression_keys(keys: Any, field: str) -> list[str]:
        selected = [str(item) for item in _list(keys, field, allow_empty=True)]
        unknown = sorted(set(selected) - set(expression_by_key))
        if unknown:
            raise ValueError(f"{field} 含未知 expression key：{unknown}")
        return [expression_by_key[item] for item in selected]

    path_rows: list[dict[str, Any]] = []
    path_number = 1
    route_plans = _list(plan.get("route_plans"), "route_plans")
    if {str(item.get("value_id", "")) for item in route_plans} != valid_values:
        raise ValueError("route_plans 必须恰好覆盖全部可沟通价值")
    for value_plan in route_plans:
        value_id = str(value_plan.get("value_id", ""))
        routes = value_plan.get("routes")
        if not isinstance(routes, dict) or set(routes) != set(ROUTES):
            raise ValueError(f"{value_id}.routes 必须恰好覆盖六路")
        for route in ROUTE_ORDER:
            item = routes[route]
            for field in ("translation", "reason", "boundary"):
                _check_public_text(item.get(field), f"{value_id}.{route}.{field}")
            _, facts = check_refs(
                [value_id],
                item.get("fact_ids"),
                f"{value_id}.{route}",
                allow_empty_facts=True,
            )
            path_rows.append({
                "scan_id": f"PATH-{path_number:03d}", "value_id": value_id, "route": route,
                "role": str(item.get("role", "")), "translation": str(item.get("translation", "")),
                "reason": str(item.get("reason", "")), "fact_ids": facts,
                "expression_ids": resolve_expression_keys(item.get("expression_keys", []), f"{value_id}.{route}.expression_keys"),
                "boundary": str(item.get("boundary", "")),
            })
            path_number += 1

    vis_rows: list[dict[str, Any]] = []
    vis_by_key: dict[str, str] = {}
    vis_has_original: dict[str, bool] = {}
    for index, item in enumerate(_list(plan.get("vis"), "vis"), 1):
        key = str(item.get("key", "")).strip()
        if not key or key in vis_by_key:
            raise ValueError("vis.key 必须非空且唯一")
        value_id = str(item.get("value_id", ""))
        _, facts = check_refs([value_id], item.get("fact_ids"), f"vis[{key}]")
        expression_keys = [str(value) for value in _list(item.get("expression_keys", []), f"vis[{key}].expression_keys", allow_empty=True)]
        for field in VIS_PUBLIC_FIELDS:
            _check_public_text(item.get(field), f"vis[{key}].{field}")
        positive_text = "\n".join(_public_text(item.get(field)) for field in VIS_PUBLIC_FIELDS if field not in {"misuse", "boundary"})
        has_original = any(expression_form_by_key.get(expression_key) == "original_document" for expression_key in expression_keys)
        if ORIGINAL_ASSET_RE.search(positive_text) and not has_original:
            raise ValueError(f"vis[{key}] 把截图或页面素材称为原件，但没有 original_document 页面表达依据")
        vis_id = f"VIS-{index:03d}"
        vis_by_key[key] = vis_id
        vis_has_original[key] = has_original
        row = {name: item.get(name) for name in (
            "secondary_value_ids", "asset_group", "slot_number", "user_question", "target_perception", "decision_task",
            "primary_route", "supporting_routes", "human_language", "visual_track", "action_track", "sound_track",
            "subtitle_track", "prop_track", "scene_track", "effect_bgm_track", "commerce_handoff_track", "must_keep",
            "variable_parts", "misuse", "applicable_objects", "must_preserve_tracks", "adaptable_tracks",
            "validation_status", "boundary", "external_priority",
        )}
        row.update({"vis_id": vis_id, "value_id": value_id, "fact_ids": facts,
                    "expression_ids": resolve_expression_keys(expression_keys, f"vis[{key}].expression_keys")})
        vis_rows.append(row)

    slot_plans = _list(plan.get("slots"), "slots")
    if [str(item.get("slot_number", "")) for item in slot_plans] != [f"{i:02d}" for i in range(1, 13)]:
        raise ValueError("slots 必须按 01—12 恰好各出现一次")
    slot_rows = []
    for item in slot_plans:
        number = str(item.get("slot_number"))
        _check_public_text(item.get("reason"), f"slot[{number}].reason")
        group = "欲望建立" if int(number) <= 8 else "阻力解除" if int(number) <= 11 else "氛围连接"
        keys = [str(value) for value in _list(item.get("vis_keys"), f"slot[{number}].vis_keys", allow_empty=True)]
        unknown = sorted(set(keys) - set(vis_by_key))
        if unknown:
            raise ValueError(f"slot[{number}] 含未知 vis key：{unknown}")
        slot_rows.append({"slot_id": f"SLOT-{number}", "slot_number": number, "asset_group": group,
                          "slot_name": SLOT_NAMES[number], "status": str(item.get("status", "")),
                          "reason": str(item.get("reason", "")), "vis_ids": [vis_by_key[key] for key in keys]})

    test_rows = []
    for index, item in enumerate(_list(plan.get("tests"), "tests", allow_empty=True), 1):
        keys = [str(value) for value in _list(item.get("vis_keys"), f"test[{index}].vis_keys")]
        unknown = sorted(set(keys) - set(vis_by_key))
        if unknown:
            raise ValueError(f"test[{index}] 含未知 vis key：{unknown}")
        for field in TEST_PUBLIC_FIELDS:
            _check_public_text(item.get(field), f"test[{index}].{field}")
        positive_text = "\n".join(_public_text(item.get(field)) for field in TEST_PUBLIC_FIELDS if field != "boundary")
        if ORIGINAL_ASSET_RE.search(positive_text) and not any(vis_has_original.get(key, False) for key in keys):
            raise ValueError(f"test[{index}] 把截图或页面素材称为原件，但关联 VIS 没有 original_document 依据")
        row = {name: item.get(name) for name in (
            "validation_task", "must_keep", "single_variable", "control_version", "test_version", "primary_metrics",
            "measurement_method", "decision_rule", "writeback", "status", "requirements", "boundary",
        )}
        row.update({"test_id": f"TEST-{index:03d}", "vis_ids": [vis_by_key[key] for key in keys]})
        test_rows.append(row)

    gap_rows = []
    for index, item in enumerate(_list(plan.get("gaps"), "gaps"), 1):
        for field in ("category", "missing", "impact", "minimum_needed"):
            _check_public_text(item.get(field), f"gap[{index}].{field}")
        gap_rows.append({"gap_id": f"GAP-{index:03d}", **{name: item.get(name) for name in (
            "category", "missing", "impact", "minimum_needed", "priority", "state")}})

    manifest_plan = plan.get("manifest")
    if not isinstance(manifest_plan, dict) or set(manifest_plan) - {"analysis_status", "delivery_status", "limitations"}:
        raise ValueError("manifest 只允许 analysis_status、delivery_status、limitations")
    _check_public_text(manifest_plan.get("limitations"), "manifest.limitations")
    updated_manifest = dict(manifest)
    updated_manifest.update(manifest_plan)
    updated_manifest["skill_version"] = SKILL_VERSION
    updated_manifest["updated_at"] = now_iso()
    result = {"status": "dry_run" if dry_run else "compiled", "expressions": len(expressions),
              "paths": len(path_rows), "slots": len(slot_rows), "vis": len(vis_rows),
              "tests": len(test_rows), "gaps": len(gap_rows)}
    if dry_run:
        return result
    write_jsonl(data / "existing_expression_ledger.jsonl", expressions)
    write_jsonl(data / "six_path_ledger.jsonl", path_rows)
    write_jsonl(data / "slot_scan_ledger.jsonl", slot_rows)
    write_jsonl(data / "vis_ledger.jsonl", vis_rows)
    write_jsonl(data / "validation_ledger.jsonl", test_rows)
    write_jsonl(data / "gap_ledger.jsonl", gap_rows)
    write_json(data / "expression_manifest.json", updated_manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--product-value", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(compile_expression_plan(args.delivery, args.product_value, args.plan, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
