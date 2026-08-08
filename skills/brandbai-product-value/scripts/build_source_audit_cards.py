"""Build immutable SVG audit cards that bind image pixels to source identity."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import re
import struct
import textwrap
from pathlib import Path
from typing import Any

from product_value_common import delivery_paths, read_jsonl, write_jsonl


CARD_DIR_NAME = "source_audit_cards"
DISPLAY_WIDTH = 1300


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_root(input_path: Path) -> Path:
    resolved = input_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"输入路径不存在: {resolved}")
    return resolved.parent if resolved.is_file() else resolved


def source_path(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(relative_path)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"来源路径越界: {relative_path}")
    return candidate


def wrapped_tspans(value: str, width: int = 38, max_lines: int = 4) -> list[str]:
    lines = textwrap.wrap(value, width=width, break_long_words=True, break_on_hyphens=False) or [value]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…" if lines[-1] else "…"
    return lines


def jpeg_dimensions(value: bytes) -> tuple[int, int] | None:
    if len(value) < 4 or value[:2] != b"\xff\xd8":
        return None
    offset = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(value):
        if value[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(value) and value[offset] == 0xFF:
            offset += 1
        if offset >= len(value):
            break
        marker = value[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA or offset + 2 > len(value):
            break
        segment_length = int.from_bytes(value[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(value):
            break
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(value[offset + 3 : offset + 5], "big")
            width = int.from_bytes(value[offset + 5 : offset + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        offset += segment_length
    return None


def svg_dimensions(value: bytes) -> tuple[int, int] | None:
    try:
        head = value[:8192].decode("utf-8", errors="ignore")
    except UnicodeError:
        return None
    width_match = re.search(r"\bwidth\s*=\s*['\"]([0-9.]+)", head, re.IGNORECASE)
    height_match = re.search(r"\bheight\s*=\s*['\"]([0-9.]+)", head, re.IGNORECASE)
    if width_match and height_match:
        width = int(float(width_match.group(1)))
        height = int(float(height_match.group(1)))
        return (width, height) if width > 0 and height > 0 else None
    view_box = re.search(
        r"\bviewBox\s*=\s*['\"]\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)",
        head,
        re.IGNORECASE,
    )
    if view_box:
        width = int(float(view_box.group(1)))
        height = int(float(view_box.group(2)))
        return (width, height) if width > 0 and height > 0 else None
    return None


def webp_dimensions(value: bytes) -> tuple[int, int] | None:
    if len(value) < 30 or value[:4] != b"RIFF" or value[8:12] != b"WEBP":
        return None
    kind = value[12:16]
    if kind == b"VP8X":
        width = 1 + int.from_bytes(value[24:27], "little")
        height = 1 + int.from_bytes(value[27:30], "little")
        return width, height
    if kind == b"VP8 " and len(value) >= 30:
        marker = value.find(b"\x9d\x01\x2a", 20, 40)
        if marker >= 0 and marker + 7 <= len(value):
            width, height = struct.unpack_from("<HH", value, marker + 3)
            return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L" and len(value) >= 25 and value[20] == 0x2F:
        bits = int.from_bytes(value[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def image_dimensions(media_type: str, value: bytes) -> tuple[int, int]:
    dimensions: tuple[int, int] | None = None
    if media_type == "image/png" and len(value) >= 24 and value[:8] == b"\x89PNG\r\n\x1a\n":
        dimensions = (int.from_bytes(value[16:20], "big"), int.from_bytes(value[20:24], "big"))
    elif media_type in {"image/jpeg", "image/jpg"}:
        dimensions = jpeg_dimensions(value)
    elif media_type == "image/gif" and len(value) >= 10 and value[:3] == b"GIF":
        dimensions = struct.unpack_from("<HH", value, 6)
    elif media_type == "image/webp":
        dimensions = webp_dimensions(value)
    elif media_type == "image/svg+xml":
        dimensions = svg_dimensions(value)
    if dimensions and dimensions[0] > 0 and dimensions[1] > 0:
        return dimensions
    return 1300, 1640


def build_svg(row: dict[str, Any], source_bytes: bytes) -> bytes:
    source_file_id = str(row["source_file_id"])
    relative_path = str(row["relative_path"])
    media_type = str(row["media_type"])
    source_sha256 = str(row["sha256"])
    source_width, source_height = image_dimensions(media_type, source_bytes)
    display_height = max(1, math.ceil(source_height * DISPLAY_WIDTH / source_width))
    if source_width > 100000 or source_height > 200000 or display_height > 200000:
        raise ValueError(
            f"{source_file_id} 的图片尺寸过大，无法生成可安全滚动的审计卡；请先按页面自然段无损拆图后重新建账"
        )
    card_height = 460 + display_height
    metadata = html.escape(
        json.dumps(
            {
                "source_file_id": source_file_id,
                "relative_path": relative_path,
                "source_sha256": source_sha256,
                "media_type": media_type,
                "source_width": source_width,
                "source_height": source_height,
                "display_width": DISPLAY_WIDTH,
                "display_height": display_height,
                "card_height": card_height,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    path_lines = wrapped_tspans(relative_path)
    tspans = []
    for index, line in enumerate(path_lines):
        dy = "0" if index == 0 else "38"
        tspans.append(f'<tspan x="48" dy="{dy}">{html.escape(line)}</tspan>')
    encoded = base64.b64encode(source_bytes).decode("ascii")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="{card_height}" viewBox="0 0 1400 {card_height}">
  <metadata id="brandbai-source-audit">{metadata}</metadata>
  <rect width="1400" height="{card_height}" fill="#f8f4ea"/>
  <rect x="0" y="0" width="1400" height="360" fill="#2d1712"/>
  <text x="48" y="70" fill="#f4ca68" font-family="Arial, Microsoft YaHei, sans-serif" font-size="34" font-weight="700">BrandBAI EXACT-FILE AUDIT CARD</text>
  <text x="48" y="132" fill="#ffffff" font-family="Arial, Microsoft YaHei, sans-serif" font-size="50" font-weight="700">{html.escape(source_file_id)}</text>
  <text x="48" y="190" fill="#ffffff" font-family="Arial, Microsoft YaHei, sans-serif" font-size="25">{''.join(tspans)}</text>
  <text x="48" y="330" fill="#d8c8bd" font-family="Consolas, monospace" font-size="20">SHA-256 {source_sha256}</text>
  <rect x="30" y="390" width="1340" height="{display_height + 40}" rx="12" fill="#ffffff" stroke="#7d5b4d" stroke-width="4"/>
  <image x="50" y="410" width="{DISPLAY_WIDTH}" height="{display_height}" preserveAspectRatio="none" href="data:{html.escape(media_type)};base64,{encoded}"/>
</svg>
"""
    return svg.encode("utf-8")


