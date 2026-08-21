"""Prepare a read-only full or claim-focused Product Value analysis packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_value_common import read_json, read_jsonl


MAX_SELECTED_CLAIMS = 120
MAX_INDEX_CLAIMS = 120


def _read_claim_ids(path: Path | None, cli_values: list[str]) -> list[str]:
    values = list(cli_values)
    if path is not None:
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [line.strip() for line in raw.splitlines() if line.strip()]
            if isinstance(parsed, dict):
                parsed = parsed.get("claim_ids")
            if not isinstance(parsed, list):
                raise ValueError("claim IDs 文件必须是 JSON 数组、含 claim_ids 的对象或每行一个 ID")
            values.extend(str(item).strip() for item in parsed)
    selected = list(dict.fromkeys(item.strip() for item in values if item.strip()))
    if len(selected) > MAX_SELECTED_CLAIMS:
        raise ValueError(f"紧凑分析包最多选择 {MAX_SELECTED_CLAIMS} 个 claim_id")
    return selected


def prepare_analysis_packet(
    delivery: Path,
    *,
    claim_ids: list[str] | None = None,
    include_dynamic: bool = False,
    index_only: bool = False,
    index_offset: int = 0,
    index_limit: int = MAX_INDEX_CLAIMS,
) -> dict[str, Any]:
    if not isinstance(index_offset, int) or index_offset < 0:
        raise ValueError("index_offset 必须是非负整数")
    if not isinstance(index_limit, int) or not 1 <= index_limit <= MAX_INDEX_CLAIMS:
        raise ValueError(f"index_limit 必须是 1—{MAX_INDEX_CLAIMS} 的整数")
    data = delivery.resolve() / "data"
    manifest = read_json(data / "product_manifest.json")
    sources = read_jsonl(data / "source_ledger.jsonl")
    claims = read_jsonl(data / "source_claim_ledger.jsonl")
    facts = read_jsonl(data / "fact_ledger.jsonl")
    selected_ids = list(dict.fromkeys(claim_ids or []))

    claim_by_id = {str(item.get("claim_id", "")): item for item in claims}
    fact_ids_by_claim: dict[str, list[str]] = {}
    for fact in facts:
        for claim_id in fact.get("claim_ids") or []:
            fact_ids_by_claim.setdefault(str(claim_id), []).append(str(fact.get("fact_id", "")))
    known_fact_claim_ids = set(fact_ids_by_claim)
    unknown = [claim_id for claim_id in selected_ids if claim_id not in known_fact_claim_ids]
    if unknown:
        raise ValueError(f"claim_ids 含未进入事实账本的主张：{', '.join(unknown)}")

    stable_facts = [item for item in facts if item.get("fact_type") != "DYN"]
    dynamic_facts = [item for item in facts if item.get("fact_type") == "DYN"]
    if selected_ids:
        selected_set = set(selected_ids)
        stable_facts = [
            item for item in stable_facts
            if selected_set.intersection(map(str, item.get("claim_ids") or []))
        ]
        dynamic_facts = [
            item for item in dynamic_facts
            if selected_set.intersection(map(str, item.get("claim_ids") or []))
        ]
    if not include_dynamic:
        dynamic_facts = []

    complete_claim_index = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        if claim_id not in known_fact_claim_ids:
            continue
        complete_claim_index.append(
            {
                "claim_id": claim_id,
                "claim_type": claim.get("claim_type"),
                "label": claim.get("label"),
                "critical": claim.get("critical"),
                "source_file_id": claim.get("source_file_id"),
                "fact_ids": fact_ids_by_claim[claim_id],
            }
        )

    if selected_ids:
        selected_set = set(selected_ids)
        claim_index = [item for item in complete_claim_index if item["claim_id"] in selected_set]
    elif index_only:
        claim_index = complete_claim_index[index_offset:index_offset + index_limit]
    else:
        claim_index = complete_claim_index

    result: dict[str, Any] = {
        "status": "prepared",
        "packet_mode": "index_only" if index_only else "claim_focused" if selected_ids else "full",
        "manifest": manifest,
        "source_count": len(sources),
        "claim_count": len(claims),
        "fact_count": len(facts),
        "stable_fact_count": sum(item.get("fact_type") != "DYN" for item in facts),
        "dynamic_fact_count": sum(item.get("fact_type") == "DYN" for item in facts),
        "returned_stable_fact_count": 0 if index_only else len(stable_facts),
        "returned_dynamic_fact_count": 0 if index_only else len(dynamic_facts),
        "omitted_fact_count": len(facts) if index_only else len(facts) - len(stable_facts) - len(dynamic_facts),
        "requested_claim_ids": selected_ids,
        "indexed_claim_count_total": len(complete_claim_index),
        "returned_claim_index_count": len(claim_index),
        "omitted_claim_index_count": len(complete_claim_index) - len(claim_index),
        "index_offset": index_offset,
        "index_limit": index_limit,
        "claim_index": claim_index,
        "unavailable_sources": [
            {
                "source_id": item.get("source_id"),
                "source_file_id": item.get("source_file_id"),
                "source_type": item.get("source_type"),
                "title": item.get("title"),
                "status": item.get("status"),
                "notes": item.get("notes"),
            }
            for item in sources
            if item.get("status") not in {"active", "read"}
        ],
    }
    if index_only:
        return result

    returned_claim_ids = {
        str(claim_id)
        for fact in stable_facts + dynamic_facts
        for claim_id in fact.get("claim_ids") or []
    }
    result["selected_claims"] = [
        {
            "claim_id": claim_id,
            "claim_type": claim_by_id[claim_id].get("claim_type"),
            "label": claim_by_id[claim_id].get("label"),
            "verbatim_text": claim_by_id[claim_id].get("verbatim_text"),
            "source_file_id": claim_by_id[claim_id].get("source_file_id"),
        }
        for claim_id in claim_by_id
        if claim_id in returned_claim_ids
    ]
    result["stable_facts"] = [
        {
            "fact_id": item.get("fact_id"),
            "statement": item.get("statement"),
            "source_id": item.get("source_id"),
            "claim_ids": item.get("claim_ids"),
            "status": item.get("status"),
            "boundary": item.get("boundary"),
        }
        for item in stable_facts
    ]
    result["dynamic_facts"] = [
        {
            "fact_id": item.get("fact_id"),
            "statement": item.get("statement"),
            "source_id": item.get("source_id"),
            "claim_ids": item.get("claim_ids"),
            "time_scope": item.get("time_scope"),
            "boundary": item.get("boundary"),
        }
        for item in dynamic_facts
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--claim-id", action="append", default=[])
    parser.add_argument("--claim-ids-file", type=Path)
    parser.add_argument("--include-dynamic", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--index-offset", type=int, default=0)
    parser.add_argument("--index-limit", type=int, default=MAX_INDEX_CLAIMS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    claim_ids = _read_claim_ids(args.claim_ids_file, args.claim_id)
    result = prepare_analysis_packet(
        args.delivery,
        claim_ids=claim_ids,
        include_dynamic=args.include_dynamic,
        index_only=args.index_only,
        index_offset=args.index_offset,
        index_limit=args.index_limit,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
