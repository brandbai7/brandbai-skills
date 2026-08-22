"""Initialize a BrandBAI Product Page delivery without drawing page conclusions."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from index_page_sources import build_unattached_plan as build_source_plan
from index_page_sources import index_sources
from product_page_common import (
    COURSE_REPORT,
    DECISION_NAMES,
    DELIVERY_MODES,
    PROFESSIONAL_REPORTS,
    SCOPES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    TASKS,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    file_sha256,
    now_iso,
    product_page_id,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)


P0_USABLE_STATUSES = {
    "P0-HYPOTHESIS",
    "P0-SELECTED",
    "P0-VALIDATING",
    "P0-BOUNDARY-VALIDATED",
}
P0_READY_STATUSES = {"P0-SELECTED", "P0-VALIDATING", "P0-BOUNDARY-VALIDATED"}
VALUE_USABLE_READINESS = {"ready", "conditional"}


def validate_output_location(
    out: Path,
    page_sources: Path,
    comparison_sources: Path | None,
) -> None:
    target = out.expanduser().resolve()
    for source in (page_sources, comparison_sources):
        if source is None:
            continue
        resolved = source.expanduser().resolve()
        source_root = resolved.parent if resolved.is_file() else resolved
        if target == source_root or target.is_relative_to(source_root):
            raise ValueError("输出目录不能位于页面资料目录内部，避免把交付文件重新索引为来源")


def product_value_paths(root: Path) -> dict[str, Path]:
    data = root / "data"
    return {
        "manifest": data / "product_manifest.json",
        "facts": data / "fact_ledger.jsonl",
        "values": data / "value_ledger.jsonl",
        "decision": data / "p0_decision.json",
    }


def value_expression_paths(root: Path) -> dict[str, Path]:
    data = root / "data"
    return {
        "manifest": data / "expression_manifest.json",
        "upstream": data / "upstream_snapshot.json",
        "vis": data / "vis_ledger.jsonl",
    }


def load_product_value(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "usable": False,
            "reason": "未提供商品价值底座",
            "product_value_id": "",
            "source_delivery_name": "not_provided",
            "brand": "",
            "product": "",
            "category": "",
            "sku": "",
            "output_version": "",
            "analysis_status": "not_provided",
            "delivery_status": "not_provided",
            "p0_status": "not_provided",
            "recommended_value_id": "",
            "facts": [],
            "values": [],
            "fact_ids": [],
            "value_ids": [],
            "file_hashes": {},
        }
    root = path.expanduser().resolve()
    paths = product_value_paths(root)
    missing = [str(item) for item in paths.values() if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"商品价值底座缺少必需文件: {', '.join(missing)}")
    manifest = read_json(paths["manifest"])
    decision = read_json(paths["decision"])
    facts = read_jsonl(paths["facts"])
    values = read_jsonl(paths["values"])
    required_identity = ("product_value_id", "brand", "product", "sku")
    if not all(str(manifest.get(field, "")).strip() for field in required_identity):
        raise ValueError("商品价值底座缺少商品、SKU或 product_value_id")
    recommended = str(decision.get("recommended_value_id", ""))
    value_ids = {str(item.get("value_id", "")) for item in values if item.get("value_id")}
    recommended_value = next(
        (item for item in values if str(item.get("value_id", "")) == recommended),
        {},
    )
    usable = (
        manifest.get("analysis_status") in UPSTREAM_ANALYSIS_STATUSES
        and manifest.get("delivery_status") in UPSTREAM_DELIVERY_STATUSES
        and decision.get("status") in P0_USABLE_STATUSES
        and bool(recommended)
        and recommended in value_ids
        and recommended_value.get("downstream_readiness") in VALUE_USABLE_READINESS
    )
    reasons: list[str] = []
    if manifest.get("analysis_status") not in UPSTREAM_ANALYSIS_STATUSES:
        reasons.append("analysis_status不可调用")
    if manifest.get("delivery_status") not in UPSTREAM_DELIVERY_STATUSES:
        reasons.append("delivery_status不可调用")
    if decision.get("status") not in P0_USABLE_STATUSES:
        reasons.append("P0不是可分析假设、已选择、验证中或边界已验证状态，或已重开、替换、停止")
    if not recommended or recommended not in value_ids:
        reasons.append("缺少有效推荐价值")
    elif recommended_value.get("downstream_readiness") not in VALUE_USABLE_READINESS:
        reasons.append("推荐价值的下游可调用状态无效或已阻断")
    return {
        "provided": True,
        "usable": usable,
        "reason": "" if usable else "；".join(reasons),
        "product_value_id": str(manifest.get("product_value_id", "")),
        "source_delivery_name": root.name,
        "brand": str(manifest.get("brand", "")),
        "product": str(manifest.get("product", "")),
        "category": str(manifest.get("category", "")),
        "sku": str(manifest.get("sku", "")),
        "output_version": str(manifest.get("output_version", "")),
        "analysis_status": str(manifest.get("analysis_status", "")),
        "delivery_status": str(manifest.get("delivery_status", "")),
        "p0_status": str(decision.get("status", "")),
        "recommended_value_id": recommended,
        "facts": [
            {
                "fact_id": item.get("fact_id", ""),
                "fact_type": item.get("fact_type", ""),
                "statement": item.get("statement", ""),
                "locator": item.get("locator", ""),
                "boundary": item.get("boundary", ""),
            }
            for item in facts
        ],
        "values": [
            {
                "value_id": item.get("value_id", ""),
                "layer": item.get("layer", ""),
                "value_statement": item.get("value_statement", ""),
                "user_task": item.get("user_task", ""),
                "downstream_readiness": item.get("downstream_readiness", ""),
                "cannot_prove": item.get("cannot_prove", []),
            }
            for item in values
        ],
        "fact_ids": [str(item.get("fact_id", "")) for item in facts if item.get("fact_id")],
        "value_ids": sorted(value_ids),
        "file_hashes": {item.name: file_sha256(item) for item in paths.values()},
    }


def load_value_expression(path: Path | None, product_value: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "usable": False,
            "reason": "未提供卖点呈现资产",
            "value_expression_id": "",
            "product_value_id": "",
            "source_delivery_name": "not_provided",
            "brand": "",
            "product": "",
            "sku": "",
            "output_version": "",
            "analysis_status": "not_provided",
            "delivery_status": "not_provided",
            "vis": [],
            "vis_ids": [],
            "file_hashes": {},
        }
    root = path.expanduser().resolve()
    paths = value_expression_paths(root)
    missing = [str(item) for item in paths.values() if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"卖点呈现交付缺少必需文件: {', '.join(missing)}")
    manifest = read_json(paths["manifest"])
    upstream = read_json(paths["upstream"])
    vis = read_jsonl(paths["vis"])
    reasons: list[str] = []
    if not product_value.get("usable"):
        reasons.append("商品价值上游不可调用")
    if manifest.get("analysis_status") not in UPSTREAM_ANALYSIS_STATUSES:
        reasons.append("analysis_status不可调用")
    if manifest.get("delivery_status") not in UPSTREAM_DELIVERY_STATUSES:
        reasons.append("delivery_status不可调用")
    if manifest.get("product_value_id") != product_value.get("product_value_id"):
        reasons.append("product_value_id与商品价值底座不一致")
    for field, label in (("brand", "品牌"), ("product", "商品"), ("sku", "SKU")):
        if str(manifest.get(field, "")).strip() != str(product_value.get(field, "")).strip():
            reasons.append(f"{label}与商品价值底座不一致")
    if (
        str(manifest.get("category", "")).strip()
        and str(product_value.get("category", "")).strip()
        and str(manifest.get("category", "")).strip()
        != str(product_value.get("category", "")).strip()
    ):
        reasons.append("类目与商品价值底座不一致")
    if upstream.get("product_value_id") != product_value.get("product_value_id"):
        reasons.append("卖点呈现内嵌上游ID与商品价值底座不一致")
    if upstream.get("recommended_value_id") != product_value.get("recommended_value_id"):
        reasons.append("卖点呈现内嵌推荐价值与当前P0不一致")
    if str(upstream.get("upstream_output_version", "")) != str(product_value.get("output_version", "")):
        reasons.append("卖点呈现内嵌商品价值版本已过期")
    if str(upstream.get("upstream_analysis_status", "")) != str(product_value.get("analysis_status", "")):
        reasons.append("卖点呈现内嵌商品价值分析状态已变化")
    if str(upstream.get("upstream_delivery_status", "")) != str(product_value.get("delivery_status", "")):
        reasons.append("卖点呈现内嵌商品价值交付状态已变化")
    if str(upstream.get("p0_status", "")) != str(product_value.get("p0_status", "")):
        reasons.append("卖点呈现内嵌P0状态已变化")
    upstream_hashes = upstream.get("file_hashes")
    expected_hashes = product_value.get("file_hashes", {})
    if not isinstance(upstream_hashes, dict):
        reasons.append("卖点呈现缺少商品价值文件哈希")
        upstream_hashes = {}
    if expected_hashes and any(
        upstream_hashes.get(name) != digest for name, digest in expected_hashes.items()
    ):
        reasons.append("卖点呈现引用的商品价值文件已变化")

    usable_vis: list[dict[str, Any]] = []
    seen_vis_ids: set[str] = set()
    invalid_page_vis = False
    current_value_ids = set(map(str, product_value.get("value_ids", [])))
    for item in vis:
        objects = item.get("applicable_objects")
        if not isinstance(objects, list) or "商品页" not in objects:
            continue
        vis_id = str(item.get("vis_id", "")).strip()
        value_id = str(item.get("value_id", "")).strip()
        required_text = all(
            str(item.get(field, "")).strip()
            for field in ("human_language", "must_keep", "boundary")
        )
        valid = bool(
            vis_id
            and vis_id not in seen_vis_ids
            and value_id in current_value_ids
            and item.get("validation_status") not in {"blocked", "stale", ""}
            and required_text
            and isinstance(objects, list)
        )
        if valid:
            seen_vis_ids.add(vis_id)
            usable_vis.append(item)
        else:
            invalid_page_vis = True
    if invalid_page_vis:
        reasons.append("存在ID、价值绑定、状态或必填字段无效的商品页VIS")
    if not usable_vis:
        reasons.append("没有适用于商品页的可调用VIS")
    return {
        "provided": True,
        "usable": not reasons,
        "reason": "；".join(reasons),
        "value_expression_id": str(manifest.get("value_expression_id", "")),
        "product_value_id": str(manifest.get("product_value_id", "")),
        "source_delivery_name": root.name,
        "brand": str(manifest.get("brand", "")),
        "product": str(manifest.get("product", "")),
        "category": str(manifest.get("category", "")),
        "sku": str(manifest.get("sku", "")),
        "output_version": str(manifest.get("output_version", "")),
        "analysis_status": str(manifest.get("analysis_status", "")),
        "delivery_status": str(manifest.get("delivery_status", "")),
        "upstream_product_value_id": str(upstream.get("product_value_id", "")),
        "upstream_output_version": str(upstream.get("upstream_output_version", "")),
        "upstream_analysis_status": str(upstream.get("upstream_analysis_status", "")),
        "upstream_delivery_status": str(upstream.get("upstream_delivery_status", "")),
        "p0_status": str(upstream.get("p0_status", "")),
        "recommended_value_id": str(upstream.get("recommended_value_id", "")),
        "upstream_file_hashes": upstream_hashes,
        "vis": [
            {
                "vis_id": item.get("vis_id", ""),
                "value_id": item.get("value_id", ""),
                "decision_task": item.get("decision_task", ""),
                "human_language": item.get("human_language", ""),
                "must_keep": item.get("must_keep", ""),
                "misuse": item.get("misuse", ""),
                "boundary": item.get("boundary", ""),
                "applicable_objects": item.get("applicable_objects", []),
                "validation_status": item.get("validation_status", ""),
            }
            for item in usable_vis
        ],
        "vis_ids": [str(item.get("vis_id", "")) for item in usable_vis if item.get("vis_id")],
        "file_hashes": {item.name: file_sha256(item) for item in paths.values()},
    }


def prepare_inputs(
    product_value_path: Path | None,
    value_expression_path: Path | None,
    brand: str,
    product: str,
    category: str,
    sku: str,
) -> tuple[dict[str, str], dict[str, Any], str, list[str]]:
    product_value = load_product_value(product_value_path)
    if product_value["provided"]:
        identity = {
            "brand": product_value["brand"],
            "product": product_value["product"],
            "category": product_value["category"],
            "sku": product_value["sku"],
        }
        for field, manual in (("brand", brand), ("product", product), ("sku", sku)):
            if manual and manual.strip() != identity[field].strip():
                raise ValueError(f"手工 {field} 与商品价值底座不一致")
        if category and identity["category"] and category.strip() != identity["category"].strip():
            raise ValueError("手工 category 与商品价值底座不一致")
        if category and not identity["category"]:
            identity["category"] = category.strip()
    else:
        if not all(value.strip() for value in (brand, product, sku)):
            raise ValueError("未提供商品价值底座时，必须提供 --brand、--product 和 --sku")
        identity = {
            "brand": brand.strip(),
            "product": product.strip(),
            "category": category.strip(),
            "sku": sku.strip(),
        }
    value_expression = load_value_expression(value_expression_path, product_value)
    limitations: list[str] = []
    if (
        product_value["usable"]
        and value_expression["usable"]
        and product_value["p0_status"] in P0_READY_STATUSES
    ):
        run_status = "ready"
    elif product_value["usable"]:
        run_status = "partial"
        if product_value["p0_status"] == "P0-HYPOTHESIS":
            limitations.append(
                "核心价值仍是待验证假设：可用于有条件页面诊断，但不得写成已选定或已验证的价值优先级"
            )
        if not value_expression["usable"]:
            limitations.append(value_expression["reason"] or "卖点呈现资产不可用")
    else:
        run_status = "degraded_no_product_value"
        limitations.append(product_value["reason"] or "商品价值底座不可用")
        if value_expression["provided"]:
            limitations.append(value_expression["reason"] or "卖点呈现资产不可用")
    snapshot = {
        "product_value": product_value,
        "value_expression": value_expression,
        "captured_at": now_iso(),
    }
    return identity, snapshot, run_status, limitations


def build_plan(
    out: Path,
    page_sources: Path,
    product_value: Path | None,
    value_expression: Path | None,
    brand: str,
    product: str,
    category: str,
    sku: str,
    scope: str,
    task: str,
    delivery_mode: str,
    page_snapshot_time: str,
    entry_context: str,
    comparison_sources: Path | None,
    comparison_snapshot_time: str = "unknown",
) -> dict[str, Any]:
    if scope not in SCOPES:
        raise ValueError(f"scope 必须是 {sorted(SCOPES)} 之一")
    validate_output_location(out, page_sources, comparison_sources)
    identity, snapshot, run_status, limitations = prepare_inputs(
        product_value, value_expression, brand, product, category, sku
    )
    validate_mode_contract(task, delivery_mode, run_status, entry_context, comparison_sources)
    source_plan = build_source_plan(page_sources, out, "current")
    if task == "version_review" and (
        page_snapshot_time in {"", "unknown"}
        or comparison_snapshot_time in {"", "unknown"}
    ):
        raise ValueError("version_review 必须提供当前版和对照版的页面时间")
    comparison_plan = (
        {
            **build_source_plan(comparison_sources, out, "comparison"),
            "capture_time": comparison_snapshot_time,
        }
        if comparison_sources is not None
        else None
    )
    reports = [COURSE_REPORT] if delivery_mode == "course" else list(PROFESSIONAL_REPORTS)
    return {
        "action": "initialize_product_page_delivery",
        "dry_run": True,
        "target": str(out.expanduser().resolve()),
        "identity": identity,
        "scope": scope,
        "task": task,
        "delivery_mode": delivery_mode,
        "initial_run_status": run_status,
        "limitations": limitations,
        "product_value_id": snapshot["product_value"]["product_value_id"],
        "value_expression_id": snapshot["value_expression"]["value_expression_id"],
        "page_snapshot_time": page_snapshot_time or "unknown",
        "source_plan": source_plan,
        "comparison_plan": comparison_plan,
        "will_create": [*reports, *(f"data/{name}" for name in (
            "page_manifest.json", "upstream_snapshot.json", "source_inventory.jsonl",
            "page_coverage.jsonl", "page_component_ledger.jsonl", "page_chain.json",
            "decision_ledger.jsonl", "action_ledger.jsonl",
            "validation_ledger.jsonl", "gap_ledger.jsonl",
        )), *(["data/routing_decision.json"] if task == "route" else [])],
    }


def validate_mode_contract(
    task: str,
    delivery_mode: str,
    run_status: str,
    entry_context: str,
    comparison_sources: Path | None,
) -> None:
    if task not in TASKS:
        raise ValueError(f"task 必须是 {sorted(TASKS)} 之一")
    if delivery_mode not in DELIVERY_MODES:
        raise ValueError(f"delivery_mode 必须是 {sorted(DELIVERY_MODES)} 之一")
    if delivery_mode == "course" and task != "diagnose":
        raise ValueError("课程模式只支持 task=diagnose")
    if task in {"design", "route", "version_review"} and run_status == "degraded_no_product_value":
        raise ValueError(f"task={task} 必须提供可用商品价值底座")
    if task == "route" and not entry_context.strip():
        raise ValueError("task=route 必须提供 --entry-context")
    if task == "version_review" and comparison_sources is None:
        raise ValueError("task=version_review 必须提供 --comparison-sources")
    if task != "version_review" and comparison_sources is not None:
        raise ValueError("--comparison-sources 只用于 task=version_review")


def initial_gaps(
    run_status: str,
    page_snapshot_time: str,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if run_status == "degraded_no_product_value":
        rows.append(
            {
                "gap_id": "GAP-001",
                "category": "商品价值",
                "missing": snapshot["product_value"]["reason"] or "当前SKU的有效商品价值底座",
                "impact": "只能做页面表面检查，不能决定核心卖点和价值顺序",
                "minimum_needed": "补充当前SKU的有效 BrandBAI 商品价值底座",
                "return_to": "product_value",
                "source_file_ids": [],
                "priority": "high",
                "state": "open",
            }
        )
    elif not snapshot["value_expression"]["usable"]:
        rows.append(
            {
                "gap_id": f"GAP-{len(rows) + 1:03d}",
                "category": "卖点呈现",
                "missing": snapshot["value_expression"]["reason"] or "可调用卖点呈现资产",
                "impact": "可以判断页面缺口，但部分动作不能直接编译成具体呈现要求",
                "minimum_needed": "补充当前SKU的有效 BrandBAI 卖点呈现交付",
                "return_to": "value_expression",
                "source_file_ids": [],
                "priority": "medium",
                "state": "open",
            }
        )
    if not page_snapshot_time or page_snapshot_time == "unknown":
        rows.append(
            {
                "gap_id": f"GAP-{len(rows) + 1:03d}",
                "category": "页面时间",
                "missing": "页面截图、下载或观察时间",
                "impact": "价格、权益、库存、物流等动态信息只能标为时间未知",
                "minimum_needed": "人工确认页面版本时间和时区",
                "return_to": "human_confirmation",
                "source_file_ids": [],
                "priority": "medium",
                "state": "open",
            }
        )
    rows.append(
        {
            "gap_id": f"GAP-{len(rows) + 1:03d}",
            "category": "页面视觉核对",
            "missing": "逐张视觉确认页面范围、真实顺序、可读性和位置",
            "impact": "来源清单只完成文件固定，尚不能形成正式页面判断",
            "minimum_needed": "逐张打开页面并更新来源清单后再建组件和动作",
            "return_to": "page_material",
            "source_file_ids": [],
            "priority": "high",
            "state": "open",
        }
    )
    return rows


def initial_coverage(scope: str, task: str) -> list[dict[str, Any]]:
    """Create explicit unknown coverage rows; visual review must upgrade them."""
    scopes = ("main_images", "detail_page") if scope == "combined" else (scope,)
    versions = ("current", "comparison") if task == "version_review" else ("current",)
    rows: list[dict[str, Any]] = []
    for version in versions:
        for page_scope in scopes:
            rows.append(
                {
                    "coverage_id": f"COV-{len(rows) + 1:03d}",
                    "source_version": version,
                    "scope": page_scope,
                    "page_declared_count": "unknown",
                    "observed_source_count": 0,
                    "quality_excluded_count": 0,
                    "readable_source_count": 0,
                    "sequence_gap": True,
                    "coverage_status": "unknown",
                    "basis": "尚未逐张核对页面范围、顺序与可读性。",
                    "boundary": "只描述本次已提供页面资料的覆盖情况，不推断平台页面完整性。",
                }
            )
    return rows


def init_delivery(
    out: Path,
    page_sources: Path,
    product_value: Path | None,
    value_expression: Path | None,
    brand: str,
    product: str,
    category: str,
    sku: str,
    scope: str,
    task: str,
    delivery_mode: str,
    page_snapshot_time: str,
    entry_context: str,
    comparison_sources: Path | None,
    comparison_snapshot_time: str = "unknown",
) -> dict[str, Any]:
    if scope not in SCOPES:
        raise ValueError(f"scope 必须是 {sorted(SCOPES)} 之一")
    validate_output_location(out, page_sources, comparison_sources)
    final_out = out.expanduser().resolve()
    if final_out.exists() and any(final_out.iterdir()):
        raise FileExistsError(f"目标目录不是空目录，拒绝覆盖: {final_out}")
    preexisting_empty = final_out.exists()
    identity, snapshot, run_status, limitations = prepare_inputs(
        product_value, value_expression, brand, product, category, sku
    )
    validate_mode_contract(task, delivery_mode, run_status, entry_context, comparison_sources)
    timestamp = now_iso()
    page_snapshot_time = page_snapshot_time.strip() or "unknown"
    comparison_snapshot_time = comparison_snapshot_time.strip() or "unknown"
    if task == "version_review" and (
        page_snapshot_time == "unknown" or comparison_snapshot_time == "unknown"
    ):
        raise ValueError("version_review 必须提供当前版和对照版的页面时间")
    output_version = "V1"
    final_out.parent.mkdir(parents=True, exist_ok=True)
    staging = final_out.parent / f".{final_out.name}.tmp-{uuid.uuid4().hex}"
    try:
        data = staging / "data"
        data.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "skill_version": SKILL_VERSION,
            "product_page_id": product_page_id(
                identity["brand"], identity["product"], identity["sku"], output_version
            ),
            **identity,
            "scope": scope,
            "task": task,
            "delivery_mode": delivery_mode,
            "run_status": run_status,
            "analysis_status": "draft",
            "delivery_status": "blocked",
            "page_snapshot_time": page_snapshot_time,
            "entry_context": entry_context.strip(),
            "cross_surface_summary": "" if scope == "combined" else "not_applicable",
            "output_version": output_version,
            "source_count": 0,
            "limitations": limitations,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        write_json(data / "page_manifest.json", manifest)
        write_json(data / "upstream_snapshot.json", snapshot)
        write_json(
            data / "page_chain.json",
            {
                "schema_version": SCHEMA_VERSION,
                "page_role": "unknown",
                "page_role_basis": "unknown",
                "entry_context_basis": "unknown",
                "precompleted_decisions": [],
                "remaining_decision_tasks": list(DECISION_NAMES),
                "dominant_route": "",
                "parallel_routes": [],
                "category_must_answer_tasks": [],
                "surface_coverage": [
                    {
                        "surface": surface,
                        "status": (
                            "unknown"
                            if surface in {"main_images", "detail_page"}
                            else "not_provided"
                        ),
                        "source_file_ids": [],
                        "boundary": "尚未完成页面表面核对。",
                    }
                    for surface in (
                        "shelf_entry",
                        "main_images",
                        "transaction_panel",
                        "detail_page",
                    )
                ],
                "ordered_component_ids": [],
                "decision_closure": {
                    "status": "unknown",
                    "closure_component_id": "",
                    "closure_reason": "",
                    "unresolved_before_closure": [],
                },
                "continuation_handoffs": [],
                "chain_findings": [],
                "aggregate_implications": [],
                "cross_surface_consistency": {
                    "status": "unknown",
                    "checked_surfaces": [],
                    "summary": "",
                    "inconsistencies": [],
                },
                "presentation_actuality_checks": [],
                "eligibility_gate": {
                    "status": "unknown",
                    "target_user_or_object": "",
                    "life_stage_or_state": "",
                    "use_context": "",
                    "primary_task": "",
                    "exclusions_or_switch_conditions": [],
                    "supporting_component_ids": [],
                    "unresolved_questions": [],
                },
                "variant_routes": [],
                "quantified_claim_checks": [],
                "current_transaction": {
                    "transaction_role": "unknown",
                    "regulated_product_type": "unknown",
                    "current_sku_id": identity["sku"],
                    "current_variant_id": "",
                    "current_quantity_or_size": "",
                    "current_price_snapshot": "",
                    "variant_dimensions": [],
                    "selection_dimension_order": [],
                    "raw_spec_groups": [],
                    "bundle_contents": [],
                    "upgrade_comparison_status": "not_applicable",
                },
                "cross_surface_sku_consistency": {
                    "current_sku_id": identity["sku"],
                    "current_variant_id": "",
                    "current_quantity_or_size": "",
                    "current_price_snapshot": "",
                    "surface_checks": [],
                    "inconsistencies": [],
                },
                "post_purchase_handoff": {
                    "status": "unknown",
                    "next_task": "",
                    "boundary": "尚未完成当前交易后的承接判断。",
                },
                "limitations": ["初始化不生成页面结论。"],
            },
        )
        for filename in (
            "source_inventory.jsonl",
            "page_component_ledger.jsonl",
            "decision_ledger.jsonl",
            "action_ledger.jsonl",
            "validation_ledger.jsonl",
        ):
            write_jsonl(data / filename, [])
        write_jsonl(data / "page_coverage.jsonl", initial_coverage(scope, task))
        write_jsonl(
            data / "gap_ledger.jsonl",
            initial_gaps(run_status, page_snapshot_time, snapshot),
        )
        if task == "route":
            write_json(
                data / "routing_decision.json",
                {
                    "routing_decision_id": "ROUTE-001",
                    "recommended_route": "shared_master",
                    "entry_context": entry_context.strip(),
                    "decision_summary": "",
                    "shared_invariants": [],
                    "change_scope": [],
                    "activation_conditions": [],
                    "standalone_gate": {
                        "entry_difference": "unknown",
                        "business_scale": "unknown",
                        "evidence_support": "unknown",
                        "maintenance_capacity": "unknown",
                    },
                    "source_file_ids": [],
                    "component_ids": [],
                    "fact_ids": [],
                    "value_ids": [],
                    "vis_ids": [],
                    "human_confirmation": [],
                    "status": "blocked",
                    "boundary": "",
                },
            )

        assets = Path(__file__).resolve().parent.parent / "assets"
        if delivery_mode == "course":
            shutil.copy2(
                assets / f"{COURSE_REPORT.removesuffix('.md')}模板.md",
                staging / COURSE_REPORT,
            )
        else:
            for name in PROFESSIONAL_REPORTS:
                shutil.copy2(assets / f"{name.removesuffix('.md')}模板.md", staging / name)

        index_sources(page_sources, staging, "current", page_snapshot_time)
        if comparison_sources is not None:
            index_sources(
                comparison_sources,
                staging,
                "comparison",
                comparison_snapshot_time,
            )
        manifest = read_json(data / "page_manifest.json")
        manifest["updated_at"] = now_iso()
        write_json(data / "page_manifest.json", manifest)
        if final_out.exists():
            final_out.rmdir()
        staging.replace(final_out)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if preexisting_empty and not final_out.exists():
            final_out.mkdir(parents=True, exist_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--page-sources", required=True, type=Path)
    parser.add_argument("--product-value", type=Path)
    parser.add_argument("--value-expression", type=Path)
    parser.add_argument("--brand", default="")
    parser.add_argument("--product", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--sku", default="")
    parser.add_argument("--scope", choices=sorted(SCOPES), default="combined")
    parser.add_argument("--task", choices=sorted(TASKS), default="diagnose")
    parser.add_argument("--delivery-mode", choices=sorted(DELIVERY_MODES), default="course")
    parser.add_argument("--page-snapshot-time", default="unknown")
    parser.add_argument("--entry-context", default="")
    parser.add_argument("--comparison-sources", type=Path)
    parser.add_argument("--comparison-snapshot-time", default="unknown")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kwargs = {
        "out": args.out,
        "page_sources": args.page_sources,
        "product_value": args.product_value,
        "value_expression": args.value_expression,
        "brand": args.brand,
        "product": args.product,
        "category": args.category,
        "sku": args.sku,
        "scope": args.scope,
        "task": args.task,
        "delivery_mode": args.delivery_mode,
        "page_snapshot_time": args.page_snapshot_time,
        "entry_context": args.entry_context,
        "comparison_sources": args.comparison_sources,
        "comparison_snapshot_time": args.comparison_snapshot_time,
    }
    if args.dry_run:
        result = build_plan(**kwargs)
    else:
        result = init_delivery(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
