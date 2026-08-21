"""Build deterministic per-source claim-ledger parts from candidate selections.

Run only after every source has both claim_extract and claim_recheck trusted
events.  The model submits candidate IDs and optional type corrections; this
script owns provenance, IDs, critical flags, timestamps, and JSONL structure.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from product_value_common import read_jsonl


CLAIM_TYPES = {
    "identity",
    "sku",
    "ingredient",
    "nutrition",
    "storage",
    "warning",
    "faq",
    "usage",
    "comparison",
    "process",
    "sensory",
    "packaging",
    "origin",
    "evidence",
    "transaction",
    "audience",
    "other",
}
CRITICAL_CLAIM_TYPES = {"sku", "ingredient", "nutrition", "storage", "warning"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--candidates-dir", required=True, type=Path)
    parser.add_argument("--selections-dir", required=True, type=Path)
    parser.add_argument("--parts-dir", required=True, type=Path)
    parser.add_argument("--trusted-events", type=Path)
    parser.add_argument("--expected-source-count", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def ensure_external_work_dir(delivery: Path, work_dir: Path, label: str) -> None:
    delivery_resolved = delivery.resolve()
    work_resolved = work_dir.resolve()
    if work_resolved == delivery_resolved or work_resolved.is_relative_to(delivery_resolved):
        raise ValueError(f"{label} 必须位于正式交付目录之外")


def source_order(source_id: str) -> int:
    match = re.fullmatch(r"SF-(\d{3,})", source_id)
    if not match:
        raise ValueError(f"source_file_id 格式不正确: {source_id}")
    return int(match.group(1))


def selection_items(value: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    items = value.get("selected_claims")
    if items is None:
        items = value.get("selections")
    if not isinstance(items, list):
        raise ValueError(f"{path.name} 缺少 selected_claims 数组")
    if len(items) > 100:
        raise ValueError(f"{path.name} 的 selected_claims 超过100项")
    return items


def parse_recorded_at(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} 的 recorded_at 不是有效 ISO 时间: {text}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} 的 recorded_at 必须包含时区: {text}")
    return parsed


def main() -> int:
    args = parse_args()
    if args.expected_source_count < 1:
        raise ValueError("expected-source-count 必须大于0")
    ensure_external_work_dir(args.delivery, args.candidates_dir, "候选目录")
    ensure_external_work_dir(args.delivery, args.selections_dir, "选择目录")
    ensure_external_work_dir(args.delivery, args.parts_dir, "分包目录")

    data = args.delivery / "data"
    inventory = read_jsonl(data / "source_inventory.jsonl")
    observations = read_jsonl(data / "source_observation.jsonl")
    events_path = args.trusted_events or data / "tool_audit_events.jsonl"
    events = read_jsonl(events_path)
    inventory.sort(key=lambda row: source_order(str(row.get("source_file_id", ""))))
    if len(inventory) != args.expected_source_count:
        raise ValueError(
            f"来源数 {len(inventory)} 与 expected-source-count={args.expected_source_count} 不一致"
        )
    observation_by_source = {str(row.get("source_file_id", "")): row for row in observations}
    event_by_key = {
        (str(row.get("source_file_id", "")), str(row.get("phase", ""))): row for row in events
    }

    compiled_sources: list[tuple[str, list[dict[str, Any]]]] = []
    claim_number = 0
    for source in inventory:
        source_id = str(source.get("source_file_id", ""))
        observation = observation_by_source.get(source_id)
        extract_event = event_by_key.get((source_id, "claim_extract"))
        recheck_event = event_by_key.get((source_id, "claim_recheck"))
        if not observation or not extract_event or not recheck_event:
            raise ValueError(f"{source_id} 缺少Observation、claim_extract或claim_recheck事件")
        for phase, event in (("claim_extract", extract_event), ("claim_recheck", recheck_event)):
            if event.get("relative_path") != source.get("relative_path"):
                raise ValueError(f"{source_id} {phase} 事件的 relative_path 与来源清单不一致")
            if event.get("source_sha256") != source.get("sha256"):
                raise ValueError(f"{source_id} {phase} 事件的 source_sha256 与来源清单不一致")
        extract_at = parse_recorded_at(extract_event.get("recorded_at"), f"{source_id} claim_extract")
        recheck_at = parse_recorded_at(recheck_event.get("recorded_at"), f"{source_id} claim_recheck")
        if recheck_at <= extract_at:
            raise ValueError(f"{source_id} claim_recheck 必须晚于 claim_extract")
        try:
            extract_sequence = int(extract_event.get("sequence"))
            recheck_sequence = int(recheck_event.get("sequence"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{source_id} 可信事件 sequence 必须是整数") from exc
        if extract_sequence < 1 or recheck_sequence < 1:
            raise ValueError(f"{source_id} 可信事件 sequence 必须是正整数")
        candidate_path = args.candidates_dir / f"{source_id}.json"
        selection_path = args.selections_dir / f"{source_id}.json"
        if not candidate_path.is_file() or not selection_path.is_file():
            raise ValueError(f"{source_id} 缺少候选或选择文件")
        candidate_packet = read_json_object(candidate_path)
        selection_packet = read_json_object(selection_path)
        if candidate_packet.get("source_file_id") != source_id:
            raise ValueError(f"{candidate_path.name} 的 source_file_id 不一致")
        if selection_packet.get("source_file_id") != source_id:
            raise ValueError(f"{selection_path.name} 的 source_file_id 不一致")
        expected_bindings = {
            "observation_id": observation.get("observation_id"),
            "relative_path": source.get("relative_path"),
            "source_sha256": source.get("sha256"),
            "extract_recorded_at": extract_event.get("recorded_at"),
            "extract_sequence": extract_event.get("sequence"),
        }
        for field, expected in expected_bindings.items():
            if candidate_packet.get(field) != expected:
                raise ValueError(f"{source_id} 候选包的 {field} 与正式账本不一致")
        candidates = candidate_packet.get("candidates")
        if not isinstance(candidates, list) or candidate_packet.get("candidate_count") != len(candidates):
            raise ValueError(f"{source_id} 候选包计数不一致")
        candidate_by_id: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError(f"{source_id} 候选必须是对象")
            candidate_id = str(candidate.get("candidate_id", ""))
            if not re.fullmatch(r"CAND-\d{3,}", candidate_id) or candidate_id in candidate_by_id:
                raise ValueError(f"{source_id} 候选编号非法或重复: {candidate_id}")
            candidate_by_id[candidate_id] = candidate

        selected_rows: list[dict[str, Any]] = []
        selected_by_id: dict[str, dict[str, Any]] = {}
        for item in selection_items(selection_packet, selection_path):
            if not isinstance(item, dict):
                raise ValueError(f"{source_id} 选择项必须是对象")
            extra_fields = set(item) - {"candidate_id", "claim_type", "claim_type_override"}
            if extra_fields:
                raise ValueError(f"{source_id} 选择项含不允许字段: {sorted(extra_fields)}")
            candidate_id = str(item.get("candidate_id", ""))
            if candidate_id in selected_by_id:
                raise ValueError(f"{source_id} 重复选择候选: {candidate_id}")
            candidate = candidate_by_id.get(candidate_id)
            if candidate is None:
                raise ValueError(f"{source_id} 选择了不存在的候选: {candidate_id}")
            if "claim_type" in item and "claim_type_override" in item:
                raise ValueError(f"{source_id} {candidate_id} 不得同时提供两种类型修正字段")
            selected_by_id[candidate_id] = item

        # A visible claim carrying a footnote marker is inseparable from the
        # matching page footnote.  The model selects the business claim; the
        # compiler deterministically adds its bound footnote so a qualifier or
        # source note cannot disappear between selection and formal ledgers.
        auto_linked_ids: set[str] = set()
        for candidate_id in list(selected_by_id):
            candidate = candidate_by_id[candidate_id]
            linked_ids = candidate.get("linked_footnote_candidate_ids", [])
            if not isinstance(linked_ids, list):
                raise ValueError(f"{source_id} {candidate_id} 的脚注绑定必须是数组")
            for linked_id_value in linked_ids:
                linked_id = str(linked_id_value)
                linked = candidate_by_id.get(linked_id)
                if linked is None or linked_id == candidate_id:
                    raise ValueError(f"{source_id} {candidate_id} 引用了无效脚注候选: {linked_id}")
                if linked.get("claim_unit_kind") != "footnote":
                    raise ValueError(f"{source_id} {candidate_id} 绑定的 {linked_id} 不是脚注候选")
                auto_linked_ids.add(linked_id)
        for linked_id in auto_linked_ids:
            selected_by_id.setdefault(linked_id, {"candidate_id": linked_id})

        # 正式主张顺序只由确定性的候选顺序决定，模型返回顺序不得改变 CLM 编号。
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id", ""))
            item = selected_by_id.get(candidate_id)
            if item is None:
                continue
            claim_type = str(
                item.get("claim_type_override", item.get("claim_type", candidate.get("suggested_claim_type", "other")))
            )
            if candidate.get("claim_unit_kind") == "footnote":
                claim_type = "evidence"
            if claim_type not in CLAIM_TYPES:
                raise ValueError(f"{source_id} {candidate_id} 的 claim_type 无效: {claim_type}")
            verbatim_text = str(candidate.get("verbatim_text", "")).strip()
            locator = str(candidate.get("visual_locator", "")).strip()
            if not verbatim_text or not locator:
                raise ValueError(f"{source_id} {candidate_id} 缺少逐字原文或定位")
            claim_number += 1
            selected_rows.append(
                {
                    "claim_id": f"CLM-{claim_number:03d}",
                    "source_file_id": source_id,
                    "observation_id": str(observation.get("observation_id", "")),
                    "claim_type": claim_type,
                    "label": verbatim_text[:60],
                    "verbatim_text": verbatim_text,
                    "normalized_value": "",
                    "unit": "",
                    "visual_locator": locator,
                    "critical": claim_type in CRITICAL_CLAIM_TYPES,
                    "claim_status": "match",
                    "claimed_at": str(extract_event.get("recorded_at", "")),
                    "rechecked_at": str(recheck_event.get("recorded_at", "")),
                }
            )
        compiled_sources.append((source_id, selected_rows))

    existing_parts = list(args.parts_dir.glob("*.jsonl")) if args.parts_dir.exists() else []
    if existing_parts and not args.dry_run:
        raise FileExistsError("主张分包目录已有JSONL文件，禁止覆盖；请使用新的空目录")
    if not args.dry_run:
        args.parts_dir.mkdir(parents=True, exist_ok=True)
        for source_id, rows in compiled_sources:
            atomic_write_jsonl(args.parts_dir / f"{source_id}.jsonl", rows)

    summary = {
        "status": "dry_run" if args.dry_run else "built",
        "source_count": len(compiled_sources),
        "claim_count": claim_number,
        "parts_dir": str(args.parts_dir),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
