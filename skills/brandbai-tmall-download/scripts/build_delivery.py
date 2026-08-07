"""Build the customer-readable BrandBAI Tmall collection workbooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from collector_core import atomic_write_json, utc_now


class DeliveryError(RuntimeError):
    pass


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(_flatten(item) for item in value if _flatten(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _style_workbook(workbook: Any) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    header_fill = PatternFill("solid", fgColor="173B57")
    header_font = Font(color="FFFFFF", bold=True)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column in sheet.columns:
            letter = column[0].column_letter
            lengths = [len(str(cell.value or "")) for cell in column[:200]]
            sheet.column_dimensions[letter].width = min(max(max(lengths, default=8) + 2, 10), 48)


def _write_sheet(workbook: Any, title: str, headers: list[str], rows: Iterable[list[Any]]) -> None:
    sheet = workbook.create_sheet(title=title)
    sheet.append(headers)
    for row in rows:
        sheet.append([_flatten(value) for value in row])


def build_delivery(out_value: str | Path) -> dict[str, Any]:
    try:
        from openpyxl import Workbook, load_workbook
    except ImportError as exc:
        raise DeliveryError("openpyxl is missing; install requirements-browser.txt first") from exc

    out = Path(out_value).expanduser().resolve()
    product_root = out / "data" / "商品采集"
    review_root = out / "data" / "评价采集"
    products = [_load_json(path, {}) for path in sorted(product_root.glob("*/product.json"))] if product_root.is_dir() else []
    review_rows: list[dict[str, Any]] = []
    review_manifests: list[dict[str, Any]] = []
    if review_root.is_dir():
        for path in sorted(review_root.glob("*/reviews.jsonl")):
            review_rows.extend(_load_jsonl(path))
        review_manifests = [_load_json(path, {}) for path in sorted(review_root.glob("*/review_manifest.json"))]
    run_manifest = _load_json(out / "data" / "run_manifest.json", {})
    if not products and not review_rows and not review_manifests:
        raise DeliveryError("No Tmall collection data was found in the delivery directory")

    product_book = Workbook()
    product_book.remove(product_book.active)
    _write_sheet(
        product_book,
        "商品总览",
        ["商品ID", "商品标题", "店铺", "商品链接", "选中SKU ID", "价格快照", "销量快照", "库存快照", "采集时间", "完成状态"],
        [
            [
                row.get("item_id"), row.get("title"), (row.get("shop") or {}).get("text"), row.get("canonical_url"),
                row.get("selected_sku_id"), (row.get("snapshot") or {}).get("price_texts"),
                (row.get("snapshot") or {}).get("sales_texts"), (row.get("snapshot") or {}).get("stock_texts"),
                row.get("collected_at"), row.get("completion_state"),
            ] for row in products
        ],
    )
    parameter_rows = []
    sku_rows = []
    media_rows = []
    completion_rows = []
    for product in products:
        item_id = product.get("item_id")
        for row in product.get("parameters") or []:
            parameter_rows.append([item_id, row.get("name"), row.get("value"), product.get("canonical_url"), product.get("collected_at")])
        for group in product.get("sku_groups") or []:
            for order, value in enumerate(group.get("values") or [], start=1):
                sku_rows.append([
                    item_id, group.get("name"), order, value, value == group.get("selected_value"),
                    group.get("selected_value"), product.get("selected_sku_id"), product.get("collected_at"),
                ])
        for row in product.get("media_records") or []:
            media_rows.append([
                item_id, row.get("asset_id"), row.get("kind"), row.get("order"), row.get("status"), row.get("file"),
                row.get("source_url"), row.get("source_url_query_redacted"), row.get("bytes"), row.get("content_type"),
            ])
        completion_rows.append([item_id, "商品资料", product.get("completion_state"), "", product.get("collected_at")])
    for manifest in review_manifests:
        completion_rows.append([
            manifest.get("item_id"), "可见评价", manifest.get("state"),
            f"保存{manifest.get('saved_reviews', 0)}条；平台折叠{manifest.get('folded_count', 0)}条；exhausted={manifest.get('exhausted')}",
            manifest.get("finished_at"),
        ])
    _write_sheet(product_book, "规格参数", ["商品ID", "参数名", "参数值", "来源链接", "采集时间"], parameter_rows)
    _write_sheet(product_book, "SKU快照", ["商品ID", "规格组", "顺序", "页面可见选项", "是否页面选中", "页面选中选项", "当时选中SKU ID", "采集时间"], sku_rows)
    _write_sheet(product_book, "素材索引", ["商品ID", "素材ID", "类型", "顺序", "状态", "文件", "公开来源URL", "查询参数已脱敏", "字节数", "内容类型"], media_rows)
    _write_sheet(product_book, "完整性", ["商品ID", "采集对象", "状态", "说明", "时间"], completion_rows)
    _style_workbook(product_book)
    product_path = out / "01_商品资料.xlsx"
    product_book.save(product_path)
    load_workbook(product_path, read_only=True).close()

    review_book = Workbook()
    review_book.remove(review_book.active)
    _write_sheet(
        review_book,
        "评价明细",
        ["评价ID", "ID类型", "商品ID", "内容角色", "评价者匿名ID", "页面遮罩名", "评价时间原文", "购买规格原文", "评价原文", "媒体数量", "采集时间"],
        [[
            row.get("review_id"), row.get("review_id_type"), row.get("item_id"), row.get("role"), row.get("author_id"),
            row.get("author_masked"), row.get("date_text"), row.get("purchased_sku_text"), row.get("content"),
            len(row.get("media") or []), row.get("collected_at"),
        ] for row in review_rows],
    )
    _write_sheet(
        review_book,
        "采集状态",
        ["商品ID", "完成状态", "已保存评价", "平台折叠提示数", "是否到达可见源末端", "样本上限", "是否达到上限", "隐私模式", "完成时间"],
        [[
            row.get("item_id"), row.get("state"), row.get("saved_reviews"), row.get("folded_count"), row.get("exhausted"),
            row.get("limit"), row.get("limit_reached"), row.get("privacy_mode"), row.get("finished_at"),
        ] for row in review_manifests],
    )
    _style_workbook(review_book)
    review_path = out / "02_评价明细.xlsx"
    review_book.save(review_path)
    load_workbook(review_path, read_only=True).close()

    description = f"""# BrandBAI 天猫商品资料采集说明

