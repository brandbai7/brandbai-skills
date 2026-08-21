"""Build deterministic source-ledger parts from audited inventory and observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_value_common import read_json, read_jsonl


ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def source_type_for(source: dict[str, Any]) -> str:
    relative_path = str(source.get("relative_path", ""))
    suffix = Path(relative_path).suffix.lower()
    media_type = str(source.get("media_type", "")).lower()
    if suffix in IMAGE_SUFFIXES or media_type.startswith("image/"):
        return "product_page_image"
    if suffix in VIDEO_SUFFIXES or media_type.startswith("video/"):
        return "product_video"
    if suffix in SPREADSHEET_SUFFIXES or "spreadsheet" in media_type or "csv" in media_type:
        return "product_parameter_sheet"
    if suffix in {".md", ".txt"} or media_type.startswith("text/"):
        return "product_document"
    if suffix == ".pdf" or media_type == "application/pdf":
        return "product_document"
    return "product_source_file"


def is_archive_source(source: dict[str, Any]) -> bool:
    suffix = Path(str(source.get("relative_path", ""))).suffix.lower()
    media_type = str(source.get("media_type", "")).lower()
    return suffix in ARCHIVE_SUFFIXES or any(token in media_type for token in ("zip", "compressed", "archive"))


def locator_suffix(observation: dict[str, Any]) -> str:
    method = str(observation.get("inspection_method", ""))
    return {
        "visual_stamped_card": "带身份审计卡",
        "structured_spreadsheet": "结构化表格读取",
        "trusted_claim_extract": "受信来源读取",
        "trusted_source_reader": "受信来源读取",
        "archive_container": "容器清单",
    }.get(method, method or "逐文件核对记录")


def build_source_rows(delivery: Path) -> list[dict[str, Any]]:
    data = delivery / "data"
    manifest = read_json(data / "product_manifest.json")
    inventory = read_jsonl(data / "source_inventory.jsonl")
    observations = read_jsonl(data / "source_observation.jsonl")
    observations_by_source: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        observations_by_source.setdefault(str(observation.get("source_file_id", "")), []).append(observation)

    rows: list[dict[str, Any]] = []
    for source in inventory:
        if is_archive_source(source):
            continue
        source_file_id = str(source.get("source_file_id", ""))
        matches = observations_by_source.get(source_file_id, [])
        if len(matches) != 1:
            raise ValueError(f"{source_file_id} 必须恰好绑定一条 Observation，实际 {len(matches)} 条")
        observation = matches[0]
        title = str(observation.get("title", "")).strip()
        relative_path = str(source.get("relative_path", "")).strip()
        captured_at = str(observation.get("inspected_at", "")).strip() or str(manifest.get("updated_at", "")).strip()
        if not title or not relative_path or not captured_at:
            raise ValueError(f"{source_file_id} 缺少 title、relative_path 或 captured_at")
        inspected = observation.get("inspection_status") == "inspected"
        if inspected:
            status = "active"
            notes = "依据逐文件核对记录建账；仅表示当前资料可读取，不自动证明页面主张正确。"
        else:
            status = "unavailable"
            notes = "当前环境不可读或不适用；仅保留来源身份，不代表来源没有内容。"
        rows.append(
            {
                "source_id": f"SRC-{len(rows) + 1:03d}",
                "source_file_id": source_file_id,
                "observation_id": str(observation.get("observation_id", "")),
                "source_type": source_type_for(source),
                "title": title,
                "locator": f"{relative_path}｜{locator_suffix(observation)}",
                "captured_at": captured_at,
                "sku_scope": str(manifest.get("sku", "")).strip(),
                "status": status,
                "notes": notes,
            }
        )
    return rows


def build_source_parts(
    delivery: Path,
    parts_dir: Path,
    *,
    dry_run: bool = False,
    rebuild: bool = False,
) -> dict[str, Any]:
    delivery = delivery.resolve()
    parts_dir = parts_dir.resolve()
    if not (delivery / "data").is_dir():
        raise ValueError("交付目录缺少 data/")
    if _is_within(parts_dir, delivery):
        raise ValueError("来源分包目录必须位于正式交付目录之外")
    rows = build_source_rows(delivery)
    if dry_run:
        return {"status": "dry_run", "source_count": len(rows), "parts_dir": str(parts_dir)}

    parts_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(path for path in parts_dir.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".jsonl"})
    if existing and not rebuild:
        raise FileExistsError("来源分包目录已有 JSON/JSONL；如需确定性重建请显式使用 --rebuild")
    if rebuild:
        for path in existing:
            path.unlink()
    for row in rows:
        output_path = parts_dir / f"{row['source_id']}.jsonl"
        output_path.write_text(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"status": "built", "source_count": len(rows), "part_count": len(rows), "parts_dir": str(parts_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--parts-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    result = build_source_parts(args.delivery, args.parts_dir, dry_run=args.dry_run, rebuild=args.rebuild)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
