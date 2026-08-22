"""Index page-source files without drawing page or product conclusions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from product_page_common import file_sha256, now_iso, read_json, read_jsonl, write_json, write_jsonl


ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
DOCUMENT_SUFFIXES = {".pdf", ".html", ".htm", ".md", ".txt", ".json", ".csv", ".xlsx"}
VERSION_LABELS = {"current", "comparison"}
SUPPORTING_SOURCE_ROLES = {
    "product_document", "evidence_document", "user_signal", "business_context",
    "competitor_page", "optional_upstream", "unknown",
}


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    return "other"


def files_under(input_path: Path) -> tuple[Path, list[Path]]:
    resolved = input_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"页面资料不存在: {resolved}")
    if resolved.is_file():
        return resolved.parent, [resolved]
    files = sorted(
        (path for path in resolved.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(resolved).as_posix().casefold(),
    )
    if not files:
        raise ValueError("页面资料目录为空")
    return resolved, files


def is_zoned_iso(value: str) -> bool:
    text = value.strip()
    if not text or text == "unknown":
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_location(input_path: Path, delivery: Path) -> tuple[Path, Path]:
    input_resolved = input_path.expanduser().resolve()
    delivery_resolved = delivery.expanduser().resolve()
    source_root = input_resolved.parent if input_resolved.is_file() else input_resolved
    if (
        delivery_resolved == source_root
        or delivery_resolved.is_relative_to(source_root)
        or source_root.is_relative_to(delivery_resolved)
    ):
        raise ValueError("页面资料目录与交付目录不能互相包含，避免把交付文件重新索引为来源")
    return source_root, delivery_resolved


def validate_index_request(
    input_path: Path,
    delivery: Path,
    version_label: str,
    capture_time: str,
) -> dict[str, Any]:
    if version_label not in VERSION_LABELS:
        raise ValueError("version_label 只能是 current 或 comparison")
    validate_location(input_path, delivery)
    manifest_path = delivery.expanduser().resolve() / "data" / "page_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("交付目录缺少 data/page_manifest.json，请先初始化")
    manifest = read_json(manifest_path)
    if version_label == "comparison":
        if manifest.get("task") != "version_review":
            raise ValueError("comparison来源只允许加入task=version_review的交付")
        if not is_zoned_iso(capture_time):
            raise ValueError("comparison来源必须显式提供带时区的--capture-time")
    return manifest


def build_rows(
    input_path: Path,
    existing: list[dict[str, Any]],
    version_label: str,
    capture_time: str,
) -> list[dict[str, Any]]:
    if version_label not in VERSION_LABELS:
        raise ValueError("version_label 只能是 current 或 comparison")
    root, files = files_under(input_path)
    start = len(existing) + 1
    known_hashes = {
        str(row.get("sha256", "")): str(row.get("source_file_id", ""))
        for row in existing
        if row.get("sha256")
    }
    rows: list[dict[str, Any]] = []
    for offset, path in enumerate(files):
        digest = file_sha256(path)
        kind = media_type(path)
        rows.append(
            {
                "source_file_id": f"PAGE-SF-{start + offset:03d}",
                "source_version": version_label,
                "relative_path": path.relative_to(root).as_posix(),
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "media_type": kind,
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "page_scope": "unknown",
                "page_location": "unknown",
                "sequence": offset + 1,
                "sequence_status": "unverified",
                "readability_status": "unsupported_archive" if kind == "archive" else "not_reviewed",
                "quality_excluded": False,
                "quality_exclusion_reason": "",
                "capture_time": capture_time or "unknown",
                "duplicate_of": known_hashes.get(digest, ""),
                "notes": "文件顺序只按原始相对路径初始化，必须视觉核对真实页面顺序。",
            }
        )
        known_hashes.setdefault(digest, rows[-1]["source_file_id"])
    return rows


def build_unattached_plan(input_path: Path, delivery: Path, version_label: str) -> dict[str, Any]:
    if version_label not in VERSION_LABELS:
        raise ValueError("version_label 只能是 current 或 comparison")
    validate_location(input_path, delivery)
    root, files = files_under(input_path)
    inventory = delivery.resolve() / "data" / "source_inventory.jsonl"
    existing_count = len(read_jsonl(inventory)) if inventory.is_file() else 0
    return {
        "action": "index_page_sources",
        "dry_run": True,
        "source_root_name": root.name,
        "version_label": version_label,
        "new_file_count": len(files),
        "existing_file_count": existing_count,
        "target": "data/source_inventory.jsonl",
    }


def build_plan(
    input_path: Path,
    delivery: Path,
    version_label: str,
    capture_time: str = "",
) -> dict[str, Any]:
    validate_index_request(input_path, delivery, version_label, capture_time)
    return build_unattached_plan(input_path, delivery, version_label)


def index_sources(
    input_path: Path,
    delivery: Path,
    version_label: str,
    capture_time: str | None = None,
) -> list[dict[str, Any]]:
    delivery = delivery.expanduser().resolve()
    manifest = validate_index_request(
        input_path,
        delivery,
        version_label,
        capture_time or "",
    )
    manifest_path = delivery / "data" / "page_manifest.json"
    inventory = delivery / "data" / "source_inventory.jsonl"
    existing = read_jsonl(inventory) if inventory.is_file() else []
    new_rows = build_rows(
        input_path,
        existing,
        version_label,
        (capture_time or str(manifest.get("page_snapshot_time", "unknown"))).strip() or "unknown",
    )
    write_jsonl(inventory, [*existing, *new_rows])
    manifest["source_count"] = len(existing) + len(new_rows)
    manifest["updated_at"] = now_iso()
    write_json(manifest_path, manifest)
    return new_rows


def build_supporting_plan(input_path: Path, delivery: Path) -> dict[str, Any]:
    """Describe a supplemental-source indexing operation without writing files."""
    validate_location(input_path, delivery)
    root, files = files_under(input_path)
    inventory = delivery.resolve() / "data" / "supporting_source_inventory.jsonl"
    existing_count = len(read_jsonl(inventory)) if inventory.is_file() else 0
    return {
        "action": "index_supporting_sources",
        "dry_run": True,
        "source_root_name": root.name,
        "new_file_count": len(files),
        "existing_file_count": existing_count,
        "target": "data/supporting_source_inventory.jsonl",
    }


def index_supporting_sources(
    input_path: Path,
    delivery: Path,
    capture_time: str = "unknown",
    source_role: str = "unknown",
) -> list[dict[str, Any]]:
    """Index optional evidence without treating it as part of the product page."""
    if source_role not in SUPPORTING_SOURCE_ROLES:
        raise ValueError(f"source_role 必须是 {sorted(SUPPORTING_SOURCE_ROLES)} 之一")
    validate_location(input_path, delivery)
    delivery = delivery.expanduser().resolve()
    manifest_path = delivery / "data" / "page_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("交付目录缺少 data/page_manifest.json，请先初始化")
    inventory = delivery / "data" / "supporting_source_inventory.jsonl"
    existing = read_jsonl(inventory) if inventory.is_file() else []
    root, files = files_under(input_path)
    known_hashes = {
        str(row.get("sha256", "")): str(row.get("supporting_source_id", ""))
        for row in existing if row.get("sha256")
    }
    rows: list[dict[str, Any]] = []
    start = len(existing) + 1
    for offset, path in enumerate(files):
        digest = file_sha256(path)
        kind = media_type(path)
        row = {
            "supporting_source_id": f"SUP-SF-{start + offset:03d}",
            "relative_path": path.relative_to(root).as_posix(),
            "file_name": path.name,
            "extension": path.suffix.lower(),
            "media_type": kind,
            "size_bytes": path.stat().st_size,
            "sha256": digest,
            "source_role": source_role,
            "readability_status": "unsupported_archive" if kind == "archive" else "not_reviewed",
            "capture_time": capture_time.strip() or "unknown",
            "duplicate_of": known_hashes.get(digest, ""),
            "notes": "补充资料必须逐份读取并登记能证明、不能证明与适用SKU。",
        }
        rows.append(row)
        known_hashes.setdefault(digest, row["supporting_source_id"])
    write_jsonl(inventory, [*existing, *rows])
    manifest = read_json(manifest_path)
    manifest["updated_at"] = now_iso()
    write_json(manifest_path, manifest)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--version-label", choices=sorted(VERSION_LABELS), default="current")
    parser.add_argument("--capture-time", default="")
    parser.add_argument("--source-kind", choices=("page", "supporting"), default="page")
    parser.add_argument("--source-role", choices=sorted(SUPPORTING_SOURCE_ROLES), default="unknown")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        result = (
            build_supporting_plan(args.input, args.delivery)
            if args.source_kind == "supporting"
            else build_plan(args.input, args.delivery, args.version_label, args.capture_time)
        )
    else:
        rows = (
            index_supporting_sources(
                args.input, args.delivery, args.capture_time or "unknown", args.source_role
            )
            if args.source_kind == "supporting"
            else index_sources(args.input, args.delivery, args.version_label, args.capture_time or None)
        )
        result = {
            "status": "indexed",
            "new_file_count": len(rows),
            "version_label": args.version_label if args.source_kind == "page" else "not_applicable",
            "target": (
                "data/supporting_source_inventory.jsonl"
                if args.source_kind == "supporting"
                else "data/source_inventory.jsonl"
            ),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