## 本次交付

- 商品数：{len(products)}
- 已保存评价及追评记录：{len(review_rows)}
- 采集状态：{run_manifest.get('state', 'unknown')}
- 构建时间：{utc_now()}

## 文件说明

- `01_商品资料.xlsx`：商品总览、页面参数、SKU 可见选项、素材索引和完整性状态。
- `02_评价明细.xlsx`：页面可见评价、追评与每个商品的评价采集状态。
- `03_商品素材/`：按本次选择下载的主图、详情图和可见视频。
- `data/`：用于断点续跑、复核和后续商品价值 Skill 接力的原始结构化数据。

## 重要边界

1. 价格、促销、销量、库存、排名和选中 SKU 都是采集时点快照，会随账号、地区、时间和活动变化。
2. “可见评价采集完成”只表示滚动到页面当前可返回内容的末端。若天猫提示折叠评价，状态会保留为 `partial_platform_folded`，不宣称平台内部绝对全量。
3. 评价是消费者公开表达，不等于经过核验的商品功效、身份或购买事实。
4. 本包只做下载、结构化和质量说明，不自动生成商品价值结论、卖点、用户语义标签或商业归因。
5. 登录资料、Cookie、请求头、验证码、浏览器配置和本地任务缓存不进入交付包。
"""
    (out / "04_采集说明.md").write_text(description, encoding="utf-8")

    summary = {
        "built_at": utc_now(),
        "products": len(products),
        "reviews": len(review_rows),
        "product_workbook": product_path.name,
        "review_workbook": review_path.name,
        "run_state": run_manifest.get("state", "unknown"),
    }
    atomic_write_json(out / "data" / "delivery_manifest.json", summary)
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(build_delivery(args.out), ensure_ascii=False, indent=2))
