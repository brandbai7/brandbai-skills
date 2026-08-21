"""Compile a reviewed compact analysis plan into Product Value analysis ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_value_common import SKILL_VERSION, now_iso, read_json, read_jsonl, write_json, write_jsonl


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} 必须是非空字符串数组")
    return value


def compile_analysis_plan(delivery: Path, plan_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    delivery = delivery.resolve()
    data = delivery / "data"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("分析计划必须是 JSON 对象")
    manifest = read_json(data / "product_manifest.json")
    claims = read_jsonl(data / "source_claim_ledger.jsonl")
    facts = read_jsonl(data / "fact_ledger.jsonl")
    claim_ids = {str(item.get("claim_id", "")) for item in claims}
    fact_by_claim: dict[str, str] = {}
    for fact in facts:
        for claim_id in fact.get("claim_ids") or []:
            if claim_id in fact_by_claim:
                raise ValueError(f"{claim_id} 同时进入多条事实，紧凑计划无法确定绑定")
            fact_by_claim[str(claim_id)] = str(fact.get("fact_id", ""))

    def fact_ids_for(value: Any, field: str) -> list[str]:
        selected = _strings(value, field)
        unknown = [claim_id for claim_id in selected if claim_id not in claim_ids]
        missing = [claim_id for claim_id in selected if claim_id not in fact_by_claim]
        if unknown:
            raise ValueError(f"{field} 含未知 Claim：{', '.join(unknown)}")
        if missing:
            raise ValueError(f"{field} 的 Claim 未进入事实：{', '.join(missing)}")
        return list(dict.fromkeys(fact_by_claim[claim_id] for claim_id in selected))

    value_plans = plan.get("values")
    if not isinstance(value_plans, list) or not value_plans:
        raise ValueError("values 必须是非空数组")
    fabe_rows: list[dict[str, Any]] = []
    value_rows: list[dict[str, Any]] = []
    for index, value in enumerate(value_plans, 1):
        value_id = str(value.get("value_id", ""))
        if value_id != f"V-{index:03d}":
            raise ValueError("value_id 必须从 V-001 连续编号")
        feature_fact_ids = fact_ids_for(value.get("feature_claim_ids"), f"{value_id}.feature_claim_ids")
        evidence_fact_ids = fact_ids_for(value.get("evidence_claim_ids"), f"{value_id}.evidence_claim_ids")
        reference_fact_ids = fact_ids_for(value.get("reference_claim_ids"), f"{value_id}.reference_claim_ids")
        fabe_rows.append(
            {
                "fabe_id": f"FABE-{index:03d}",
                "value_id": value_id,
                "feature": str(value.get("feature", "")),
                "feature_fact_ids": feature_fact_ids,
                "advantage": str(value.get("advantage", "")),
                "benefit": str(value.get("benefit", "")),
                "evidence": str(value.get("evidence", "")),
                "evidence_fact_ids": evidence_fact_ids,
                "reference_frame": str(value.get("reference_frame", "")),
                "reference_fact_ids": reference_fact_ids,
                "user_language": str(value.get("user_language", "")),
                "derivation_status": str(value.get("derivation_status", "reasoned")),
                "boundary": str(value.get("boundary", "")),
            }
        )
        supporting_fact_ids = list(dict.fromkeys(feature_fact_ids + evidence_fact_ids + reference_fact_ids))
        value_rows.append(
            {
                "value_id": value_id,
                "layer": str(value.get("layer", "")),
                "p0_candidate": value.get("p0_candidate"),
                "p0_status": str(value.get("p0_status", "")),
                "user_task": str(value.get("user_task", "")),
                "value_statement": str(value.get("value_statement", "")),
                "supporting_fact_ids": supporting_fact_ids,
                "strategic_potential": str(value.get("strategic_potential", "")),
                "execution_maturity": str(value.get("execution_maturity", "")),
                "user_perception_goal": str(value.get("user_perception_goal", "")),
                "sku_scope": str(value.get("sku_scope", "")),
                "scope": str(value.get("scope", "")),
                "cannot_prove": _strings(value.get("cannot_prove"), f"{value_id}.cannot_prove"),
                "downstream_readiness": str(value.get("downstream_readiness", "")),
            }
        )

    anchor_plans = plan.get("anchors")
    if not isinstance(anchor_plans, list) or not anchor_plans:
        raise ValueError("anchors 必须是非空数组")
    anchor_rows = []
    for index, anchor in enumerate(anchor_plans, 1):
        anchor_rows.append(
            {
                "anchor_id": f"ANCHOR-{index:03d}",
                "anchor_type": str(anchor.get("anchor_type", "")),
                "statement": str(anchor.get("statement", "")),
                "fact_ids": fact_ids_for(anchor.get("claim_ids"), f"anchor[{index}].claim_ids"),
                "status": str(anchor.get("status", "active")),
                "boundary": str(anchor.get("boundary", "")),
            }
        )

    gap_plans = plan.get("gaps")
    if not isinstance(gap_plans, list) or not gap_plans:
        raise ValueError("gaps 必须是非空数组")
    gap_rows = []
    for index, gap in enumerate(gap_plans, 1):
        gap_rows.append(
            {
                "gap_id": f"GAP-{index:03d}",
                "category": str(gap.get("category", "")),
                "missing": str(gap.get("missing", "")),
                "impact": str(gap.get("impact", "")),
                "minimum_needed": str(gap.get("minimum_needed", "")),
                "priority": str(gap.get("priority", "")),
                "state": str(gap.get("state", "open")),
            }
        )

    decision = plan.get("p0_decision")
    if not isinstance(decision, dict):
        raise ValueError("p0_decision 必须是对象")
    values_by_id = {item["value_id"]: item for item in value_rows}
    execution_ids = _strings(decision.get("current_execution_value_ids"), "current_execution_value_ids")
    if any(value_id not in values_by_id for value_id in execution_ids):
        raise ValueError("current_execution_value_ids 含未知价值")
    execution_axis = "当前执行主轴调用：" + "；".join(values_by_id[value_id]["value_statement"] for value_id in execution_ids)
    p0_row = {
        "decision_id": "P0D-001",
        "candidate_value_ids": _strings(decision.get("candidate_value_ids"), "candidate_value_ids"),
        "recommended_value_id": str(decision.get("recommended_value_id", "")),
        "status": str(decision.get("status", "")),
        "rationale": str(decision.get("rationale", "")),
        "public_rationale": str(decision.get("public_rationale", "")),
        "current_execution_axis": execution_axis,
        "current_execution_value_ids": execution_ids,
        "cannot_prove": _strings(decision.get("cannot_prove"), "p0_decision.cannot_prove"),
        "validation_questions": _strings(decision.get("validation_questions"), "validation_questions"),
        "decided_at": now_iso(),
        "valid_until": str(decision.get("valid_until", "")),
        "supersedes": str(decision.get("supersedes", "")),
    }

    manifest_updates = plan.get("manifest")
    if not isinstance(manifest_updates, dict):
        raise ValueError("manifest 必须是对象")
    allowed_manifest_fields = {
        "sku", "sku_status", "sku_basis", "fc", "sc", "pkg_level",
        "analysis_status", "delivery_status", "limitations",
    }
    unexpected = set(manifest_updates) - allowed_manifest_fields
    if unexpected:
        raise ValueError(f"manifest 含不允许字段：{', '.join(sorted(unexpected))}")
    updated_manifest = dict(manifest)
    updated_manifest.update(manifest_updates)
    updated_manifest["skill_version"] = SKILL_VERSION
    updated_manifest["updated_at"] = now_iso()

    result = {
        "status": "dry_run" if dry_run else "compiled",
        "fabe": len(fabe_rows),
        "anchors": len(anchor_rows),
        "values": len(value_rows),
        "gaps": len(gap_rows),
        "recommended_value_id": p0_row["recommended_value_id"],
    }
    if dry_run:
        return result
    write_jsonl(data / "fabe_ledger.jsonl", fabe_rows)
    write_jsonl(data / "anchor_ledger.jsonl", anchor_rows)
    write_jsonl(data / "value_ledger.jsonl", value_rows)
    write_jsonl(data / "gap_ledger.jsonl", gap_rows)
    write_json(data / "p0_decision.json", p0_row)
    write_json(data / "product_manifest.json", updated_manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(compile_analysis_plan(args.delivery, args.plan, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
