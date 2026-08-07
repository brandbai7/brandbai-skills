"""Validate a BrandBAI Product Value delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from product_value_common import (
    ANALYSIS_STATUSES,
    DELIVERY_STATUSES,
    FACT_TYPES,
    FC_LEVELS,
    INPUT_MODES,
    P0_STATUSES,
    PKG_LEVELS,
    READINESS_LEVELS,
    SC_LEVELS,
    VALUE_LAYERS,
    delivery_paths,
    read_json,
    read_jsonl,
)


MANIFEST_FIELDS = {
    "schema_version",
    "skill_version",
    "product_value_id",
    "brand",
    "product",
    "category",
    "sku",
    "identity_id",
    "input_mode",
    "package_version",
    "output_version",
    "fc",
    "sc",
    "pkg_level",
    "analysis_status",
    "delivery_status",
    "limitations",
    "created_at",
    "updated_at",
}
SOURCE_FIELDS = {"source_id", "source_type", "title", "locator", "captured_at", "sku_scope", "status", "notes"}
FACT_FIELDS = {"fact_id", "fact_type", "statement", "source_id", "locator", "sku_scope", "time_scope", "status", "boundary"}
FABE_FIELDS = {
    "fabe_id",
    "value_id",
    "feature",
    "feature_fact_ids",
    "advantage",
    "benefit",
    "evidence",
    "evidence_fact_ids",
    "reference_frame",
    "user_language",
    "derivation_status",
    "boundary",
}
ANCHOR_FIELDS = {"anchor_id", "anchor_type", "statement", "fact_ids", "status", "boundary"}
VALUE_FIELDS = {
    "value_id",
    "layer",
    "p0_candidate",
    "p0_status",
    "user_task",
    "value_statement",
    "supporting_fact_ids",
    "strategic_potential",
    "execution_maturity",
    "user_perception_goal",
    "sku_scope",
    "scope",
    "cannot_prove",
    "downstream_readiness",
}
DECISION_FIELDS = {
    "decision_id",
    "candidate_value_ids",
    "recommended_value_id",
    "status",
    "rationale",
    "current_execution_axis",
    "cannot_prove",
    "validation_questions",
    "decided_at",
    "valid_until",
    "supersedes",
}
GAP_FIELDS = {"gap_id", "category", "missing", "impact", "minimum_needed", "priority", "state"}


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def duplicate_ids(records: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = str(record.get(key, ""))
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []

    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"缺少必需文件 {name}: {path}")
    if errors:
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    try:
        manifest = read_json(paths["manifest"])
        sources = read_jsonl(paths["sources"])
        facts = read_jsonl(paths["facts"])
        fabe = read_jsonl(paths["fabe"])
        anchors = read_jsonl(paths["anchors"])
        values = read_jsonl(paths["values"])
        decision = read_json(paths["decision"])
        gaps = read_jsonl(paths["gaps"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    counts = {
        "sources": len(sources),
        "facts": len(facts),
        "fabe": len(fabe),
        "anchors": len(anchors),
        "values": len(values),
        "gaps": len(gaps),
    }

    missing = missing_fields(manifest, MANIFEST_FIELDS)
    if missing:
        errors.append(f"product_manifest.json 缺少字段: {', '.join(missing)}")
    if not re.fullmatch(r"PV-[0-9a-f]{12}", str(manifest.get("product_value_id", ""))):
        errors.append("product_value_id 必须使用 PV- 加 12 位小写十六进制")
    if not re.fullmatch(r"ID-\d{3,}", str(manifest.get("identity_id", ""))):
        errors.append("identity_id 格式无效")
    if manifest.get("input_mode") not in INPUT_MODES:
        errors.append("input_mode 不在允许范围")
    if manifest.get("fc") not in FC_LEVELS:
        errors.append("fc 不在 FC0—FC3 范围")
    if manifest.get("sc") not in SC_LEVELS:
        errors.append("sc 不在 SC0—SC3 范围")
    if manifest.get("pkg_level") not in PKG_LEVELS:
        errors.append("pkg_level 不在 PKG-L0—PKG-L4 范围")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        errors.append("analysis_status 不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        errors.append("delivery_status 不在允许范围")
    if manifest.get("analysis_status") == "draft":
        errors.append("analysis_status=draft，不得作为正式交付")
    if not isinstance(manifest.get("limitations"), list):
        errors.append("limitations 必须是数组")

    ledger_specs = (
        ("source_ledger", sources, "source_id", SOURCE_FIELDS, r"SRC-\d{3,}"),
        ("fact_ledger", facts, "fact_id", FACT_FIELDS, r"(?:F|STRAT|DYN|U|EX|H)-\d{3,}"),
        ("fabe_ledger", fabe, "fabe_id", FABE_FIELDS, r"FABE-\d{3,}"),
        ("anchor_ledger", anchors, "anchor_id", ANCHOR_FIELDS, r"ANCHOR-\d{3,}"),
        ("value_ledger", values, "value_id", VALUE_FIELDS, r"V-\d{3,}"),
        ("gap_ledger", gaps, "gap_id", GAP_FIELDS, r"GAP-\d{3,}"),
    )
    for ledger_name, records, id_key, fields, pattern in ledger_specs:
        for index, record in enumerate(records, start=1):
            record_missing = missing_fields(record, fields)
            if record_missing:
                errors.append(f"{ledger_name} 第 {index} 条缺少字段: {', '.join(record_missing)}")
            if not re.fullmatch(pattern, str(record.get(id_key, ""))):
                errors.append(f"{ledger_name} 第 {index} 条 {id_key} 格式无效")
        duplicates = duplicate_ids(records, id_key)
        if duplicates:
            errors.append(f"{ledger_name} 存在重复 ID: {', '.join(duplicates)}")

    source_ids = {item.get("source_id") for item in sources}
    fact_ids = {item.get("fact_id") for item in facts}
    value_ids = {item.get("value_id") for item in values}
    values_by_id = {item.get("value_id"): item for item in values}
    fabe_by_value: dict[str, list[dict[str, Any]]] = {}

    for fact in facts:
        fact_id = str(fact.get("fact_id", ""))
        fact_type = fact.get("fact_type")
        if fact_type not in FACT_TYPES:
            errors.append(f"{fact_id} 的 fact_type 不在允许范围")
        expected_prefix = "F" if fact_type in {"F-PAGE", "F-EVIDENCE"} else fact_type
        if expected_prefix and not fact_id.startswith(f"{expected_prefix}-"):
            errors.append(f"{fact_id} 与 fact_type={fact_type} 的前缀不一致")
        source_id = fact.get("source_id")
        if source_id not in source_ids:
            if fact_type == "H" and not source_id and str(fact.get("boundary", "")).strip():
                warnings.append(f"{fact_id} 是无直接来源的分析推导，已依赖 boundary 限定")
            else:
                errors.append(f"{fact_id} 引用了不存在的 source_id: {source_id}")
        if fact_type == "DYN" and not str(fact.get("time_scope", "")).strip():
            errors.append(f"{fact_id} 是动态交易事实，必须填写 time_scope")
        if not str(fact.get("statement", "")).strip():
            errors.append(f"{fact_id} 的 statement 为空")
        if not str(fact.get("boundary", "")).strip():
            errors.append(f"{fact_id} 的 boundary 为空")

    for anchor in anchors:
        anchor_id = str(anchor.get("anchor_id", ""))
        if anchor.get("anchor_type") not in {"main", "supporting"}:
            errors.append(f"{anchor_id} 的 anchor_type 必须是 main 或 supporting")
        references = anchor.get("fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{anchor_id} 必须引用至少一个 fact_id")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{anchor_id} 引用了不存在的 fact_id: {fact_id}")

    allowed_derivation_statuses = {"page_supported", "reasoned", "to_validate"}
    for item in fabe:
        fabe_id = str(item.get("fabe_id", ""))
        value_id = str(item.get("value_id", ""))
        if value_id not in value_ids:
            errors.append(f"{fabe_id} 引用了不存在的 value_id: {value_id}")
        else:
            fabe_by_value.setdefault(value_id, []).append(item)
        for key in ("feature_fact_ids", "evidence_fact_ids"):
            references = item.get(key)
            if not isinstance(references, list) or not references:
                errors.append(f"{fabe_id} 的 {key} 必须引用至少一个 fact_id")
            else:
                for fact_id in references:
                    if fact_id not in fact_ids:
                        errors.append(f"{fabe_id} 的 {key} 引用了不存在的 fact_id: {fact_id}")
        for key in ("feature", "advantage", "benefit", "evidence", "reference_frame", "user_language", "boundary"):
            if not str(item.get(key, "")).strip():
                errors.append(f"{fabe_id} 的 {key} 为空")
        if item.get("derivation_status") not in allowed_derivation_statuses:
            errors.append(f"{fabe_id} 的 derivation_status 必须是 page_supported/reasoned/to_validate")

    allowed_axis = {"high", "medium", "low", "unknown"}
    for value in values:
        value_id = str(value.get("value_id", ""))
        if value.get("layer") not in VALUE_LAYERS:
            errors.append(f"{value_id} 的 layer 不在允许范围")
        if not isinstance(value.get("p0_candidate"), bool):
            errors.append(f"{value_id} 的 p0_candidate 必须是布尔值")
        if value.get("p0_status") not in P0_STATUSES | {"", "not_applicable"}:
            errors.append(f"{value_id} 的 p0_status 不在允许范围")
        references = value.get("supporting_fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{value_id} 必须引用至少一个事实或推导")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{value_id} 引用了不存在的 fact_id: {fact_id}")
        for key in ("strategic_potential", "execution_maturity"):
            if value.get(key) not in allowed_axis:
                errors.append(f"{value_id} 的 {key} 必须是 high/medium/low/unknown")
        if value.get("downstream_readiness") not in READINESS_LEVELS:
            errors.append(f"{value_id} 的 downstream_readiness 不在允许范围")
        if not isinstance(value.get("cannot_prove"), list):
            errors.append(f"{value_id} 的 cannot_prove 必须是数组")
        if not str(value.get("value_statement", "")).strip():
            errors.append(f"{value_id} 的 value_statement 为空")
        if value.get("layer") != "deferred" and not fabe_by_value.get(value_id):
            errors.append(f"{value_id} 缺少 FABE 完整推导链")

    p0_values = [item for item in values if item.get("layer") == "P0"]
    if len(p0_values) > 1:
        errors.append("当前 layer=P0 的价值超过一个；未推荐候选应保留在其他层或 deferred")
    for layer in ("P1", "P2"):
        count = sum(1 for item in values if item.get("layer") == layer)
        if count > 3:
            errors.append(f"普通版 {layer} 超过 3 个，需合并或降为暂缓")

    decision_missing = missing_fields(decision, DECISION_FIELDS)
    if decision_missing:
        errors.append(f"p0_decision.json 缺少字段: {', '.join(decision_missing)}")
    if not re.fullmatch(r"P0D-\d{3,}", str(decision.get("decision_id", ""))):
        errors.append("decision_id 格式无效")
    if decision.get("status") not in P0_STATUSES:
        errors.append("P0 决策状态不在允许范围")
    candidate_ids = decision.get("candidate_value_ids")
    if not isinstance(candidate_ids, list):
        errors.append("candidate_value_ids 必须是数组")
        candidate_ids = []
    for value_id in candidate_ids:
        if value_id not in value_ids:
            errors.append(f"P0 候选池引用了不存在的 value_id: {value_id}")
        elif values_by_id[value_id].get("p0_candidate") is not True:
            errors.append(f"{value_id} 在 P0 候选池中，但 p0_candidate 不是 true")
    recommended_id = decision.get("recommended_value_id")
    if recommended_id:
        if recommended_id not in value_ids:
            errors.append(f"P0 推荐引用了不存在的 value_id: {recommended_id}")
        else:
            if recommended_id not in candidate_ids:
                errors.append("P0 推荐值不在 candidate_value_ids 中")
            if values_by_id[recommended_id].get("layer") != "P0":
                errors.append("P0 推荐值的 layer 必须是 P0")

    analysis_status = manifest.get("analysis_status")
    delivery_status = manifest.get("delivery_status")
    if analysis_status in {"complete", "partial"}:
        for key in ("brand", "product", "sku"):
            if not str(manifest.get(key, "")).strip():
                errors.append(f"analysis_status={analysis_status} 时 {key} 不得为空")
        if not sources:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个来源")
        if not facts:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个事实或推导")
        if not values:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个可用价值")
    if analysis_status == "complete":
        if not recommended_id:
            errors.append("analysis_status=complete 时必须有当前推荐 P0")
        if decision.get("status") in {"P0-CANDIDATE", "P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
            errors.append("analysis_status=complete 与当前 P0 决策状态不一致")
        if delivery_status not in {"ready", "conditional"}:
            errors.append("analysis_status=complete 时 delivery_status 应为 ready 或 conditional")
    elif analysis_status == "partial":
        if delivery_status != "conditional":
            errors.append("analysis_status=partial 时 delivery_status 必须是 conditional")
    elif analysis_status == "insufficient":
        if not gaps:
            errors.append("analysis_status=insufficient 时至少需要一个资料缺口")
        if delivery_status != "blocked":
            errors.append("analysis_status=insufficient 时 delivery_status 必须是 blocked")
    elif analysis_status == "stale":
        if delivery_status != "stale":
            errors.append("analysis_status=stale 时 delivery_status 必须是 stale")

    for report_key in ("report_01", "report_02"):
        text = paths[report_key].read_text(encoding="utf-8")
        if "{{" in text or "}}" in text:
            errors.append(f"{paths[report_key].name} 仍包含模板占位符")
        if re.search(r"[A-Za-z]:\\(?:Users|Documents|Desktop)\\", text, re.IGNORECASE):
            errors.append(f"{paths[report_key].name} 暴露了本地绝对路径")
        if re.search(r"\b(?:PV-[0-9a-f]{12}|(?:SRC|ANCHOR|FABE|V|F|H|EX|U|DYN|STRAT)-\d{3,})\b", text):
            errors.append(f"{paths[report_key].name} 暴露了内部资产 ID")

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "analysis_status": analysis_status,
        "delivery_status": delivery_status,
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
