"""Initialize a BrandBAI Value Expression delivery from a valid Product Value delivery."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from value_expression_common import (
    REPORT_FILES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    file_sha256,
    now_iso,
    normalize_output_version,
    read_json,
    read_jsonl,
    upstream_paths,
    value_expression_id,
    write_json,
    write_jsonl,
)


def load_upstream(product_value_delivery: Path) -> dict[str, Any]:
    root = product_value_delivery.resolve()
    paths = upstream_paths(root)
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"商品价值底座缺少必需文件: {', '.join(missing)}")
    manifest = read_json(paths["manifest"])
    decision = read_json(paths["decision"])
    facts = read_jsonl(paths["facts"])
    values = read_jsonl(paths["values"])
    if manifest.get("analysis_status") not in UPSTREAM_ANALYSIS_STATUSES:
        raise ValueError("上游商品价值 analysis_status 必须为 complete 或 partial")
    if manifest.get("delivery_status") not in UPSTREAM_DELIVERY_STATUSES:
        raise ValueError("上游商品价值 delivery_status 必须为 ready 或 conditional")
    if decision.get("status") in {"P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
        raise ValueError("上游 P0 当前不可用，必须先回到商品价值 Skill 重开或重新编译")
    recommended = str(decision.get("recommended_value_id", ""))
    value_ids = {str(item.get("value_id", "")) for item in values}
    if not recommended or recommended not in value_ids:
        raise ValueError("上游缺少有效的推荐核心价值")
    if not all(str(manifest.get(field, "")).strip() for field in ("product_value_id", "brand", "product", "sku")):
        raise ValueError("上游商品、SKU 或 product_value_id 不完整")
    return {
        "root": root,
        "paths": paths,
        "manifest": manifest,
        "decision": decision,
        "facts": facts,
        "values": values,
    }


def build_plan(
    out: Path,
    product_value_delivery: Path,
    source_materials: Path | None,
    output_version: str = "V1",
) -> dict[str, Any]:
    upstream = load_upstream(product_value_delivery)
    manifest = upstream["manifest"]
    output_version = normalize_output_version(output_version)
    return {
        "action": "initialize_value_expression_delivery",
        "dry_run": True,
        "target": str(out.resolve()),
        "product_value_delivery": str(upstream["root"]),
        "product_value_id": manifest["product_value_id"],
        "brand": manifest["brand"],
        "product": manifest["product"],
        "sku": manifest["sku"],
        "output_version": output_version,
        "value_expression_id": value_expression_id(manifest["product_value_id"], output_version),
        "source_materials": str(source_materials.resolve()) if source_materials else "not_provided",
        "will_create": [
            *REPORT_FILES,
            "data/expression_manifest.json",
            "data/upstream_snapshot.json",
            "data/existing_expression_ledger.jsonl",
            "data/six_path_ledger.jsonl",
            "data/slot_scan_ledger.jsonl",
            "data/vis_ledger.jsonl",
            "data/validation_ledger.jsonl",
            "data/gap_ledger.jsonl",
        ],
    }


def init_delivery(
    out: Path,
    product_value_delivery: Path,
    source_materials: Path | None,
    output_version: str = "V1",
) -> dict[str, Any]:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"目标目录不是空目录，拒绝覆盖: {out}")
    upstream = load_upstream(product_value_delivery)
    source_materials = source_materials.resolve() if source_materials else None
    if source_materials and not source_materials.exists():
        raise FileNotFoundError(f"补充商品素材不存在: {source_materials}")

    manifest_up = upstream["manifest"]
    decision = upstream["decision"]
    timestamp = now_iso()
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    output_version = normalize_output_version(output_version)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "value_expression_id": value_expression_id(manifest_up["product_value_id"], output_version),
        "product_value_id": manifest_up["product_value_id"],
        "brand": manifest_up["brand"],
        "product": manifest_up["product"],
        "category": manifest_up.get("category", ""),
        "sku": manifest_up["sku"],
        "upstream_output_version": manifest_up.get("output_version", ""),
        "output_version": output_version,
        "source_materials": source_materials.name if source_materials else "not_provided",
        "analysis_status": "draft",
        "delivery_status": "blocked",
        "limitations": list(manifest_up.get("limitations", [])),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    snapshot = {
        "product_value_id": manifest_up["product_value_id"],
        "upstream_output_version": manifest_up.get("output_version", ""),
        "upstream_updated_at": manifest_up.get("updated_at", ""),
        "upstream_analysis_status": manifest_up.get("analysis_status", ""),
        "upstream_delivery_status": manifest_up.get("delivery_status", ""),
        "decision_id": decision.get("decision_id", ""),
        "p0_status": decision.get("status", ""),
        "recommended_value_id": decision.get("recommended_value_id", ""),
        "source_delivery_name": upstream["root"].name,
        "source_materials_name": source_materials.name if source_materials else "not_provided",
        "values": [
            {
                "value_id": item.get("value_id", ""),
                "layer": item.get("layer", ""),
                "p0_status": item.get("p0_status", ""),
                "user_task": item.get("user_task", ""),
                "value_statement": item.get("value_statement", ""),
                "user_perception_goal": item.get("user_perception_goal", ""),
                "downstream_readiness": item.get("downstream_readiness", ""),
                "cannot_prove": item.get("cannot_prove", []),
            }
            for item in upstream["values"]
        ],
        "fact_ids": [str(item.get("fact_id", "")) for item in upstream["facts"]],
        "facts": [
            {
                "fact_id": item.get("fact_id", ""),
                "fact_type": item.get("fact_type", ""),
                "statement": item.get("statement", ""),
                "source_quotes": item.get("source_quotes", []),
                "locator": item.get("locator", ""),
                "boundary": item.get("boundary", ""),
                "evidence_detail_confidence": item.get("evidence_detail_confidence"),
                "exact_fields_verified": item.get("exact_fields_verified"),
                "verification_locator": item.get("verification_locator", ""),
            }
            for item in upstream["facts"]
        ],
        "expression_ids": [
            str(item.get("fact_id", ""))
            for item in upstream["facts"]
            if item.get("fact_type") == "EX"
        ],
        "anchor_ids": [
            str(item.get("anchor_id", "")) for item in read_jsonl(upstream["paths"]["anchors"])
        ],
        "file_hashes": {
            path.name: file_sha256(path) for path in upstream["paths"].values()
        },
        "captured_at": timestamp,
    }
    existing = []
    for fact in upstream["facts"]:
        if fact.get("fact_type") != "EX":
            continue
        existing.append(
            {
                "expression_id": fact.get("fact_id", ""),
                "expression_origin": "upstream",
                "source_form": "upstream_registered",
                "value_ids": [],
                "fact_ids": [fact.get("fact_id", "")],
                "source_statement": fact.get("statement", ""),
                "source_id": fact.get("source_id", ""),
                "locator": fact.get("locator", ""),
                "page_says": fact.get("statement", ""),
                "page_shows": "",
                "current_perception": "",
                "reusable": "",
                "gap": "",
                "status": "inventory_pending",
                "boundary": fact.get("boundary", ""),
            }
        )

    write_json(data / "expression_manifest.json", manifest)
    write_json(data / "upstream_snapshot.json", snapshot)
    write_jsonl(data / "existing_expression_ledger.jsonl", existing)
    for filename in (
        "six_path_ledger.jsonl",
        "slot_scan_ledger.jsonl",
        "vis_ledger.jsonl",
        "validation_ledger.jsonl",
        "gap_ledger.jsonl",
    ):
        write_jsonl(data / filename, [])

    assets = Path(__file__).resolve().parent.parent / "assets"
    for filename in ("01_卖点可视化呈现模板.md", "02_资料说明与验证计划模板.md"):
        shutil.copy2(assets / filename, out / filename.replace("模板", ""))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--product-value", required=True, type=Path)
    parser.add_argument("--source-materials", type=Path)
    parser.add_argument("--output-version", default="V1")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_plan(args.out, args.product_value, args.source_materials, args.output_version)
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    manifest = init_delivery(args.out, args.product_value, args.source_materials, args.output_version)
    print(json.dumps({"status": "initialized", "target": str(args.out.resolve()), "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
