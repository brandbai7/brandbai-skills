"""Prepare deterministic per-source claim candidates outside the delivery.

The model decides which candidates matter.  This script owns source binding,
verbatim text, locators, suggested types, and trusted claim-extract metadata.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree as ET

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

EXCLUDED_SHEETS_RE = re.compile(r"素材清单|采集说明")
HEADER_LABEL_RE = re.compile(
    r"^(字段|参数名称|当前参数名|变量名|价格角色|信息类型|素材类型|项目|当前规格项|规格组)$"
)
OPERATIONAL_LABEL_RE = re.compile(
    r"^(商品链接|快照采集时间|价格识别状态|SKU映射状态|主图数量|详情图数量|"
    r"有效详情内容图|待复核低信息图|质量排除图片|视频数量|可选内容未展示|"
    r"详情加载状态|视频识别状态|页面视频播放器|模块读取状态|商品资料状态|"
    r"内容资料状态|经营快照状态)$"
)

# High-density labels must become independent claim units.  The list is
# deliberately conservative: it targets fields whose accidental merging would
# change SKU, compliance, ingredient, nutrition, storage or warning meaning.
ATOMIC_FIELD_LABEL_RE = re.compile(
    r"(?:商品标题|产品名称|商品名称|品牌|品名|系列|厂名|生产企业|产地|"
    r"当前选择SKU\s*ID|当前选中规格|规格组|型号|净含量|单件净含量|包装规格|"
    r"配料表|配料|成分|营养成分表|能量|蛋白质|脂肪|碳水化合物|钠|钙|"
    r"保质期|贮存条件|储存条件|储存方法|生产许可证编号|生产许可证|"
    r"执行标准|标准编号|注册证号|备案编号|适用人群|不适宜人群|禁忌|"
    r"注意事项|警示语|使用方法|食用方法|饮用方法)\s*[:：]",
    re.IGNORECASE,
)
FOOTNOTE_START_RE = re.compile(
    r"^\s*(?P<marker>\*\d*|※\d*|注\s*\d*)\s*(?:数据来源|来源|注|说明|"
    r"检测|实验|测试|统计|依据|截至|结果|本页|页面)",
    re.IGNORECASE,
)
NUMBERED_FOOTNOTE_MARKER_RE = re.compile(r"\*\d+|※\d+|注\s*\d+")
PLAIN_FOOTNOTE_MARKER_RE = re.compile(r"(?<=[\u4e00-\u9fff\d%])\*(?=$|[；;。,.，\s])")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--trusted-events", type=Path)
    parser.add_argument("--source-file-id", action="append", dest="source_file_ids")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def ensure_external_work_dir(delivery: Path, out_dir: Path) -> None:
    delivery_resolved = delivery.resolve()
    out_resolved = out_dir.resolve()
    if out_resolved == delivery_resolved or out_resolved.is_relative_to(delivery_resolved):
        raise ValueError("候选工作目录必须位于正式交付目录之外")


def suggested_claim_type(text: str) -> str:
    if re.search(r"^(商品标题|产品名称|商品名称|品牌|店铺|品名|系列|厂名)[:：]", text):
        return "identity"
    if re.search(
        r"^(当前选择SKU ID|当前选中规格|规格组|口味|净含量|单件净含量|包装规格)[:：]",
        text,
        re.IGNORECASE,
    ):
        return "sku"
    if re.search(r"(?:^|[\s【#-])(?:EM|W|CB|MLE|C|N)\d+(?:\.[A-Z])?(?:\s|$|[^A-Za-z0-9])", text, re.IGNORECASE):
        return "sku"
    rules = (
        (r"配料表|配料[:：]|成分[:：]|0添加蔗糖|无添加蔗糖", "ingredient"),
        (r"营养成分表|能量|蛋白质|脂肪|碳水化合物|钠|钙", "nutrition"),
        (r"贮存|储存|冷藏|保鲜|保质期", "storage"),
        (r"警示|注意事项|请勿|不适宜|不宜|禁忌|过敏|色差|以收到的实物为准|避免阳光", "warning"),
        (r"许可证|认证|检测|证书|报告|备案编号|注册证号|执行标准|标准编号|未检出|符合|国家队指定", "evidence"),
        (
            r"价格|售价|优惠|赠|会员|销量|已售|评价|回头客|加购|补贴|到手|"
            r"送达|运费|价保|退款|支付|退货|假一赔",
            "transaction",
        ),
        (r"SKU|规格|净含量|型号|当前选中|当前选择|\d+(?:\.\d+)?\s*(?:g|kg|克|千克|ml|毫升|袋|盒)", "sku"),
        (r"使用方法|饮用|食用|搭配|用法|涂抹|上妆|唇颊|腮红|眼影|打底|叠涂", "usage"),
        (r"高于|低于|相比|降低|提升|对比", "comparison"),
        (r"发酵|工艺|生产|菌种", "process"),
        (r"口感|风味|香|甜|醇厚|顺滑|柔雾|哑雾|粉雾|绵密|Q弹|延展|质地|妆效|氛围感", "sensory"),
        (r"产地|原产|奶源|牧场", "origin"),
        (r"适用人群|适合|儿童|老人|健身|代言人", "audience"),
        (r"包装|袋装|盒装|独立装", "packaging"),
        (r"问[:：]|答[:：]|FAQ", "faq"),
    )
    for pattern, claim_type in rules:
        if re.search(pattern, text, re.IGNORECASE):
            return claim_type
    return "other"


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    member = "xl/sharedStrings.xml"
    if member not in archive.namelist():
        return []
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read(member))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", namespace)).strip()
        for item in root.findall("m:si", namespace)
    ]


def cell_text(cell: ET.Element, shared: list[str], namespace: dict[str, str]) -> str:
    value = cell.find("m:v", namespace)
    if value is None or value.text is None:
        inline = cell.find("m:is", namespace)
        return "" if inline is None else "".join(
            node.text or "" for node in inline.findall(".//m:t", namespace)
        ).strip()
    if cell.attrib.get("t") == "s":
        index = int(value.text)
        return shared[index].strip() if 0 <= index < len(shared) else ""
    return str(value.text).strip()


def workbook_rows(path: Path) -> Iterable[tuple[str, int, list[tuple[str, str]]]]:
    namespace = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    package_rel_namespace = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        shared = shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation_map = {
            node.attrib["Id"]: node.attrib["Target"]
            for node in relationships.findall("p:Relationship", package_rel_namespace)
        }
        for sheet in workbook.findall("m:sheets/m:sheet", namespace):
            sheet_name = str(sheet.attrib.get("name", ""))
            relation_id = sheet.attrib.get(f"{{{namespace['r']}}}id", "")
            target = relation_map.get(relation_id, "")
            member = str(PurePosixPath("xl") / target.lstrip("/"))
            if target.startswith("/xl/"):
                member = target.lstrip("/")
            if member not in archive.namelist():
                continue
            xml = ET.fromstring(archive.read(member))
            for row in xml.findall(".//m:sheetData/m:row", namespace):
                row_number = int(row.attrib.get("r", "0") or 0)
                cells: list[tuple[str, str]] = []
                for cell in row.findall("m:c", namespace):
                    text = cell_text(cell, shared, namespace)
                    if text:
                        cells.append((str(cell.attrib.get("r", "")), text))
                yield sheet_name, row_number, cells


def spreadsheet_candidates(path: Path) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sheet_name, row_number, cells in workbook_rows(path):
        if EXCLUDED_SHEETS_RE.search(sheet_name) or len(cells) < 2:
            continue
        values = [value.strip() for _, value in cells if value.strip()]
        if len(values) < 2:
            continue
        if row_number == 1 and HEADER_LABEL_RE.fullmatch(values[0]):
            continue
        if OPERATIONAL_LABEL_RE.fullmatch(values[0]):
            continue
        verbatim = f"{values[0]}：{'；'.join(values[1:])}"
        locator = f"{sheet_name}!{cells[0][0]}:{cells[-1][0]}"
        key = verbatim, locator
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"verbatim_text": verbatim, "visual_locator": locator})
    return candidates


def split_atomic_units(text: str) -> list[str]:
    """Split visible text without merging distinct regulated claim fields."""

    hard_parts = [part.strip() for part in re.split(r"[;；\n|]+", text) if part.strip()]
    units: list[str] = []
    for hard_part in hard_parts:
        # Sentence boundaries are safe claim boundaries; punctuation itself is
        # layout, not part of the business value copied into the ledger.
        sentence_parts = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?])\s*", hard_part)
            if part.strip()
        ]
        for sentence in sentence_parts:
            starts = [match.start() for match in ATOMIC_FIELD_LABEL_RE.finditer(sentence)]
            if len(starts) <= 1:
                units.append(sentence)
                continue
            if starts[0] > 0 and sentence[: starts[0]].strip():
                units.append(sentence[: starts[0]].strip())
            for index, start in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else len(sentence)
                value = sentence[start:end].strip(" ，,、")
                if value:
                    units.append(value)
    return units


def footnote_marker(value: str) -> str:
    match = FOOTNOTE_START_RE.match(value)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group("marker"))


def referenced_footnote_markers(value: str) -> list[str]:
    if FOOTNOTE_START_RE.match(value):
        return []
    markers = [re.sub(r"\s+", "", match.group(0)) for match in NUMBERED_FOOTNOTE_MARKER_RE.finditer(value)]
    if PLAIN_FOOTNOTE_MARKER_RE.search(value):
        markers.append("*")
    return list(dict.fromkeys(markers))


def bind_footnotes(candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    marker_to_indexes: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        marker = footnote_marker(candidate["verbatim_text"])
        if marker:
            marker_to_indexes.setdefault(marker, []).append(index)

    enriched: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        marker = footnote_marker(candidate["verbatim_text"])
        linked_indexes: list[int] = []
        for reference in referenced_footnote_markers(candidate["verbatim_text"]):
            linked_indexes.extend(marker_to_indexes.get(reference, []))
        enriched.append(
            {
                **candidate,
                "claim_unit_kind": "footnote" if marker else "atomic",
                "footnote_marker": marker,
                "linked_footnote_indexes": sorted(set(linked_indexes)),
            }
        )
    return enriched


def text_candidates(text: str, locator: str) -> list[dict[str, str]]:
    values = [part.strip() for part in split_atomic_units(text) if len(part.strip()) >= 2]
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        value = re.sub(r"^#{1,6}\s*", "", value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        candidates.append({"verbatim_text": value, "visual_locator": locator})
    return candidates


def candidate_rows(source: dict[str, Any], observation: dict[str, Any], source_path: Path) -> list[dict[str, str]]:
    suffix = source_path.suffix.lower()
    media_type = str(source.get("media_type", "")).lower()
    if suffix in {".xlsx", ".xlsm"} or "spreadsheetml" in media_type:
        return spreadsheet_candidates(source_path)
    if suffix in {".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".jsonl"}:
        try:
            raw = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = source_path.read_text(encoding="utf-8-sig")
        return text_candidates(raw, "文档可见文字")
    rows: list[dict[str, str]] = []
    rows.extend(text_candidates(str(observation.get("visible_heading", "")), "页面可见标题"))
    rows.extend(text_candidates(str(observation.get("visible_text_excerpt", "")), "页面可见文字摘录"))
    unique_rows: list[dict[str, str]] = []
    seen_text: set[str] = set()
    for row in rows:
        verbatim = row["verbatim_text"]
        if verbatim in seen_text:
            continue
        seen_text.add(verbatim)
        unique_rows.append(row)
    return unique_rows


def main() -> int:
    args = parse_args()
    ensure_external_work_dir(args.delivery, args.out_dir)
    data = args.delivery / "data"
    inventory = read_jsonl(data / "source_inventory.jsonl")
    observations = read_jsonl(data / "source_observation.jsonl")
    events_path = args.trusted_events or data / "tool_audit_events.jsonl"
    events = read_jsonl(events_path)
    source_by_id = {str(row.get("source_file_id", "")): row for row in inventory}
    observation_by_source = {str(row.get("source_file_id", "")): row for row in observations}
    extract_by_source = {
        str(row.get("source_file_id", "")): row
        for row in events
        if row.get("phase") == "claim_extract"
    }
    selected_ids = args.source_file_ids or [
        str(row.get("source_file_id", "")) for row in inventory if str(row.get("source_file_id", "")) in extract_by_source
    ]
    if not selected_ids:
        raise ValueError("没有已完成 claim_extract 的来源可生成候选")

    summaries: list[dict[str, Any]] = []
    for source_id in selected_ids:
        if not re.fullmatch(r"SF-\d{3,}", source_id):
            raise ValueError(f"source_file_id 格式不正确: {source_id}")
        source = source_by_id.get(source_id)
        observation = observation_by_source.get(source_id)
        event = extract_by_source.get(source_id)
        if not source or not observation or not event:
            raise ValueError(f"{source_id} 缺少来源、Observation 或 claim_extract 事件")
        inspection_status = str(observation.get("inspection_status", ""))
        if inspection_status not in {"inspected", "unreadable", "not_applicable"}:
            raise ValueError(f"{source_id} 的 inspection_status 不在允许范围")
        source_path = args.source_root / str(source.get("relative_path", ""))
        if not source_path.is_file():
            raise ValueError(f"来源文件不存在: {source_path}")
        output_path = args.out_dir / f"{source_id}.json"
        if output_path.exists() and not args.force:
            raise FileExistsError(f"候选文件已存在，禁止覆盖: {output_path}")
        raw_candidates = (
            candidate_rows(source, observation, source_path)
            if inspection_status == "inspected"
            else []
        )
        candidate_seeds = bind_footnotes(raw_candidates)
        candidates = [
            {
                "candidate_id": f"CAND-{index:03d}",
                "verbatim_text": row["verbatim_text"],
                "suggested_claim_type": (
                    "evidence"
                    if row.get("claim_unit_kind") == "footnote"
                    else suggested_claim_type(row["verbatim_text"])
                ),
                "visual_locator": row["visual_locator"],
                "claim_unit_kind": row.get("claim_unit_kind", "atomic"),
                "footnote_marker": row.get("footnote_marker", ""),
                "linked_footnote_candidate_ids": [
                    f"CAND-{linked_index + 1:03d}"
                    for linked_index in row.get("linked_footnote_indexes", [])
                ],
            }
            for index, row in enumerate(candidate_seeds, start=1)
        ]
        if any(row["suggested_claim_type"] not in CLAIM_TYPES for row in candidates):
            raise ValueError(f"{source_id} 生成了非法 claim_type")
        payload = {
            "format_version": "1.1",
            "source_file_id": source_id,
            "observation_id": str(observation.get("observation_id", "")),
            "relative_path": str(source.get("relative_path", "")),
            "source_sha256": str(source.get("sha256", "")),
            "extract_recorded_at": str(event.get("recorded_at", "")),
            "extract_sequence": int(event.get("sequence", 0)),
            "inspection_status": inspection_status,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        summaries.append({"source_file_id": source_id, "candidate_count": len(candidates)})
        if not args.dry_run:
            atomic_write_json(output_path, payload)

    print(
        json.dumps(
            {"status": "dry_run" if args.dry_run else "prepared", "source_count": len(summaries), "sources": summaries},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
