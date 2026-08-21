"""Merge small, model-written JSON/JSONL partitions into one product-value ledger.

The working parts must live outside the formal delivery directory. This keeps
large source, claim, fact, and analysis ledgers from becoming one fragile model
write while preserving a clean final delivery.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


LEDGERS = {
    "observations": ("source_observation.jsonl", "observation_id", ("OBS-",)),
    "claims": ("source_claim_ledger.jsonl", "claim_id", ("CLM-",)),
    "sources": ("source_ledger.jsonl", "source_id", ("SRC-",)),
    "facts": ("fact_ledger.jsonl", "fact_id", ("F-", "DYN-", "U-", "EX-", "STRAT-", "H-")),
    "fabe": ("fabe_ledger.jsonl", "fabe_id", ("FABE-",)),
    "anchors": ("anchor_ledger.jsonl", "anchor_id", ("ANCHOR-",)),
    "values": ("value_ledger.jsonl", "value_id", ("V-",)),
    "gaps": ("gap_ledger.jsonl", "gap_id", ("GAP-",)),
}


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _read_part(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name}:{line_number} 必须是 JSON 对象")
            rows.append(value)
        return rows
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    raise ValueError(f"{path.name} 必须是 JSON 对象或对象数组")


def merge_parts(
    delivery: Path,
    ledger: str,
    parts_dir: Path,
    expected_count: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if ledger not in LEDGERS:
        raise ValueError(f"未知账本：{ledger}")
    delivery = delivery.resolve()
    parts_dir = parts_dir.resolve()
    if not (delivery / "data").is_dir():
        raise ValueError("交付目录缺少 data/")
    if not parts_dir.is_dir():
        raise ValueError("分包目录不存在")
    if _is_within(parts_dir, delivery):
        raise ValueError("分包工作目录必须位于正式交付目录之外")

    filename, id_field, prefixes = LEDGERS[ledger]
    part_files = sorted(
        path for path in parts_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl"}
    )
    if not part_files:
        raise ValueError("分包目录中没有 .json 或 .jsonl 文件")

    rows: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for path in part_files:
        for row in _read_part(path):
            stable_id = row.get(id_field)
            if not isinstance(stable_id, str) or not stable_id.startswith(prefixes):
                raise ValueError(f"{path.name} 缺少合法 {id_field}")
            if stable_id in seen:
                raise ValueError(f"{stable_id} 在 {seen[stable_id]} 与 {path.name} 重复")
            seen[stable_id] = path.name
            rows.append(row)

    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(f"期望 {expected_count} 条，实际 {len(rows)} 条")

    target = delivery / "data" / filename
    result = {
        "status": "dry_run" if dry_run else "merged",
        "ledger": ledger,
        "parts": len(part_files),
        "rows": len(rows),
        "target": str(target),
    }
    if dry_run:
        return result

    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temp, target)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge product-value ledger partitions.")
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--ledger", required=True, choices=sorted(LEDGERS))
    parser.add_argument("--parts-dir", required=True, type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(merge_parts(
        args.delivery,
        args.ledger,
        args.parts_dir,
        args.expected_count,
        args.dry_run,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
