"""Shared helpers and schema constants for BrandBAI Value Expression."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "0.1.1"
SKILL_VERSION = "0.1.3"

ANALYSIS_STATUSES = {"draft", "complete", "partial", "insufficient", "stale"}
DELIVERY_STATUSES = {"ready", "conditional", "blocked", "stale"}
UPSTREAM_ANALYSIS_STATUSES = {"complete", "partial"}
UPSTREAM_DELIVERY_STATUSES = {"ready", "conditional"}
ACTIVE_VALUE_LAYERS = {"P0", "P1", "P2"}
ROUTES = {"数字化", "感官化", "差异化", "情境化", "证据化", "人格化"}
ROUTE_ROLES = {"primary", "supporting", "not_prioritized", "not_applicable"}
ASSET_GROUPS = {"欲望建立", "阻力解除", "氛围连接"}
SLOT_STATUSES = {"applicable", "not_applicable"}
DECISION_TASKS = {"看懂", "相信", "觉得适合", "觉得值", "选对", "知道下一步"}
CONTENT_OBJECTS = {"种草", "直播引流短视频", "挂车成交短视频", "直播间", "商品页"}
VIS_STATUSES = {
    "page_existing_unvalidated",
    "suggested_untested",
    "candidate",
    "validated",
    "blocked",
    "stale",
}
TEST_STATUSES = {"suggested", "ready", "running", "completed", "blocked", "stale"}
EXPRESSION_ORIGINS = {"upstream", "source_material"}
EXPRESSION_SOURCE_FORMS = {
    "upstream_registered",
    "detail_page",
    "packaging",
    "image",
    "video_frame",
    "original_document",
    "other",
}
EXPRESSION_STATUSES = {"inventory_pending", "page_existing_unvalidated", "stale"}

DATA_FILES = (
    "expression_manifest.json",
    "upstream_snapshot.json",
    "existing_expression_ledger.jsonl",
    "six_path_ledger.jsonl",
    "slot_scan_ledger.jsonl",
    "vis_ledger.jsonl",
    "validation_ledger.jsonl",
    "gap_ledger.jsonl",
)
REPORT_FILES = ("01_卖点可视化呈现.md", "02_资料说明与验证计划.md")
UPSTREAM_FILES = (
    "product_manifest.json",
    "fact_ledger.jsonl",
    "fabe_ledger.jsonl",
    "anchor_ledger.jsonl",
    "value_ledger.jsonl",
    "p0_decision.json",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def value_expression_id(product_value_id: str, output_version: str = "V1") -> str:
    normalized = f"{product_value_id.strip().casefold()}|{output_version.strip().casefold()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"VE-{digest}"


def normalize_output_version(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not re.fullmatch(r"V[1-9]\d*", normalized):
        raise ValueError("output_version 必须使用 V1、V2、V3 等正整数版本")
    return normalized


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def upstream_paths(product_value_delivery: Path) -> dict[str, Path]:
    data = product_value_delivery / "data"
    return {
        "manifest": data / "product_manifest.json",
        "facts": data / "fact_ledger.jsonl",
        "fabe": data / "fabe_ledger.jsonl",
        "anchors": data / "anchor_ledger.jsonl",
        "values": data / "value_ledger.jsonl",
        "decision": data / "p0_decision.json",
    }


def delivery_paths(delivery: Path) -> dict[str, Path]:
    data = delivery / "data"
    return {
        "manifest": data / "expression_manifest.json",
        "upstream": data / "upstream_snapshot.json",
        "existing": data / "existing_expression_ledger.jsonl",
        "paths": data / "six_path_ledger.jsonl",
        "slots": data / "slot_scan_ledger.jsonl",
        "vis": data / "vis_ledger.jsonl",
        "validation": data / "validation_ledger.jsonl",
        "gaps": data / "gap_ledger.jsonl",
        "report_01": delivery / REPORT_FILES[0],
        "report_02": delivery / REPORT_FILES[1],
    }
