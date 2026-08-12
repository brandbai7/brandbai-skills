"""Create an immutable file inventory before analyzing local product materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from product_value_common import delivery_paths, read_jsonl, write_jsonl


DERIVED_PAGE_FILENAME_RE = re.compile(r"^page[_-]?(\d{1,5})\.(?:png|jpe?g|webp)$", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(input_path: Path, delivery: Path) -> list[tuple[Path, str]]:
    input_path = input_path.resolve()
    delivery = delivery.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入路径不存在: {input_path}")

    if input_path.is_file():
        return [(input_path, input_path.name)]

    files: list[tuple[Path, str]] = []
    for candidate in input_path.rglob("*"):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved == delivery or delivery in resolved.parents:
            continue
        relative = candidate.relative_to(input_path).as_posix()
        files.append((candidate, relative))
    return sorted(files, key=lambda item: (item[1].casefold(), item[1]))


def build_inventory(input_path: Path, delivery: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (path, relative_path) in enumerate(source_files(input_path, delivery), start=1):
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        rows.append(
            {
                "source_file_id": f"SF-{index:03d}",
                "filename": path.name,
                "relative_path": relative_path,
                "media_type": media_type,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "status": "indexed",
            }
        )
    pdf_rows = [row for row in rows if row["media_type"] == "application/pdf"]
    derived_page_rows = [row for row in rows if DERIVED_PAGE_FILENAME_RE.match(row["filename"])]
    page_numbers = sorted(
        int(DERIVED_PAGE_FILENAME_RE.match(row["filename"]).group(1))
        for row in derived_page_rows
    )
    if len(pdf_rows) == 1 and len(derived_page_rows) >= 10 and page_numbers == list(range(1, len(page_numbers) + 1)):
        parent_source_file_id = pdf_rows[0]["source_file_id"]
        for row in derived_page_rows:
            row["parent_source_file_id"] = parent_source_file_id
    return rows


def index_sources(input_path: Path, delivery: Path, write: bool = True) -> dict[str, Any]:
    inventory_path = delivery_paths(delivery)["source_inventory"]
    if not inventory_path.is_file():
        raise FileNotFoundError(f"交付目录尚未初始化，缺少: {inventory_path}")
    existing = read_jsonl(inventory_path)
    if existing:
        raise FileExistsError("source_inventory.jsonl 已有内容；为防止来源身份漂移，拒绝覆盖")

    rows = build_inventory(input_path, delivery)
    result = {
        "status": "indexed" if write else "dry_run",
        "input": str(input_path.resolve()),
        "delivery": str(delivery.resolve()),
        "file_count": len(rows),
        "files": [
            {
                "source_file_id": row["source_file_id"],
                "relative_path": row["relative_path"],
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
            }
            for row in rows
        ],
    }
    if write:
        write_jsonl(inventory_path, rows)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = index_sources(args.input, args.delivery, write=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