def build_cards(input_path: Path, delivery: Path, write: bool = True) -> dict[str, Any]:
    paths = delivery_paths(delivery)
    inventory_path = paths["source_inventory"]
    ledger_path = paths["audit_card_ledger"]
    cards_dir = paths["audit_cards_dir"]
    if not inventory_path.is_file() or not ledger_path.is_file():
        raise FileNotFoundError("交付目录未初始化或缺少来源清单/审计卡台账")
    inventory = read_jsonl(inventory_path)
    if not inventory:
        raise ValueError("source_inventory.jsonl 为空；请先建立来源清单")
    if read_jsonl(ledger_path):
        raise FileExistsError("source_audit_card_ledger.jsonl 已有内容；为防止审计身份漂移，拒绝覆盖")
    if cards_dir.exists() and any(cards_dir.iterdir()):
        raise FileExistsError(f"审计卡目录非空，拒绝覆盖: {cards_dir}")

    root = source_root(input_path)
    rows: list[dict[str, Any]] = []
    card_payloads: list[tuple[Path, bytes]] = []
    for item in inventory:
        source_file_id = str(item["source_file_id"])
        relative_path = str(item["relative_path"])
        media_type = str(item["media_type"])
        original = source_path(root, relative_path)
        if not original.is_file():
            raise FileNotFoundError(f"来源文件不存在: {original}")
        actual_sha256 = sha256_file(original)
        if actual_sha256 != item.get("sha256"):
            raise ValueError(f"{source_file_id} 的原文件 SHA-256 已变化，拒绝生成审计卡")

        if media_type.startswith("image/"):
            relative_card = f"{CARD_DIR_NAME}/{source_file_id}.svg"
            payload = build_svg(item, original.read_bytes())
            card_sha256 = sha256_bytes(payload)
            card_payloads.append((cards_dir / f"{source_file_id}.svg", payload))
            status = "ready"
        else:
            relative_card = ""
            card_sha256 = ""
            status = "not_applicable"
        rows.append(
            {
                "source_file_id": source_file_id,
                "relative_path": relative_path,
                "source_sha256": actual_sha256,
                "media_type": media_type,
                "audit_card_path": relative_card,
                "audit_card_sha256": card_sha256,
                "status": status,
            }
        )

    if write:
        cards_dir.mkdir(parents=True, exist_ok=True)
        for path, payload in card_payloads:
            path.write_bytes(payload)
        write_jsonl(ledger_path, rows)

    return {
        "status": "built" if write else "dry_run",
        "input": str(input_path.resolve()),
        "delivery": str(delivery.resolve()),
        "source_files": len(rows),
        "audit_cards": len(card_payloads),
        "ledger": str(ledger_path),
        "cards_dir": str(cards_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_cards(args.input, args.delivery, write=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
