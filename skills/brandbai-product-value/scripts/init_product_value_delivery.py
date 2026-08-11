"""Initialize a new BrandBAI Product Value delivery directory."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from product_value_common import (
    INPUT_MODES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    SKU_STATUSES,
    now_iso,
    product_value_id,
    write_json,
    write_jsonl,
)


def build_plan(
    out: Path,
    brand: str,
    product: str,
    category: str,
    sku: str,
    input_mode: str,
    sku_status: str = "unverified",
    sku_basis: str = "初始化输入，待来源核对",
) -> dict[str, Any]:
    return {
        "action": "initialize_product_value_delivery",
        "dry_run": True,
        "target": str(out.resolve()),
        "product_value_id": product_value_id(brand, product, sku),
        "brand": brand,
        "product": product,
        "category": category,
        "sku": sku,
        "sku_status": sku_status,
        "sku_basis": sku_basis,
        "input_mode": input_mode,
        "will_create": [
            "01_商品价值底座.md",
            "02_资料说明与缺口.md",
            "data/product_manifest.json",
            "data/source_inventory.jsonl",
            "data/source_audit_card_ledger.jsonl",
            "data/source_audit_cards/",
            "data/source_observation.jsonl",
            "data/source_claim_ledger.jsonl",
            "data/source_ledger.jsonl",
            "data/fact_ledger.jsonl",
            "data/fabe_ledger.jsonl",
            "data/anchor_ledger.jsonl",
            "data/value_ledger.jsonl",
            "data/p0_decision.json",
            "data/gap_ledger.jsonl",
        ],
    }


def init_delivery(
    out: Path,
    brand: str,
    product: str,
    category: str,
    sku: str,
    input_mode: str,
    sku_status: str = "unverified",
    sku_basis: str = "初始化输入，待来源核对",
) -> dict[str, Any]:
    if input_mode not in INPUT_MODES:
        raise ValueError(f"不支持的 input_mode: {input_mode}")
    if sku_status not in SKU_STATUSES:
        raise ValueError(f"不支持的 sku_status: {sku_status}")
    if not sku_basis.strip():
        raise ValueError("sku_basis 不得为空")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"目标目录不是空目录，拒绝覆盖: {out}")

    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "source_audit_cards").mkdir(parents=True, exist_ok=True)
    timestamp = now_iso()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "product_value_id": product_value_id(brand, product, sku),
        "brand": brand.strip(),
        "product": product.strip(),
        "category": category.strip(),
        "sku": sku.strip(),
        "sku_status": sku_status,
        "sku_basis": sku_basis.strip(),
        "identity_id": "ID-001",
        "input_mode": input_mode,
        "package_version": "1.0",
        "output_version": "V1",
        "fc": "FC0",
        "sc": "SC0",
        "pkg_level": "PKG-L0",
        "analysis_status": "draft",
        "delivery_status": "blocked",
        "limitations": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    decision = {
        "decision_id": "P0D-001",
        "candidate_value_ids": [],
        "recommended_value_id": "",
        "status": "P0-CANDIDATE",
        "rationale": "",
        "public_rationale": "",
        "current_execution_axis": "",
        "current_execution_value_ids": [],
        "cannot_prove": [],
        "validation_questions": [],
        "decided_at": "",
        "valid_until": "",
        "supersedes": "",
    }
    write_json(data / "product_manifest.json", manifest)
    for filename in (
        "source_inventory.jsonl",
        "source_audit_card_ledger.jsonl",
        "source_observation.jsonl",
        "source_claim_ledger.jsonl",
        "source_ledger.jsonl",
        "fact_ledger.jsonl",
        "fabe_ledger.jsonl",
        "anchor_ledger.jsonl",
        "value_ledger.jsonl",
        "gap_ledger.jsonl",
    ):
        write_jsonl(data / filename, [])
    write_json(data / "p0_decision.json", decision)

    assets = Path(__file__).resolve().parent.parent / "assets"
    for filename in ("01_商品价值底座模板.md", "02_资料说明与缺口模板.md"):
        destination = out / filename.replace("模板", "")
        shutil.copy2(assets / filename, destination)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--brand", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--sku-status", choices=("confirmed", "partial", "unverified"), default="unverified")
    parser.add_argument("--sku-basis", default="初始化输入，待来源核对")
    parser.add_argument("--input-mode", choices=sorted(INPUT_MODES), default="mixed")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_plan(
        args.out,
        args.brand,
        args.product,
        args.category,
        args.sku,
        args.input_mode,
        args.sku_status,
        args.sku_basis,
    )
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    manifest = init_delivery(
        args.out,
        args.brand,
        args.product,
        args.category,
        args.sku,
        args.input_mode,
        args.sku_status,
        args.sku_basis,
    )
    print(json.dumps({"status": "initialized", "target": str(args.out.resolve()), "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
