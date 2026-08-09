"""Shared helpers and schema constants for BrandBAI Product Value."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "0.1.5"
SKILL_VERSION = "0.1.9"

INPUT_MODES = {
    "link",
    "page",
    "document",
    "image",
    "spreadsheet",
    "packaging",
    "evidence",
    "feedback",
    "mixed",
    "incremental",
}
FC_LEVELS = {"FC0", "FC1", "FC2", "FC3"}
SC_LEVELS = {"SC0", "SC1", "SC2", "SC3"}
PKG_LEVELS = {"PKG-L0", "PKG-L1", "PKG-L2", "PKG-L3", "PKG-L4"}
ANALYSIS_STATUSES = {"draft", "complete", "partial", "insufficient", "stale"}
DELIVERY_STATUSES = {"ready", "conditional", "blocked", "stale"}
SKU_STATUSES = {"confirmed", "partial", "unverified"}
FACT_TYPES = {"F-PAGE", "F-EVIDENCE", "STRAT", "DYN", "U", "EX", "H"}
VALUE_LAYERS = {"P0", "P1", "P2", "deferred"}
READINESS_LEVELS = {"ready", "conditional", "blocked"}
GAP_PRIORITIES = {"P0", "P1", "P2", "P3"}
P0_STATUSES = {
    "P0-CANDIDATE",
    "P0-HYPOTHESIS",
    "P0-SELECTED",
    "P0-VALIDATING",
    "P0-BOUNDARY-VALIDATED",
    "P0-REOPEN",
    "P0-REPLACED",
    "P0-STOPPED",
}

DATA_FILES = (
    "product_manifest.json",
    "source_inventory.jsonl",
    "source_audit_card_ledger.jsonl",
    "source_observation.jsonl",
    "source_claim_ledger.jsonl",
    "source_ledger.jsonl",
    "fact_ledger.jsonl",
    "fabe_ledger.jsonl",
    "anchor_ledger.jsonl",
    "value_ledger.jsonl",
    "p0_decision.json",
    "gap_ledger.jsonl",
)
REPORT_FILES = ("01_商品价值底座.md", "02_资料说明与缺口.md")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def product_value_id(brand: str, product: str, sku: str) -> str:
    normalized = "|".join(part.strip().casefold() for part in (brand, product, sku))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"PV-{digest}"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} 第 {line_number} 行不是有效 JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path.name} 第 {line_number} 行必须是 JSON 对象")
            rows.append(value)
    return rows


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value.rstrip() + "\n")


def md(value: Any, empty: str = "未提供") -> str:
    if value is None or value == "":
        return empty
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        if not value:
            return empty
        value = "、".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def bullet_lines(values: Iterable[Any], empty: str = "暂无") -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def delivery_paths(delivery: Path) -> dict[str, Path]:
    data = delivery / "data"
    return {
        "manifest": data / "product_manifest.json",
        "source_inventory": data / "source_inventory.jsonl",
        "audit_card_ledger": data / "source_audit_card_ledger.jsonl",
        "audit_cards_dir": data / "source_audit_cards",
        "source_observations": data / "source_observation.jsonl",
        "source_claims": data / "source_claim_ledger.jsonl",
        "sources": data / "source_ledger.jsonl",
        "facts": data / "fact_ledger.jsonl",
        "fabe": data / "fabe_ledger.jsonl",
        "anchors": data / "anchor_ledger.jsonl",
        "values": data / "value_ledger.jsonl",
        "decision": data / "p0_decision.json",
        "gaps": data / "gap_ledger.jsonl",
        "report_01": delivery / REPORT_FILES[0],
        "report_02": delivery / REPORT_FILES[1],
    }
