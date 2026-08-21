"""Compile trusted per-source observation notes into the formal observation ledger.

The model is responsible for visual judgement.  This script is responsible for
deterministic structure, provenance checks, tag normalisation, and atomic output.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from product_value_common import read_jsonl


ALLOWED_FLAG_ORDER = (
    "identity",
    "sku",
    "ingredient",
    "nutrition_table",
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
)
ALLOWED_FLAGS = set(ALLOWED_FLAG_ORDER)

FLAG_KEYWORDS = {
    "identity": ("brand", "logo", "品牌", "君乐宝", "简醇", "产品名"),
    "sku": ("sku", "spec_quantity", "规格", "净含量", "当前选中", "当前选择"),
    "ingredient": ("ingredient", "配料表", "配料：", "配料:"),
    "nutrition_table": ("nutrition_table", "营养成分表"),
    "storage": ("storage", "储存", "贮存", "冷藏", "保鲜", "冰袋", "保质期"),
    "warning": ("warning", "警示", "注意", "禁忌", "不适宜", "过敏"),
    "faq": ("faq", "问答", "问题", "答疑"),
    "usage": ("usage", "食用", "饮用", "搭配", "吃法", "用法", "场景"),
    "comparison": ("comparison", "对比", "相比", "高于", "降低", "提升", "柱状图", "bar_chart"),
    "process": ("process", "工艺", "发酵", "生产", "菌种", "牧场"),
    "sensory": ("sensory", "口感", "风味", "醇", "甜", "香", "顺滑"),
    "packaging": ("packaging", "包装", "产品展示", "product_show", "product_showcase", "开箱"),
    "origin": ("origin", "产地", "原产", "奶源", "牧场"),
    "evidence": ("evidence", "认证", "检测", "报告", "证书", "徽章", "credential", "certification"),
    "transaction": (
        "transaction",
        "优惠",
        "满",
        "赠",
        "会员",
        "价格",
        "发货",
        "售后",
        "promotion",
        "sales_claim",
        "gift_offer",
        "taojinbi",
    ),
    "audience": ("audience", "人群", "儿童", "老人", "健身", "代言人", "endorser", "celebrity"),
}

REQUIRED_FIRST = {
    "source_file_id",
    "relative_path",
    "recorded_at",
    "sequence",
    "audit_card_sha256",
    "visible_title",
    "verbatim_excerpt",
    "text_density",
    "content_flags",
    "visual_summary",
    "uncertainty",
}
REQUIRED_SECOND = {
    "source_file_id",
    "relative_path",
    "recorded_at",
    "sequence",
    "audit_card_sha256",
    "second_pass_heading",
    "second_pass_excerpt",
    "second_pass_status",
    "comparison_note",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--first-notes", required=True, type=Path)
    parser.add_argument("--second-notes", required=True, type=Path)
    parser.add_argument("--reconciliation-notes", type=Path)
    parser.add_argument("--trusted-events", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_note(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    matches = list(re.finditer(r"(?m)^#{1,6}\s+([A-Za-z0-9_]+)\s*$", text))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if key in result:
            raise ValueError(f"{path.name} 字段重复: {key}")
        result[key] = text[start:end].strip()
    if not result:
        raise ValueError(f"{path.name} 未找到 Markdown 字段标题")
    return result


def load_notes(directory: Path, required: set[str]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.md")):
        row = parse_note(path)
        missing = sorted(required.difference(row))
        if missing:
            raise ValueError(f"{path.name} 缺少字段: {', '.join(missing)}")
        source_id = row["source_file_id"].strip()
        if path.stem != source_id:
            raise ValueError(f"{path.name} 与 source_file_id={source_id} 不一致")
        if source_id in rows:
            raise ValueError(f"{source_id} 存在重复笔记")
        rows[source_id] = row
    return rows


def iso_datetime(value: str, label: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} 不是 ISO 时间: {value}") from exc
    return value


def int_value(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} 必须是整数: {value}") from exc
    if parsed < 1:
        raise ValueError(f"{label} 必须大于 0")
    return parsed


def normalise_flags(raw: str, context: str, density: str) -> list[str]:
    if density == "none":
        return []
    tokens = [part.strip() for part in re.split(r"[\n,，;；|]+", raw) if part.strip()]
    haystack = " ".join(tokens + [context]).casefold()
    flags = [
        flag
        for flag, keywords in FLAG_KEYWORDS.items()
        if any(keyword.casefold() in haystack for keyword in keywords)
    ]
    flags = sorted(set(flags), key=lambda item: ALLOWED_FLAG_ORDER.index(item) if item in ALLOWED_FLAGS else 999)
    if not flags:
        flags = ["other"]
    return flags


def event_key(event: dict[str, Any]) -> tuple[str, str]:
    return str(event.get("phase", "")), str(event.get("source_file_id", ""))


def validate_visual_packets(
    inventory: list[dict[str, Any]],
    audit_cards: list[dict[str, Any]],
    events: list[dict[str, Any]],
    first_notes: dict[str, dict[str, str]],
    second_notes: dict[str, dict[str, str]],
    reconciliations: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    images = [row for row in inventory if str(row.get("media_type", "")).startswith("image/")]
    image_ids = [str(row["source_file_id"]) for row in images]
    if set(first_notes) != set(image_ids) or set(second_notes) != set(image_ids):
        raise ValueError("正序/倒序笔记必须与图片来源一一对应")
    cards = {str(row["source_file_id"]): row for row in audit_cards}
    by_event: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = event_key(event)
        if key in by_event:
            raise ValueError(f"审计事件重复: {key}")
        by_event[key] = event

    first_order: list[tuple[int, str]] = []
    second_order: list[tuple[int, str]] = []
    for source in images:
        source_id = str(source["source_file_id"])
        first = first_notes[source_id]
        second = second_notes[source_id]
        card = cards.get(source_id)
        if not card or card.get("status") != "ready":
            raise ValueError(f"{source_id} 缺少 ready 审计卡")
        for phase, note in (("visual_first", first), ("visual_second", second)):
            event = by_event.get((phase, source_id))
            if not event:
                raise ValueError(f"{source_id} 缺少 {phase} 可信审计事件")
            for field in ("relative_path", "recorded_at", "audit_card_sha256"):
                if str(note[field]).strip() != str(event.get(field, "")).strip():
                    raise ValueError(f"{source_id} {phase} 的 {field} 与可信事件不一致")
            sequence = int_value(note["sequence"], f"{source_id} {phase} sequence")
            if sequence != int(event.get("sequence", 0)):
                raise ValueError(f"{source_id} {phase} 的 sequence 与可信事件不一致")
        if first["relative_path"] != source["relative_path"] or second["relative_path"] != source["relative_path"]:
            raise ValueError(f"{source_id} 的 relative_path 与来源清单不一致")
        if first["audit_card_sha256"] != card["audit_card_sha256"]:
            raise ValueError(f"{source_id} 的审计卡哈希不一致")
        second_status = second["second_pass_status"].strip()
        if second_status not in {"match", "mismatch"}:
            raise ValueError(f"{source_id} 逆序复核状态无效: {second_status}")
        reconciliation = reconciliations.get(source_id)
        if second_status == "mismatch":
            if not reconciliation:
                raise ValueError(f"{source_id} 逆序复核为 mismatch，但缺少第三次仲裁记录")
            if reconciliation.get("final_status", "").strip() != "match_after_correction":
                raise ValueError(f"{source_id} 第三次仲裁未解决，不得写入正式观察账本")
            expected_values = {
                "relative_path": source["relative_path"],
                "first_pass_sequence": first["sequence"],
                "second_pass_sequence": second["sequence"],
                "audit_card_sha256": card["audit_card_sha256"],
            }
            for field, expected_value in expected_values.items():
                if reconciliation.get(field, "").strip() != str(expected_value).strip():
                    raise ValueError(f"{source_id} 仲裁记录的 {field} 不一致")
        elif reconciliation:
            raise ValueError(f"{source_id} 原逆序复核已 match，不应额外生成仲裁记录")
        first_order.append((int(first["sequence"]), source_id))
        second_order.append((int(second["sequence"]), source_id))

    if [source_id for _, source_id in sorted(first_order)] != image_ids:
        raise ValueError("正序初检必须按来源清单图片顺序执行")
    if [source_id for _, source_id in sorted(second_order)] != list(reversed(image_ids)):
        raise ValueError("倒序复核必须按来源清单图片逆序执行")
    expected = list(range(1, len(image_ids) + 1))
    if sorted(sequence for sequence, _ in first_order) != expected:
        raise ValueError("正序初检 sequence 必须连续")
    if sorted(sequence for sequence, _ in second_order) != expected:
        raise ValueError("倒序复核 sequence 必须连续")
    return images, cards


def visual_observation(
    source: dict[str, Any],
    first: dict[str, str],
    second: dict[str, str],
    reconciliation: dict[str, str] | None,
) -> dict[str, Any]:
    source_id = str(source["source_file_id"])
    density = first["text_density"].strip().lower()
    if density not in {"none", "low", "medium", "high"}:
        raise ValueError(f"{source_id} 的 text_density 无效: {density}")
    # Claim obligations may only be triggered by the model's explicit page flag
    # or by transcribed visible text.  Analyst summaries and uncertainty notes
    # can contain words such as "comparison" that are not themselves page text.
    context = " ".join((first["visible_title"], first["verbatim_excerpt"]))
    final_heading = reconciliation["final_heading"].strip() if reconciliation else first["visible_title"].strip()
    final_excerpt = reconciliation["final_excerpt"].strip() if reconciliation else first["verbatim_excerpt"].strip()
    return {
        "observation_id": f"OBS-{int(source_id.split('-')[1]):03d}",
        "source_file_id": source_id,
        "relative_path": source["relative_path"],
        "content_type": "visual_stamped_card",
        "title": final_heading or source["filename"],
        "visible_heading": final_heading or source["filename"],
        "visible_text_excerpt": final_excerpt,
        "inspection_method": "visual_stamped_card",
        "inspection_status": "inspected",
        "inspected_at": iso_datetime(first["recorded_at"], f"{source_id} first recorded_at"),
        "audit_card_sha256": first["audit_card_sha256"].strip(),
        "first_pass_sequence": int_value(first["sequence"], f"{source_id} first sequence"),
        "second_pass_sequence": int_value(second["sequence"], f"{source_id} second sequence"),
        "second_pass_heading": final_heading or second["second_pass_heading"].strip(),
        "second_pass_excerpt": final_excerpt or second["second_pass_excerpt"].strip(),
        "second_pass_status": "match",
        "second_pass_at": iso_datetime(second["recorded_at"], f"{source_id} second recorded_at"),
        "text_density": density,
        "content_flags": normalise_flags(first["content_flags"], context, density),
    }


def xlsx_text(path: Path) -> tuple[str, str, list[str]]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", namespace):
                shared.append("".join(node.text or "" for node in item.findall(".//m:t", namespace)).strip())
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {node.attrib["Id"]: node.attrib["Target"] for node in rels}
        sheet_names: list[str] = []
        values: list[str] = []
        for sheet in workbook.findall("m:sheets/m:sheet", namespace):
            sheet_names.append(sheet.attrib.get("name", ""))
            target = rel_map.get(sheet.attrib.get(f"{{{namespace['r']}}}id", ""), "")
            member = "xl/" + target.lstrip("/")
            if member not in archive.namelist() and target.startswith("/xl/"):
                member = target.lstrip("/")
            if member not in archive.namelist():
                continue
            xml = ET.fromstring(archive.read(member))
            for cell in xml.findall(".//m:c", namespace):
                value = cell.find("m:v", namespace)
                if value is None or value.text is None:
                    inline = cell.find("m:is", namespace)
                    text = "" if inline is None else "".join(node.text or "" for node in inline.findall(".//m:t", namespace))
                elif cell.attrib.get("t") == "s":
                    index = int(value.text)
                    text = shared[index] if 0 <= index < len(shared) else ""
                else:
                    text = value.text
                text = str(text).strip()
                if text and text not in values:
                    values.append(text)
                if len(values) >= 80:
                    break
    title = "、".join(name for name in sheet_names if name) or path.stem
    excerpt = ";".join(values[:40])[:3000]
    return title, excerpt, values


def text_source_observation(source: dict[str, Any], source_path: Path, inspected_at: str) -> dict[str, Any]:
    source_id = str(source["source_file_id"])
    media_type = str(source.get("media_type", ""))
    if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        heading, excerpt, values = xlsx_text(source_path)
        content_type = "structured_spreadsheet"
        method = "structured_spreadsheet"
        title = source["filename"]
        density = "high" if len(values) >= 20 else "medium" if values else "none"
    else:
        text = source_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        nonempty = [line.strip() for line in text.splitlines() if line.strip()]
        first_heading = next((re.sub(r"^#+\s*", "", line) for line in nonempty if line.startswith("#")), source["filename"])
        heading = first_heading
        excerpt = " ".join(nonempty)[:3000]
        values = nonempty
        content_type = "document_text"
        method = "document_text"
        title = first_heading or source["filename"]
        density = "high" if len(text) >= 1500 else "medium" if text.strip() else "none"
    return {
        "observation_id": f"OBS-{int(source_id.split('-')[1]):03d}",
        "source_file_id": source_id,
        "relative_path": source["relative_path"],
        "content_type": content_type,
        "title": title,
        "visible_heading": heading,
        "visible_text_excerpt": excerpt or "未读取到非空内容",
        "inspection_method": method,
        "inspection_status": "inspected" if excerpt else "unreadable",
        "inspected_at": inspected_at,
        "audit_card_sha256": "",
        "first_pass_sequence": 0,
        "second_pass_sequence": 0,
        "second_pass_heading": "",
        "second_pass_excerpt": "",
        "second_pass_status": "not_applicable",
        "second_pass_at": "",
        "text_density": density,
        "content_flags": normalise_flags("", excerpt, density),
    }


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, suffix=".tmp") as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    data = args.delivery / "data"
    inventory = read_jsonl(data / "source_inventory.jsonl")
    audit_cards = read_jsonl(data / "source_audit_card_ledger.jsonl")
    events = read_jsonl(args.trusted_events)
    first_notes = load_notes(args.first_notes, REQUIRED_FIRST)
    second_notes = load_notes(args.second_notes, REQUIRED_SECOND)
    reconciliation_required = {
        "source_file_id",
        "relative_path",
        "reviewed_at",
        "first_pass_sequence",
        "second_pass_sequence",
        "audit_card_sha256",
        "final_heading",
        "final_excerpt",
        "final_status",
        "correction_basis",
        "corrected_fields",
        "reconciliation_note",
    }
    reconciliations = (
        load_notes(args.reconciliation_notes, reconciliation_required)
        if args.reconciliation_notes and args.reconciliation_notes.is_dir()
        else {}
    )
    images, _ = validate_visual_packets(
        inventory, audit_cards, events, first_notes, second_notes, reconciliations
    )

    rows: list[dict[str, Any]] = []
    image_ids = {str(row["source_file_id"]) for row in images}
    compiled_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for source in inventory:
        source_id = str(source["source_file_id"])
        if source_id in image_ids:
            rows.append(
                visual_observation(
                    source,
                    first_notes[source_id],
                    second_notes[source_id],
                    reconciliations.get(source_id),
                )
            )
            continue
        source_path = args.source_root / str(source["relative_path"])
        if not source_path.is_file():
            raise ValueError(f"来源文件不存在: {source_path}")
        rows.append(text_source_observation(source, source_path, compiled_at))

    rows.sort(key=lambda row: int(str(row["source_file_id"]).split("-")[1]))
    payload = {
        "status": "ready",
        "source_count": len(inventory),
        "observation_count": len(rows),
        "image_count": len(images),
        "first_pass_count": len(first_notes),
        "second_pass_count": len(second_notes),
        "mismatch_count": sum(1 for row in second_notes.values() if row["second_pass_status"].strip() != "match"),
        "reconciled_count": len(reconciliations),
        "output": str(data / "source_observation.jsonl"),
        "dry_run": args.dry_run,
    }
    if not args.dry_run:
        atomic_write_jsonl(data / "source_observation.jsonl", rows)
        atomic_write_jsonl(data / "tool_audit_events.jsonl", events)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
