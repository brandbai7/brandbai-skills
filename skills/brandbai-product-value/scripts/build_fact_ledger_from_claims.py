"""Build conservative one-claim-one-fact parts from the audited claim ledger."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from product_value_common import read_json, read_jsonl


SKIPPED_CLAIM_TYPES = {"other"}
VARIANT_BUNDLE_RE = re.compile(r"(?:24|48|72|96)\s*包")
OPERATIONAL_URL_RE = re.compile(r"^\s*[-*]?\s*商品链接\s*[:：]\s*https?://", re.IGNORECASE)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def boundary_for(claim: dict[str, Any], dynamic: bool) -> str:
    text = str(claim.get("verbatim_text", ""))
    claim_type = str(claim.get("claim_type", ""))
    if dynamic:
        if len(set(VARIANT_BUNDLE_RE.findall(text))) > 1:
            return "仅为采集时页面套餐入口快照；time_scope 年份依据采集时间推定；多组包数是可见变体，不等于当前成交 SKU，不进入长期稳定价值。"
        return "仅为采集时页面快照；time_scope 年份依据采集时间推定；价格、销量、权益、服务与活动状态会变化，不进入长期稳定价值。"
    if claim_type == "sku":
        return "页面可见 SKU/规格主张；当前成交单元仍需以成交页最终选择确认，不外推到其他变体。"
    if claim_type == "evidence":
        return "仅按页面公开证据主张记录，未取得报告或证书原件核验；不升级为官方核验结论。"
    if claim_type == "comparison":
        return "仅按当前页面内比较或品牌主张记录；未做外部同类样本与行业数据核验。"
    if claim_type in {"ingredient", "nutrition", "storage", "warning", "origin"}:
        return "仅按当前页面/表格公开字段记录；不扩展到其他 SKU、批次或未展示范围。"
    return "仅按当前页面公开主张记录；未经过独立外部验证，不扩展到其他 SKU 或批次。"


def build_fact_rows(delivery: Path) -> list[dict[str, Any]]:
    data = delivery / "data"
    manifest = read_json(data / "product_manifest.json")
    claims = read_jsonl(data / "source_claim_ledger.jsonl")
    sources = read_jsonl(data / "source_ledger.jsonl")
    source_by_file = {str(item.get("source_file_id", "")): item for item in sources}
    stable_index = 0
    dynamic_index = 0
    rows: list[dict[str, Any]] = []
    covered_critical: set[str] = set()

    for claim in claims:
        claim_type = str(claim.get("claim_type", ""))
        if claim_type in SKIPPED_CLAIM_TYPES:
            continue
        if OPERATIONAL_URL_RE.search(str(claim.get("verbatim_text", ""))):
            continue
        source = source_by_file.get(str(claim.get("source_file_id", "")))
        if source is None:
            raise ValueError(f"{claim.get('claim_id')} 的来源未进入 source_ledger")
        verbatim = str(claim.get("verbatim_text", "")).strip()
        locator = str(claim.get("visual_locator", "")).strip()
        if not verbatim or not locator:
            raise ValueError(f"{claim.get('claim_id')} 缺少逐字原文或定位")
        dynamic = claim_type == "transaction"
        if dynamic:
            dynamic_index += 1
            fact_id = f"DYN-{dynamic_index:03d}"
            fact_type = "DYN"
            time_scope = str(source.get("captured_at", ""))
            status = "active_at_snapshot"
        else:
            stable_index += 1
            fact_id = f"F-{stable_index:03d}"
            fact_type = "F-PAGE"
            time_scope = "current_page_snapshot"
            status = "page_claim_unverified"
        row = {
            "fact_id": fact_id,
            "fact_type": fact_type,
            "statement": verbatim,
            "source_id": str(source.get("source_id", "")),
            "claim_ids": [str(claim.get("claim_id", ""))],
            "source_quotes": [verbatim],
            "locator": locator,
            "sku_scope": str(source.get("sku_scope", "")) or str(manifest.get("sku", "")),
            "time_scope": time_scope,
            "status": status,
            "boundary": boundary_for(claim, dynamic),
        }
        rows.append(row)
        if claim.get("critical") is True:
            covered_critical.add(str(claim.get("claim_id", "")))

    required_critical = {
        str(claim.get("claim_id", ""))
        for claim in claims
        if claim.get("critical") is True
    }
    missing = sorted(required_critical - covered_critical)
    if missing:
        raise ValueError(f"关键原文主张未进入事实：{', '.join(missing)}")
    return rows


def build_fact_parts(
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
        raise ValueError("事实分包目录必须位于正式交付目录之外")
    rows = build_fact_rows(delivery)
    counts = {
        "facts": sum(1 for row in rows if row["fact_type"] == "F-PAGE"),
        "dynamic": sum(1 for row in rows if row["fact_type"] == "DYN"),
    }
    if dry_run:
        return {"status": "dry_run", "fact_count": len(rows), **counts, "parts_dir": str(parts_dir)}

    parts_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(path for path in parts_dir.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".jsonl"})
    if existing and not rebuild:
        raise FileExistsError("事实分包目录已有 JSON/JSONL；如需确定性重建请显式使用 --rebuild")
    if rebuild:
        for path in existing:
            path.unlink()
    rows_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_source.setdefault(str(row["source_id"]), []).append(row)
    for source_id, source_rows in rows_by_source.items():
        output_path = parts_dir / f"{source_id}.jsonl"
        output_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in source_rows),
            encoding="utf-8",
        )
    return {
        "status": "built",
        "fact_count": len(rows),
        "part_count": len(rows_by_source),
        **counts,
        "parts_dir": str(parts_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--parts-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    result = build_fact_parts(args.delivery, args.parts_dir, dry_run=args.dry_run, rebuild=args.rebuild)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
