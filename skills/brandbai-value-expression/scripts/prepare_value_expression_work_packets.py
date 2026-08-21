"""Create compact per-value work packets and six-route skeletons.

The packets are working files outside the formal delivery. An agent reads and
writes one value at a time, then merges the completed parts with
merge_value_expression_ledger_parts.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROUTES = ["数字化", "感官化", "差异化", "情境化", "证据化", "人格化"]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} 必须是 JSON 对象")
        rows.append(value)
    return rows


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_plan(delivery: Path, product_value: Path, work_dir: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    product_value = product_value.resolve()
    work_dir = work_dir.resolve()
    if not (delivery / "data" / "expression_manifest.json").is_file():
        raise ValueError("卖点呈现交付尚未初始化")
    if not (product_value / "data" / "product_manifest.json").is_file():
        raise ValueError("商品价值底座无效")
    if _is_within(work_dir, delivery):
        raise ValueError("工作分包目录必须位于正式交付目录之外")

    expression_manifest = read_json(delivery / "data" / "expression_manifest.json")
    product_manifest = read_json(product_value / "data" / "product_manifest.json")
    if expression_manifest.get("product_value_id") != product_manifest.get("product_value_id"):
        raise ValueError("卖点呈现与商品价值底座 ID 不一致")

    values = [
        row for row in read_jsonl(product_value / "data" / "value_ledger.jsonl")
        if row.get("layer") in {"P0", "P1", "P2"}
        and row.get("downstream_readiness") != "blocked"
    ]
    facts = {row.get("fact_id"): row for row in read_jsonl(product_value / "data" / "fact_ledger.jsonl")}
    expressions_path = delivery / "data" / "existing_expression_ledger.jsonl"
    expressions = read_jsonl(expressions_path) if expressions_path.is_file() else []
    p0_decision = read_json(product_value / "data" / "p0_decision.json")

    packets = []
    for index, value in enumerate(values):
        value_id = value.get("value_id")
        fact_ids = list(map(str, value.get("supporting_fact_ids") or []))
        packet = {
            "value": value,
            "supporting_facts": [facts[fact_id] for fact_id in fact_ids if fact_id in facts],
            "page_expressions": [
                row for row in expressions
                if value_id in list(map(str, row.get("value_ids") or []))
            ],
            "p0_decision": p0_decision,
            "write_contract": {
                "routes": ROUTES,
                "roles": ["primary", "supporting", "not_prioritized", "not_applicable"],
                "required_role_counts": "exactly 1 primary and 1-2 supporting",
                "output_file": f"six_path/{value_id}.jsonl",
            },
        }
        skeleton = []
        for route_index, route in enumerate(ROUTES):
            skeleton.append({
                "scan_id": f"PATH-{index * 6 + route_index + 1:03d}",
                "value_id": value_id,
                "route": route,
                "role": "",
                "translation": "",
                "reason": "",
                "fact_ids": [],
                "expression_ids": [],
                "boundary": "",
            })
        packets.append((value_id, packet, skeleton))
    return {
        "delivery": delivery,
        "product_value": product_value,
        "work_dir": work_dir,
        "packets": packets,
    }


def prepare(delivery: Path, product_value: Path, work_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    plan = build_plan(delivery, product_value, work_dir)
    packets = plan["packets"]
    result = {
        "status": "dry_run" if dry_run else "prepared",
        "values": [value_id for value_id, _, _ in packets],
        "packet_count": len(packets),
        "expected_six_path_rows": len(packets) * 6,
        "work_dir": str(plan["work_dir"]),
    }
    if dry_run:
        return result
    work_dir = plan["work_dir"]
    if work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError("工作分包目录非空；请使用新的目录")
    input_dir = work_dir / "inputs"
    path_dir = work_dir / "six_path"
    input_dir.mkdir(parents=True, exist_ok=True)
    path_dir.mkdir(parents=True, exist_ok=True)
    for value_id, packet, skeleton in packets:
        (input_dir / f"{value_id}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (path_dir / f"{value_id}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in skeleton),
            encoding="utf-8",
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare compact per-value expression work packets.")
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--product-value", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(
        args.delivery,
        args.product_value,
        args.work_dir,
        args.dry_run,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
