"""Synthetic end-to-end tests for BrandBAI Product Page."""

from __future__ import annotations

import base64
import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from build_product_page_report import build_delivery
from index_page_sources import build_plan as build_index_plan
from index_page_sources import index_sources
from init_product_page_delivery import build_plan, init_delivery
from product_page_common import (
    DECISION_NAMES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    file_sha256,
    now_iso,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)
from validate_product_page_delivery import validate_delivery


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def make_page_sources(root: Path) -> Path:
    sources = root / "page-sources"
    sources.mkdir(parents=True)
    (sources / "01_main.png").write_bytes(PNG_1X1)
    (sources / "02_detail.png").write_bytes(PNG_1X1 + b"detail")
    return sources


def make_product_value(root: Path) -> Path:
    delivery = root / "product-value"
    data = delivery / "data"
    data.mkdir(parents=True)
    timestamp = now_iso()
    write_json(
        data / "product_manifest.json",
        {
            "product_value_id": "PV-0123456789ab",
            "brand": "测试品牌",
            "product": "测试饮品",
            "category": "饮料",
            "sku": "300毫升乘12瓶",
            "output_version": "V1",
            "analysis_status": "partial",
            "delivery_status": "conditional",
            "updated_at": timestamp,
        },
    )
    write_jsonl(
        data / "fact_ledger.jsonl",
        [
            {
                "fact_id": "F-001",
                "fact_type": "F-PAGE",
                "statement": "当前SKU为每瓶300毫升、每箱12瓶。",
                "locator": "商品规格区",
                "boundary": "只适用于当前SKU。",
            },
            {
                "fact_id": "F-002",
                "fact_type": "F-PAGE",
                "statement": "页面公开主张入口有气泡感。",
                "locator": "商品详情页",
                "boundary": "不代表所有用户体验相同。",
            },
        ],
    )
    write_jsonl(
        data / "value_ledger.jsonl",
        [
            {
                "value_id": "V-001",
                "layer": "P0",
                "value_statement": "入口气泡感容易被感知",
                "user_task": "快速看懂核心体验",
                "downstream_readiness": "ready",
                "cannot_prove": ["不能承诺所有人的体验一致"],
            },
            {
                "value_id": "V-002",
                "layer": "P1",
                "value_statement": "当前规格清楚",
                "user_task": "确认实际到手",
                "downstream_readiness": "ready",
                "cannot_prove": [],
            },
        ],
    )
    write_json(
        data / "p0_decision.json",
        {
            "decision_id": "P0D-001",
            "status": "P0-SELECTED",
            "recommended_value_id": "V-001",
        },
    )
    return delivery


def make_value_expression(root: Path) -> Path:
    delivery = root / "value-expression"
    data = delivery / "data"
    data.mkdir(parents=True)
    write_json(
        data / "expression_manifest.json",
        {
            "value_expression_id": "VE-0123456789ab",
            "product_value_id": "PV-0123456789ab",
            "brand": "测试品牌",
            "product": "测试饮品",
            "category": "饮料",
            "sku": "300毫升乘12瓶",
            "output_version": "V1",
            "analysis_status": "partial",
            "delivery_status": "conditional",
        },
    )
    product_data = root / "product-value" / "data"
    product_manifest = read_json(product_data / "product_manifest.json")
    product_decision = read_json(product_data / "p0_decision.json")
    required_product_files = (
        "product_manifest.json", "fact_ledger.jsonl", "value_ledger.jsonl", "p0_decision.json",
    )
    write_json(
        data / "upstream_snapshot.json",
        {
            "product_value_id": "PV-0123456789ab",
            "upstream_output_version": product_manifest["output_version"],
            "upstream_analysis_status": product_manifest["analysis_status"],
            "upstream_delivery_status": product_manifest["delivery_status"],
            "p0_status": product_decision["status"],
            "recommended_value_id": product_decision["recommended_value_id"],
            "file_hashes": {
                name: file_sha256(product_data / name) for name in required_product_files
            },
            "captured_at": now_iso(),
        },
    )
    write_jsonl(
        data / "vis_ledger.jsonl",
        [
            {
                "vis_id": "VIS-001",
                "value_id": "V-001",
                "decision_task": "看懂",
                "human_language": "用真实开瓶与倒杯动作呈现气泡状态。",
                "must_keep": "商品身份与真实动作。",
                "misuse": "不能承诺每个人体验相同。",
                "boundary": "待验证呈现建议。",
                "applicable_objects": ["商品页"],
                "validation_status": "suggested_untested",
            }
        ],
    )
    return delivery


def reviewed_sources(delivery: Path) -> list[dict[str, object]]:
    path = delivery / "data" / "source_inventory.jsonl"
    rows = read_jsonl(path)
    rows[0].update(
        {
            "page_scope": "main_images",
            "page_location": "主图第1张",
            "sequence": 1,
            "sequence_status": "confirmed",
            "readability_status": "readable",
            "notes": "已逐图核对。",
        }
    )
    rows[1].update(
        {
            "page_scope": "detail_page",
            "page_location": "详情页首屏",
            "sequence": 1,
            "sequence_status": "confirmed",
            "readability_status": "readable",
            "notes": "已逐图核对。",
        }
    )
    write_jsonl(path, rows)
    review_coverage(delivery)
    return rows


def review_coverage(delivery: Path) -> None:
    data = delivery / "data"
    sources = read_jsonl(data / "source_inventory.jsonl")
    coverage_path = data / "page_coverage.jsonl"
    coverage = read_jsonl(coverage_path)
    for item in coverage:
        pair_sources = [
            row for row in sources
            if row.get("source_version") == item.get("source_version")
            and row.get("page_scope") == item.get("scope")
            and not row.get("duplicate_of")
        ]
        excluded = len([row for row in pair_sources if row.get("quality_excluded") is True])
        readable = len([
            row for row in pair_sources
            if row.get("quality_excluded") is not True
            and row.get("readability_status") in {"readable", "partially_readable"}
        ])
        sequence_values = [int(row["sequence"]) for row in pair_sources]
        sequence_gap = bool(sequence_values) and sorted(sequence_values) != list(
            range(1, max(sequence_values) + 1)
        )
        complete = bool(pair_sources) and readable + excluded == len(pair_sources) and not sequence_gap
        item.update(
            {
                "page_declared_count": len(pair_sources) if pair_sources else "unknown",
                "observed_source_count": len(pair_sources),
                "quality_excluded_count": excluded,
                "readable_source_count": readable,
                "sequence_gap": sequence_gap,
                "coverage_status": "complete_observed" if complete else "unknown",
                "basis": "已逐张核对本次提供的页面文件、真实顺序与可读性。" if complete else "当前范围没有可核对页面。",
                "boundary": "只确认本次提供资料的覆盖，不代表平台页面没有其他未提供模块。",
            }
        )
    write_jsonl(coverage_path, coverage)


def component_rows(with_upstream: bool = True) -> list[dict[str, object]]:
    upstream = {
        "fact_ids": ["F-001", "F-002"],
        "value_ids": ["V-001"],
        "vis_ids": ["VIS-001"],
    } if with_upstream else {"fact_ids": [], "value_ids": [], "vis_ids": []}
    return [
        {
            "component_id": "COMP-001",
            "scope": "main_images",
            "page_location": "主图第1张",
            "sequence": 1,
            "source_file_ids": ["PAGE-SF-001"],
            "readability_status": "readable",
            "current_observation": "首图能认出商品，但当前SKU规格不够清楚。",
            "page_says": "测试饮品",
            "page_shows": "商品正面包装",
            "decision_names": ["认对", "选对"],
            **upstream,
            "dynamic_status": "not_dynamic",
            "content_layer": "evergreen_product",
            "module_role": "identity",
            "information_node_type": "identity",
            "primary_decision_name": "认对",
            "match_status": "partially_matched",
            "predecessor_requirement": "not_applicable",
            "next_node_or_touchpoint": "详情页首屏",
            "comparison_dimension": "",
            "package_version_status": "current_confirmed",
            "component_applicability": "current_sku",
            "target_user_or_object": "普通消费者",
            "variant_id": "",
            "claim_scope": "current_sku",
            "adjacency_status": "not_applicable",
            "valid_time_or_unknown": "not_applicable",
            "claim_level": "product_fact",
            "support_target": "not_applicable",
            "current_role": "商品识别",
            "recommended_role": "商品与当前SKU共同识别",
            "change_type": "补充",
            "execution_instruction": "保留商品正面并补充当前规格和整箱数量。",
            "required_material": "当前SKU包装正面与规格文字",
            "acceptance_check": "只看首图能否说清收到哪一款和多少瓶。",
            "status": "suggested_untested",
            "boundary": "不加入未确认价格或赠品。",
        },
        {
            "component_id": "COMP-002",
            "scope": "detail_page",
            "page_location": "详情页首屏",
            "sequence": 1,
            "source_file_ids": ["PAGE-SF-002"],
            "readability_status": "readable",
            "current_observation": "详情页先写品牌口号，核心体验出现较晚。",
            "page_says": "随时来一瓶",
            "page_shows": "商品与背景场景",
            "decision_names": ["看懂", "相信", "放心买"],
            **upstream,
            "dynamic_status": "not_dynamic",
            "content_layer": "evergreen_product",
            "module_role": "value_claim",
            "information_node_type": "value",
            "primary_decision_name": "看懂",
            "match_status": "partially_matched",
            "predecessor_requirement": "先认对商品和当前SKU",
            "next_node_or_touchpoint": "详情页证明模块",
            "comparison_dimension": "",
            "package_version_status": "not_applicable",
            "component_applicability": "current_sku",
            "target_user_or_object": "普通消费者",
            "variant_id": "",
            "claim_scope": "current_sku",
            "adjacency_status": "adjacent",
            "valid_time_or_unknown": "not_applicable",
            "claim_level": "page_claim",
            "support_target": "入口气泡感容易被感知",
            "current_role": "品牌氛围",
            "recommended_role": "承接核心价值并保留品牌识别",
            "change_type": "重新组织",
            "execution_instruction": "用已确认呈现单元承接核心价值，再进入品牌氛围。",
            "required_material": "开瓶与倒杯动作素材",
            "acceptance_check": "首屏能否让用户复述核心体验且不扩大承诺。",
            "status": "suggested_untested",
            "boundary": "页面公开主张不自动写成用户普遍体验。",
        },
    ]


def decision_rows(with_upstream: bool = True) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, name in enumerate(DECISION_NAMES, start=1):
        if name in {"认对", "选对"}:
            source_ids = ["PAGE-SF-001"]
            component_ids = ["COMP-001"]
        else:
            source_ids = ["PAGE-SF-002"]
            component_ids = ["COMP-002"]
        rows.append(
            {
                "decision_id": f"DEC-{index:02d}",
                "decision_name": name,
                "status": "部分讲清" if name in {"认对", "看懂", "相信", "选对"} else "资料不足",
                "summary": f"当前页面对{name}只完成了部分信息承接。",
                "source_file_ids": source_ids,
                "component_ids": component_ids,
                "fact_ids": ["F-001"] if with_upstream else [],
                "value_ids": ["V-001"] if with_upstream else [],
                "vis_ids": ["VIS-001"] if with_upstream else [],
                "unknowns": ["价格、物流和售后时点信息未提供"] if name == "放心买" else [],
                "boundary": "只判断当前可读页面，不推断未提供模块。",
            }
        )
    return rows


def action_row(
    action_id: str,
    priority: int,
    scope: str,
    location: str,
    component_id: str,
    source_id: str,
    with_upstream: bool = True,
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "priority": priority,
        "scope": scope,
        "page_location": location,
        "decision_name": "认对" if scope == "main_images" else "看懂",
        "current_observation": "页面当前能认出商品，但关键判断还没有一次讲清。",
        "gap_or_risk": "用户可能需要跨页面寻找规格或核心价值。",
        "basis_type": "product_value_and_value_expression" if with_upstream else "page_visible_only",
        "basis_summary": "当前SKU事实、既定核心价值与待验证呈现" if with_upstream else "仅依据当前页面可见信息",
        "source_file_ids": [source_id],
        "component_ids": [component_id],
        "fact_ids": ["F-001"] if with_upstream else [],
        "value_ids": ["V-001"] if with_upstream else [],
        "vis_ids": ["VIS-001"] if with_upstream else [],
        "action_type": "补充",
        "action_detail": "在当前页面位置补齐当前SKU与用户要完成的主要判断。",
        "must_preserve": "商品身份、当前SKU事实和不能证明什么。",
        "material_needed": "当前SKU包装图与已确认呈现素材。",
        "human_confirmation": "页面负责人确认规格与动态信息。",
        "acceptance_check": "用户只看这一位置能否说清商品、规格和主要价值。",
        "validation_question": "改版后是否更容易完成该项页面判断。",
        "status": "suggested_untested",
        "boundary": "这是待验证页面动作，不代表已经有效。",
    }


def page_chain(components: list[dict[str, object]], sku: str = "300毫升乘12瓶") -> dict[str, object]:
    component_ids = [str(item["component_id"]) for item in components]
    return {
        "schema_version": SCHEMA_VERSION,
        "page_role": "single_product_page",
        "page_role_basis": "page_visible_inference",
        "entry_context_basis": "unknown",
        "precompleted_decisions": [],
        "remaining_decision_tasks": ["认对", "看懂", "相信", "选对", "放心买"],
        "dominant_route": "认对当前SKU后承接核心体验，再进入证明和到手确认",
        "parallel_routes": [],
        "category_must_answer_tasks": ["商品与规格", "核心体验", "事实支持", "实际到手"],
        "surface_coverage": [
            {"surface": "shelf_entry", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供货架外显。"},
            {"surface": "main_images", "status": "observed", "source_file_ids": ["PAGE-SF-001"], "boundary": "只核对本次主图资料。"},
            {"surface": "transaction_panel", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供交易区。"},
            {"surface": "detail_page", "status": "observed", "source_file_ids": ["PAGE-SF-002"], "boundary": "只核对本次详情页资料。"},
        ],
        "ordered_component_ids": component_ids,
        "decision_closure": {
            "status": "partially_closed",
            "closure_component_id": "",
            "closure_reason": "商品身份和核心体验已有承接，但交易信息未提供。",
            "unresolved_before_closure": ["当前价格与实际到手"],
        },
        "continuation_handoffs": [],
        "chain_findings": [],
        "aggregate_implications": [],
        "cross_surface_consistency": {
            "status": "partially_checked",
            "checked_surfaces": ["main_images", "detail_page"],
            "summary": "主图与详情页商品身份一致。",
            "inconsistencies": [],
        },
        "presentation_actuality_checks": [],
        "eligibility_gate": {
            "status": "not_applicable",
            "target_user_or_object": "普通消费者",
            "life_stage_or_state": "not_applicable",
            "use_context": "日常饮用",
            "primary_task": "快速确认商品与核心体验",
            "exclusions_or_switch_conditions": [],
            "supporting_component_ids": [],
            "unresolved_questions": [],
        },
        "variant_routes": [],
        "quantified_claim_checks": [],
        "current_transaction": {
            "transaction_role": "standard",
            "regulated_product_type": "ordinary_consumer_product",
            "current_sku_id": sku,
            "current_variant_id": "",
            "current_quantity_or_size": "12瓶装",
            "current_price_snapshot": "",
            "variant_dimensions": ["quantity"],
            "selection_dimension_order": ["quantity"],
            "raw_spec_groups": [
                {
                    "group_name": "规格",
                    "current_value": "12瓶装",
                    "normalized_dimensions": ["quantity"],
                    "mixing_status": "single_dimension",
                    "boundary": "平台规格组只承担数量选择。",
                }
            ],
            "bundle_contents": [],
            "upgrade_comparison_status": "not_applicable",
        },
        "cross_surface_sku_consistency": {
            "current_sku_id": sku,
            "current_variant_id": "",
            "current_quantity_or_size": "12瓶装",
            "current_price_snapshot": "",
            "surface_checks": [
                {"surface": "main_images", "represented_sku_or_variant": sku, "represented_quantity_or_size": "12瓶装", "represented_price_or_offer": "", "relationship": "matched"},
                {"surface": "detail_page", "represented_sku_or_variant": sku, "represented_quantity_or_size": "12瓶装", "represented_price_or_offer": "", "relationship": "matched"},
            ],
            "inconsistencies": [],
        },
        "post_purchase_handoff": {
            "status": "not_checked",
            "next_task": "",
            "boundary": "本轮不判断复购或关联商品。",
        },
        "limitations": ["未提供货架外显、交易区和经营数据。"],
    }


def populate_ready(delivery: Path) -> None:
    reviewed_sources(delivery)
    data = delivery / "data"
    manifest = read_json(data / "page_manifest.json")
    manifest.update(
        {
            "run_status": "ready",
            "analysis_status": "partial",
            "delivery_status": "conditional",
            "cross_surface_summary": "主图与详情页商品身份一致，但规格和核心价值的承接仍不完整。",
            "limitations": ["当前只有静态页面资料，未提供经营数据。"],
            "updated_at": now_iso(),
        }
    )
    write_json(data / "page_manifest.json", manifest)
    components = component_rows()
    write_jsonl(data / "page_component_ledger.jsonl", components)
    write_json(data / "page_chain.json", page_chain(components))
    write_jsonl(data / "decision_ledger.jsonl", decision_rows())
    write_jsonl(
        data / "action_ledger.jsonl",
        [
            action_row("ACT-001", 1, "main_images", "主图第1张", "COMP-001", "PAGE-SF-001"),
            action_row("ACT-002", 2, "detail_page", "详情页首屏", "COMP-002", "PAGE-SF-002"),
        ],
    )
    write_jsonl(data / "validation_ledger.jsonl", [])
    write_jsonl(data / "gap_ledger.jsonl", [])


def populate_degraded(delivery: Path) -> None:
    reviewed_sources(delivery)
    data = delivery / "data"
    manifest = read_json(data / "page_manifest.json")
    manifest.update(
        {
            "run_status": "degraded_no_product_value",
            "analysis_status": "partial",
            "delivery_status": "conditional",
            "cross_surface_summary": "只能确认两处页面的SKU表达不够集中，不能判断核心价值承接。",
            "limitations": ["未提供当前SKU的有效商品价值底座。"],
            "updated_at": now_iso(),
        }
    )
    write_json(data / "page_manifest.json", manifest)
    components = component_rows(with_upstream=False)
    write_jsonl(data / "page_component_ledger.jsonl", components)
    write_json(data / "page_chain.json", page_chain(components))
    write_jsonl(data / "decision_ledger.jsonl", decision_rows(with_upstream=False))
    write_jsonl(
        data / "action_ledger.jsonl",
        [action_row("ACT-001", 1, "main_images", "主图第1张", "COMP-001", "PAGE-SF-001", with_upstream=False)],
    )
    write_jsonl(data / "validation_ledger.jsonl", [])
    write_jsonl(
        data / "gap_ledger.jsonl",
        [
            {
                "gap_id": "GAP-001",
                "category": "商品价值",
                "missing": "当前SKU的有效商品价值底座",
                "impact": "不能决定核心卖点和页面价值顺序",
                "minimum_needed": "先完成BrandBAI商品价值底座",
                "return_to": "product_value",
                "source_file_ids": [],
                "priority": "high",
                "state": "open",
            }
        ],
    )


def route_record(entry_context: str) -> dict[str, object]:
    return {
        "routing_decision_id": "ROUTE-001",
        "recommended_route": "shared_master",
        "entry_context": entry_context,
        "decision_summary": "当前没有足够证据支持另建独立页面，先维护一套共用母版。",
        "shared_invariants": ["商品身份、当前SKU、核心价值和事实边界保持不变"],
        "change_scope": ["只调整入口首屏承接，不改写商品价值"],
        "activation_conditions": [],
        "standalone_gate": {
            "entry_difference": "unknown",
            "business_scale": "unknown",
            "evidence_support": "unknown",
            "maintenance_capacity": "unknown",
        },
        "source_file_ids": ["PAGE-SF-001"],
        "component_ids": ["COMP-001"],
        "fact_ids": ["F-001"],
        "value_ids": ["V-001"],
        "vis_ids": [],
        "human_confirmation": ["页面负责人确认入口任务和维护能力"],
        "status": "suggested_untested",
        "boundary": "这是页面维护与分版建议，不代表页面有效或会改善经营结果。",
    }


def assert_error(delivery: Path, code: str) -> None:
    result = validate_delivery(delivery)
    assert result["status"] == "failed", json.dumps(result, ensure_ascii=False, indent=2)
    assert any(error.startswith(f"{code}:") for error in result["errors"]), json.dumps(
        result, ensure_ascii=False, indent=2
    )


def run_test() -> None:
    test_parent = Path.cwd() / "_skill_test_artifacts"
    test_parent.mkdir(parents=True, exist_ok=True)
    temp_root = test_parent / f"brandbai-product-page-{uuid.uuid4().hex}"
    temp_root.mkdir()
    try:
        sources = make_page_sources(temp_root)
        product_value = make_product_value(temp_root)
        value_expression = make_value_expression(temp_root)

        course = temp_root / "course-ready"
        plan = build_plan(
            course, sources, product_value, value_expression,
            "", "", "", "", "combined", "diagnose", "course",
            "2026-08-11T10:00:00+08:00", "", None,
        )
        assert plan["dry_run"] is True
        assert not course.exists(), "dry-run不得创建交付目录"
        assert "data/page_chain.json" in plan["will_create"], "dry-run必须完整声明page_chain交付文件"
        init_delivery(
            course, sources, product_value, value_expression,
            "", "", "", "", "combined", "diagnose", "course",
            "2026-08-11T10:00:00+08:00", "", None,
        )
        populate_ready(course)
        indexed_before = read_jsonl(course / "data" / "source_inventory.jsonl")
        for operation in (
            lambda: build_index_plan(
                sources, course, "comparison", "2026-08-10T10:00:00+08:00"
            ),
            lambda: index_sources(
                sources, course, "comparison", "2026-08-10T10:00:00+08:00"
            ),
        ):
            try:
                operation()
                raise AssertionError("diagnose交付的comparison索引预览与正式执行都必须拒绝")
            except ValueError as exc:
                assert "comparison来源只允许" in str(exc)
        assert read_jsonl(course / "data" / "source_inventory.jsonl") == indexed_before
        nested_source = course / "nested-source.png"
        nested_source.write_bytes(PNG_1X1)
        for operation in (
            lambda: build_index_plan(nested_source, course, "current", ""),
            lambda: index_sources(nested_source, course, "current", ""),
        ):
            try:
                operation()
                raise AssertionError("页面来源与交付目录互相包含时预览与正式执行都必须拒绝")
            except ValueError as exc:
                assert "不能互相包含" in str(exc)
        nested_source.unlink()
        assert build_delivery(course, write=False)["status"] == "dry_run"
        build_delivery(course, write=True)
        passed = validate_delivery(course)
        assert passed["status"] == "passed", json.dumps(passed, ensure_ascii=False, indent=2)
        report = (course / "01_商品页诊断与优化建议.md").read_text(encoding="utf-8")
        assert "放心买" in report
        assert "这张页面主要负责：单品价值页" in report
        assert "用户进页前已可靠完成：没有可靠证据表明某项已经完成" in report
        assert "页面还必须补齐：认对、看懂、相信、选对、放心买" in report
        assert "规格选择顺序：数量" in report
        assert "已核对" in report and "本次提供范围已逐张看完" in report
        assert "### 优先 1｜主图第1张（认对）" in report
        assert "- 现在的问题：" in report and "- 改完怎么检查：" in report
        assert "| 优先顺序 |" not in report
        assert "by 布兰德老白 BrandBAI" in report
        assert "ACT-001" not in report and "V-001" not in report

        excluded_sources = read_jsonl(course / "data" / "source_inventory.jsonl")
        excluded_source = deepcopy(excluded_sources[0])
        excluded_source.update(
            {
                "source_file_id": "PAGE-SF-003",
                "relative_path": "03_divider.png",
                "file_name": "03_divider.png",
                "sha256": "f" * 64,
                "page_scope": "unknown",
                "page_location": "非页面分隔条",
                "sequence": 3,
                "sequence_status": "not_applicable",
                "readability_status": "unreadable",
                "quality_excluded": True,
                "quality_exclusion_reason": "纯分隔条，不属于页面内容。",
            }
        )
        excluded_sources.append(excluded_source)
        write_jsonl(course / "data" / "source_inventory.jsonl", excluded_sources)
        excluded_manifest = read_json(course / "data" / "page_manifest.json")
        excluded_manifest["source_count"] = len(excluded_sources)
        write_json(course / "data" / "page_manifest.json", excluded_manifest)
        build_delivery(course, write=True)
        excluded_result = validate_delivery(course)
        assert excluded_result["status"] == "passed", json.dumps(
            excluded_result, ensure_ascii=False, indent=2
        )

        hypothesis_root = temp_root / "hypothesis-upstream"
        shutil.copytree(product_value, hypothesis_root)
        hypothesis_decision_path = hypothesis_root / "data" / "p0_decision.json"
        hypothesis_decision = read_json(hypothesis_decision_path)
        hypothesis_decision["status"] = "P0-HYPOTHESIS"
        write_json(hypothesis_decision_path, hypothesis_decision)
        hypothesis_expression = temp_root / "hypothesis-expression"
        shutil.copytree(value_expression, hypothesis_expression)
        hypothesis_upstream_path = hypothesis_expression / "data" / "upstream_snapshot.json"
        hypothesis_upstream = read_json(hypothesis_upstream_path)
        hypothesis_upstream["p0_status"] = "P0-HYPOTHESIS"
        hypothesis_upstream["file_hashes"]["p0_decision.json"] = file_sha256(
            hypothesis_decision_path
        )
        write_json(hypothesis_upstream_path, hypothesis_upstream)
        hypothesis_plan = build_plan(
            temp_root / "hypothesis-page", sources, hypothesis_root, hypothesis_expression,
            "", "", "", "", "combined", "diagnose", "professional",
            "2026-08-11T10:00:00+08:00", "", None,
        )
        assert hypothesis_plan["initial_run_status"] == "partial"
        assert any("待验证假设" in item for item in hypothesis_plan["limitations"])

        degraded = temp_root / "course-degraded"
        init_delivery(
            degraded, sources, None, None,
            "测试品牌", "测试饮品", "饮料", "300毫升乘12瓶",
            "combined", "diagnose", "course", "2026-08-11T10:00:00+08:00", "", None,
        )
        populate_degraded(degraded)
        build_delivery(degraded, write=True)
        degraded_result = validate_delivery(degraded)
        assert degraded_result["status"] == "passed", json.dumps(
            degraded_result, ensure_ascii=False, indent=2
        )
        degraded_report = (degraded / "01_商品页诊断与优化建议.md").read_text(encoding="utf-8")
        assert "本轮可基于现有页面完成诊断" in degraded_report
        assert "不得新增资料外主张" in degraded_report
        assert "unreadable" not in degraded_report

        professional = temp_root / "professional-main-images"
        init_delivery(
            professional, sources, product_value, value_expression,
            "", "", "", "", "main_images", "diagnose", "professional",
            "2026-08-11T10:00:00+08:00", "", None,
        )
        reviewed_sources(professional)
        data = professional / "data"
        manifest = read_json(data / "page_manifest.json")
        manifest.update(
            {
                "run_status": "ready",
                "analysis_status": "partial",
                "delivery_status": "conditional",
                "cross_surface_summary": "not_applicable",
                "limitations": ["只检查主图。"],
                "updated_at": now_iso(),
            }
        )
        write_json(data / "page_manifest.json", manifest)
        pro_component = component_rows()[0]
        pro_component["decision_names"] = list(DECISION_NAMES)
        write_jsonl(data / "page_component_ledger.jsonl", [pro_component])
        pro_chain = page_chain([pro_component])
        pro_chain["surface_coverage"] = [
            {"surface": "shelf_entry", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供货架外显。"},
            {"surface": "main_images", "status": "observed", "source_file_ids": ["PAGE-SF-001"], "boundary": "只核对本次主图资料。"},
            {"surface": "transaction_panel", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供交易区。"},
            {"surface": "detail_page", "status": "not_applicable", "source_file_ids": [], "boundary": "本轮不看详情页。"},
        ]
        pro_chain["cross_surface_sku_consistency"]["surface_checks"] = [
            {"surface": "main_images", "represented_sku_or_variant": "300毫升乘12瓶", "represented_quantity_or_size": "12瓶装", "represented_price_or_offer": "", "relationship": "matched"},
        ]
        write_json(data / "page_chain.json", pro_chain)
        pro_decisions = decision_rows()
        for row in pro_decisions:
            row["source_file_ids"] = ["PAGE-SF-001"]
            row["component_ids"] = ["COMP-001"]
        write_jsonl(data / "decision_ledger.jsonl", pro_decisions)
        write_jsonl(
            data / "action_ledger.jsonl",
            [action_row("ACT-001", 1, "main_images", "主图第1张", "COMP-001", "PAGE-SF-001")],
        )
        write_jsonl(data / "validation_ledger.jsonl", [])
        write_jsonl(data / "gap_ledger.jsonl", [])
        build_delivery(professional, write=True)
        pro_result = validate_delivery(professional)
        assert pro_result["status"] == "passed", json.dumps(pro_result, ensure_ascii=False, indent=2)
        assert (professional / "02_主图交易区详情页优化页纲.md").is_file()
        assert (professional / "03_资料缺口与证据边界.md").is_file()
        legacy_report = professional / "02_主图与详情页执行页.md"
        legacy_report.write_text("legacy", encoding="utf-8")
        build_delivery(professional, write=True)
        assert not legacy_report.exists(), "旧版执行页应在重新生成时移除，避免双入口"

        route = temp_root / "professional-route"
        entry_context = "抖音达人挂车内容进入天猫商品页，先判断是否需要独立承接页"
        init_delivery(
            route, sources, product_value, value_expression,
            "", "", "", "", "combined", "route", "professional",
            "2026-08-11T10:00:00+08:00", entry_context, None,
        )
        populate_ready(route)
        write_json(route / "data" / "routing_decision.json", route_record(entry_context))
        build_delivery(route, write=True)
        route_result = validate_delivery(route)
        assert route_result["status"] == "passed", json.dumps(
            route_result, ensure_ascii=False, indent=2
        )
        route_report = (route / "01_商品页诊断与优化建议.md").read_text(encoding="utf-8")
        assert "## 页面共用与分版建议" in route_report
        assert "先用一套共用母版" in route_report and "ROUTE-001" not in route_report

        route_path = route / "data" / "routing_decision.json"
        original_route = read_json(route_path)
        bad_route = deepcopy(original_route)
        bad_route["recommended_route"] = "standalone_page"
        write_json(route_path, bad_route)
        build_delivery(route, write=True)
        assert_error(route, "E_ROUTE_STANDALONE_GATE")
        write_json(route_path, original_route)
        build_delivery(route, write=True)

        current_sources = temp_root / "current-page"
        comparison_sources = temp_root / "comparison-page"
        current_sources.mkdir()
        comparison_sources.mkdir()
        (current_sources / "main.png").write_bytes(PNG_1X1 + b"current")
        (comparison_sources / "main.png").write_bytes(PNG_1X1 + b"comparison")
        version_review = temp_root / "professional-version-review"
        init_delivery(
            version_review, current_sources, product_value, value_expression,
            "", "", "", "", "main_images", "version_review", "professional",
            "2026-08-11T10:00:00+08:00", "", comparison_sources,
            "2026-08-10T10:00:00+08:00",
        )
        version_data = version_review / "data"
        version_sources = read_jsonl(version_data / "source_inventory.jsonl")
        for row in version_sources:
            row.update(
                {
                    "page_scope": "main_images",
                    "page_location": "当前版主图第1张" if row["source_version"] == "current" else "对照版主图第1张",
                    "sequence": 1,
                    "sequence_status": "confirmed",
                    "readability_status": "readable",
                    "notes": "已逐图核对。",
                }
            )
        write_jsonl(version_data / "source_inventory.jsonl", version_sources)
        review_coverage(version_review)
        version_manifest = read_json(version_data / "page_manifest.json")
        version_manifest.update(
            {
                "run_status": "ready",
                "analysis_status": "partial",
                "delivery_status": "conditional",
                "cross_surface_summary": "not_applicable",
                "limitations": ["没有经营数据，只比较静态页面差异，不判版本胜负。"],
                "updated_at": now_iso(),
            }
        )
        write_json(version_data / "page_manifest.json", version_manifest)
        version_component = component_rows()[0]
        version_component["source_file_ids"] = ["PAGE-SF-001", "PAGE-SF-002"]
        version_component["decision_names"] = list(DECISION_NAMES)
        write_jsonl(version_data / "page_component_ledger.jsonl", [version_component])
        version_chain = page_chain([version_component])
        version_chain["surface_coverage"] = [
            {"surface": "shelf_entry", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供货架外显。"},
            {"surface": "main_images", "status": "observed", "source_file_ids": ["PAGE-SF-001", "PAGE-SF-002"], "boundary": "两版主图均已核对。"},
            {"surface": "transaction_panel", "status": "not_provided", "source_file_ids": [], "boundary": "本轮未提供交易区。"},
            {"surface": "detail_page", "status": "not_applicable", "source_file_ids": [], "boundary": "本轮不比较详情页。"},
        ]
        version_chain["cross_surface_sku_consistency"]["surface_checks"] = [
            {"surface": "main_images", "represented_sku_or_variant": "12瓶装", "represented_quantity_or_size": "12瓶装", "represented_price_or_offer": "", "relationship": "matched"},
        ]
        write_json(version_data / "page_chain.json", version_chain)
        version_decisions = decision_rows()
        for row in version_decisions:
            row["source_file_ids"] = ["PAGE-SF-001", "PAGE-SF-002"]
            row["component_ids"] = ["COMP-001"]
        write_jsonl(version_data / "decision_ledger.jsonl", version_decisions)
        version_action = action_row(
            "ACT-001", 1, "main_images", "主图第1张", "COMP-001", "PAGE-SF-001"
        )
        version_action["source_file_ids"] = ["PAGE-SF-001", "PAGE-SF-002"]
        write_jsonl(version_data / "action_ledger.jsonl", [version_action])
        write_jsonl(
            version_data / "validation_ledger.jsonl",
            [
                {
                    "test_id": "TEST-001",
                    "scope": "main_images",
                    "version_a": "comparison",
                    "version_b": "current",
                    "must_keep": "同一商品、SKU、页面范围和事实边界",
                    "single_variable": "主图第1张的规格表达位置",
                    "observation_needed": "下一轮再补流量范围和观察窗口；本轮只看静态差异",
                    "comparability": "部分可比：商品与SKU相同；页面范围相同；价格权益未知；流量范围未提供；观察窗口未提供",
                    "status": "suggested_untested",
                    "boundary": "只比较页面差异，不判胜负、不做因果归因。",
                }
            ],
        )
        write_jsonl(version_data / "gap_ledger.jsonl", [])
        build_delivery(version_review, write=True)
        version_result = validate_delivery(version_review)
        assert version_result["status"] == "passed", json.dumps(
            version_result, ensure_ascii=False, indent=2
        )
        validation_path = version_data / "validation_ledger.jsonl"
        original_validation = read_jsonl(validation_path)
        fake_binding = deepcopy(original_validation)
        fake_binding[0]["version_a"] = "legacy"
        write_jsonl(validation_path, fake_binding)
        assert_error(version_review, "E_VERSION_BINDING")
        write_jsonl(validation_path, original_validation)
        original_version_sources = read_jsonl(version_data / "source_inventory.jsonl")
        bad_version_time = deepcopy(original_version_sources)
        bad_version_time[1]["capture_time"] = "unknown"
        write_jsonl(version_data / "source_inventory.jsonl", bad_version_time)
        assert_error(version_review, "E_VERSION_TIME")
        write_jsonl(version_data / "source_inventory.jsonl", original_version_sources)

        actions_path = course / "data" / "action_ledger.jsonl"
        original_actions = read_jsonl(actions_path)

        six = deepcopy(original_actions)
        while len(six) < 6:
            clone = deepcopy(six[0])
            clone["action_id"] = f"ACT-{len(six) + 1:03d}"
            clone["priority"] = len(six) + 1
            clone["page_location"] = f"主图第{len(six) + 1}张"
            clone["action_detail"] = f"合成边界测试动作{len(six) + 1}。"
            six.append(clone)
        write_jsonl(actions_path, six)
        assert_error(course, "E_ACTION_LIMIT")

        promised = deepcopy(original_actions)
        promised[0]["action_detail"] = "这样修改会提升转化率。"
        write_jsonl(actions_path, promised)
        assert_error(course, "E_EFFECT_PROMISE")

        comment_fact = deepcopy(original_actions)
        comment_fact[0]["basis_summary"] = "评论证明当前规格更受欢迎。"
        write_jsonl(actions_path, comment_fact)
        assert_error(course, "E_COMMENT_AS_PRODUCT_FACT")

        p0_mutation = deepcopy(original_actions)
        p0_mutation[0]["action_detail"] = "重新选择核心价值后再改首图。"
        write_jsonl(actions_path, p0_mutation)
        assert_error(course, "E_P0_MUTATED")

        reopened_boundary = deepcopy(original_actions)
        reopened_boundary[0]["action_detail"] = "突出所有人的体验一致，并把它放进首图主张。"
        write_jsonl(actions_path, reopened_boundary)
        assert_error(course, "E_UPSTREAM_BOUNDARY_REOPENED")

        preserved_boundary = deepcopy(original_actions)
        preserved_boundary[0]["action_detail"] = "保留真实倒杯动作，不承诺所有人的体验一致。"
        write_jsonl(actions_path, preserved_boundary)
        assert validate_delivery(course)["status"] == "passed"

        safe_boundary = deepcopy(original_actions)
        safe_boundary[0]["boundary"] = "当前资料不能证明该动作会提升转化率，只能验证页面判断是否更清楚。"
        write_jsonl(actions_path, safe_boundary)
        assert validate_delivery(course)["status"] == "passed"

        chain_path = course / "data" / "page_chain.json"
        original_chain = read_json(chain_path)

        bad_page_role = deepcopy(original_chain)
        bad_page_role["page_role"] = "万能高转化页"
        write_json(chain_path, bad_page_role)
        assert_error(course, "E_PAGE_ROLE")

        ungrounded_precompleted = deepcopy(original_chain)
        ungrounded_precompleted["precompleted_decisions"] = ["认对"]
        ungrounded_precompleted["remaining_decision_tasks"] = ["看懂", "相信", "选对", "放心买"]
        write_json(chain_path, ungrounded_precompleted)
        assert_error(course, "E_ENTRY_CONTEXT")

        incomplete_selection_order = deepcopy(original_chain)
        incomplete_selection_order["current_transaction"]["variant_dimensions"] = ["flavor", "quantity"]
        incomplete_selection_order["current_transaction"]["selection_dimension_order"] = ["quantity"]
        incomplete_selection_order["current_transaction"]["raw_spec_groups"] = [
            {
                "group_name": "口味",
                "current_value": "红烧牛肉12桶",
                "normalized_dimensions": ["flavor", "quantity"],
                "mixing_status": "mixed",
                "boundary": "平台字段混合口味与数量。",
            }
        ]
        write_json(chain_path, incomplete_selection_order)
        assert_error(course, "E_SELECTION_ORDER")

        missing_raw_spec_groups = deepcopy(original_chain)
        missing_raw_spec_groups["current_transaction"]["raw_spec_groups"] = []
        write_json(chain_path, missing_raw_spec_groups)
        assert_error(course, "E_RAW_SPEC_GROUP")

        false_single_raw_group = deepcopy(original_chain)
        false_single_raw_group["current_transaction"]["variant_dimensions"] = ["flavor", "quantity"]
        false_single_raw_group["current_transaction"]["selection_dimension_order"] = ["flavor", "quantity"]
        false_single_raw_group["current_transaction"]["raw_spec_groups"] = [
            {
                "group_name": "口味",
                "current_value": "红烧牛肉12桶",
                "normalized_dimensions": ["flavor", "quantity"],
                "mixing_status": "single_dimension",
                "boundary": "错误地把混合字段标成单维。",
            }
        ]
        write_json(chain_path, false_single_raw_group)
        assert_error(course, "E_RAW_SPEC_GROUP")

        missing_bundle_contents = deepcopy(original_chain)
        missing_bundle_contents["current_transaction"]["variant_dimensions"] = ["bundle"]
        missing_bundle_contents["current_transaction"]["selection_dimension_order"] = ["bundle"]
        missing_bundle_contents["current_transaction"]["bundle_contents"] = []
        write_json(chain_path, missing_bundle_contents)
        assert_error(course, "E_BUNDLE_CONTENTS")

        unknown_transaction_role = deepcopy(original_chain)
        unknown_transaction_role["current_transaction"]["transaction_role"] = "unknown"
        write_json(chain_path, unknown_transaction_role)
        assert_error(course, "E_TRANSACTION_ROLE")

        high_risk_unresolved = deepcopy(original_chain)
        high_risk_unresolved["current_transaction"]["regulated_product_type"] = "infant_food"
        high_risk_unresolved["eligibility_gate"].update(
            {
                "status": "unresolved",
                "target_user_or_object": "婴幼儿",
                "life_stage_or_state": "月龄未知",
                "unresolved_questions": ["当前适用月龄未锁定"],
            }
        )
        write_json(chain_path, high_risk_unresolved)
        assert_error(course, "E_ELIGIBILITY")

        percent_without_basis = deepcopy(original_chain)
        percent_without_basis["quantified_claim_checks"] = [
            {
                "claim_text": "93%用户反馈更喜欢",
                "claim_type": "user_feedback",
                "support_target": "用户偏好",
                "target_user_or_object": "当前测试人群",
                "variant_id_or_current_product": "current_product",
                "time_window_or_unknown": "unknown",
                "metric": "偏好比例",
                "baseline_or_denominator_or_unknown": "unknown",
                "source_readability": "readable",
                "page_support_status": "partially_supported",
                "boundary": "只记录页面主张。",
            }
        ]
        percent_without_basis["chain_findings"] = [
            {
                "finding_type": "quantified_claim_basis_missing",
                "component_ids": ["COMP-002"],
                "decision_names": ["相信"],
                "observation": "页面写93%，但没有展示分母或统计口径。",
                "problem": "用户无法判断数字适用于谁、如何计算。",
                "boundary": "只判断页面支持完整性，不判断研究本身有效性。",
                "action_or_need": "补充分母、样本与统计口径，或降级表述。",
            }
        ]
        write_json(chain_path, percent_without_basis)
        assert validate_delivery(course)["status"] == "passed"

        forged_supported_claim = deepcopy(percent_without_basis)
        forged_supported_claim["quantified_claim_checks"][0]["page_support_status"] = "supported_on_page"
        write_json(chain_path, forged_supported_claim)
        assert_error(course, "E_QUANTIFIED_CLAIM")

        unknown_variant_option = deepcopy(original_chain)
        unknown_variant_option["current_transaction"]["current_variant_id"] = "VAR-001"
        unknown_variant_option["variant_routes"] = [
            {
                "variant_id": "VAR-001",
                "variant_type": "flavor",
                "option_type": "service_entry",
                "label": "加入会员",
                "sku_ids_or_unknown": [],
                "applicability": "unknown",
                "fact_ids": [],
                "value_ids": [],
                "evidence_component_ids": [],
                "usage_component_ids": [],
                "current_variant": True,
                "boundary": "会员服务不是可成交SKU。",
            }
        ]
        write_json(chain_path, unknown_variant_option)
        assert_error(course, "E_VARIANT_ROUTE")

        bad_upgrade = deepcopy(original_chain)
        bad_upgrade["current_transaction"]["upgrade_comparison_status"] = "insufficient"
        bad_upgrade["chain_findings"] = []
        write_json(chain_path, bad_upgrade)
        assert_error(course, "E_UPGRADE_COMPARISON")

        hidden_cross_sku_conflict = deepcopy(original_chain)
        hidden_cross_sku_conflict["cross_surface_sku_consistency"]["surface_checks"][1]["relationship"] = "inconsistent"
        hidden_cross_sku_conflict["cross_surface_sku_consistency"]["inconsistencies"] = [
            "详情页展示的是另一规格。"
        ]
        hidden_cross_sku_conflict["cross_surface_consistency"]["inconsistencies"] = []
        write_json(chain_path, hidden_cross_sku_conflict)
        assert_error(course, "E_CROSS_SURFACE_SKU")

        recorded_cross_sku_conflict = deepcopy(hidden_cross_sku_conflict)
        recorded_cross_sku_conflict["cross_surface_consistency"]["status"] = "fully_checked"
        recorded_cross_sku_conflict["cross_surface_consistency"]["inconsistencies"] = [
            "主图与详情页展示规格不一致。"
        ]
        recorded_cross_sku_conflict["chain_findings"] = [
            {
                "finding_type": "cross_surface_sku_mismatch",
                "component_ids": ["COMP-001", "COMP-002"],
                "decision_names": ["认对", "选对"],
                "observation": "主图和详情页展示了不同规格。",
                "problem": "用户无法确认当前成交SKU。",
                "boundary": "只判断页面信息一致性，不判断库存或履约事实。",
                "action_or_need": "统一当前SKU，并把其他规格明确标为可选变体。",
            }
        ]
        write_json(chain_path, recorded_cross_sku_conflict)
        assert_error(course, "E_CROSS_SURFACE_SKU")

        manifest_for_conflict = course / "data" / "page_manifest.json"
        conflict_manifest = read_json(manifest_for_conflict)
        conflict_manifest["run_status"] = "partial"
        write_json(manifest_for_conflict, conflict_manifest)
        assert validate_delivery(course)["status"] == "passed"
        conflict_manifest["run_status"] = "ready"
        write_json(manifest_for_conflict, conflict_manifest)

        promised_chain = deepcopy(original_chain)
        promised_chain["decision_closure"]["closure_reason"] = "这样组织一定提升转化率。"
        write_json(chain_path, promised_chain)
        assert_error(course, "E_EFFECT_PROMISE")

        comment_as_chain_fact = deepcopy(original_chain)
        comment_as_chain_fact["dominant_route"] = "评论证明这个规格最受欢迎，所以直接主推。"
        write_json(chain_path, comment_as_chain_fact)
        assert_error(course, "E_COMMENT_AS_PRODUCT_FACT")

        write_json(chain_path, original_chain)

        bad_priority = deepcopy(original_actions)
        bad_priority[0]["priority"] = "1"
        write_jsonl(actions_path, bad_priority)
        assert build_delivery(course, write=False)["status"] == "dry_run"
        assert_error(course, "E_ACTION_FIELDS_MISSING")

        blocked_action = deepcopy(original_actions)
        blocked_action[0]["status"] = "blocked"
        write_jsonl(actions_path, blocked_action)
        assert_error(course, "E_BLOCKED_ACTION")

        wrong_decision = deepcopy(original_actions)
        wrong_decision[0]["decision_name"] = "相信"
        write_jsonl(actions_path, wrong_decision)
        assert_error(course, "E_ACTION_UNGROUNDED")

        bad_ref = deepcopy(original_actions)
        bad_ref[0]["source_file_ids"] = ["PAGE-SF-999"]
        write_jsonl(actions_path, bad_ref)
        assert_error(course, "E_PAGE_REF_INVALID")

        write_jsonl(actions_path, original_actions)
        decisions_path = course / "data" / "decision_ledger.jsonl"
        original_decisions = read_jsonl(decisions_path)
        ungrounded_decisions = deepcopy(original_decisions)
        for row in ungrounded_decisions:
            row["status"] = "已讲清"
            row["source_file_ids"] = []
            row["component_ids"] = []
            row["fact_ids"] = []
            row["value_ids"] = []
            row["vis_ids"] = []
            row["unknowns"] = []
        write_jsonl(decisions_path, ungrounded_decisions)
        assert_error(course, "E_DECISION_UNGROUNDED")
        write_jsonl(decisions_path, original_decisions)

        components_path = course / "data" / "page_component_ledger.jsonl"
        original_components = read_jsonl(components_path)
        promised_component = deepcopy(original_components)
        promised_component[0]["execution_instruction"] = "这样改一定提升转化率。"
        write_jsonl(components_path, promised_component)
        assert_error(course, "E_EFFECT_PROMISE")

        campaign_as_static = deepcopy(original_components)
        campaign_as_static[0]["content_layer"] = "current_campaign"
        campaign_as_static[0]["dynamic_status"] = "not_dynamic"
        write_jsonl(components_path, campaign_as_static)
        assert_error(course, "E_DYNAMIC_TIME_SCOPE")

        unsupported_evidence = deepcopy(original_components)
        unsupported_evidence[0]["module_role"] = "evidence"
        unsupported_evidence[0]["support_target"] = "not_applicable"
        write_jsonl(components_path, unsupported_evidence)
        assert_error(course, "E_SUPPORT_TARGET_MISSING")

        other_sku = deepcopy(original_components)
        other_sku[0]["component_applicability"] = "related_product"
        write_jsonl(components_path, other_sku)
        write_jsonl(actions_path, original_actions)
        assert_error(course, "E_SKU_APPLICABILITY")
        write_jsonl(components_path, original_components)

        coverage_path = course / "data" / "page_coverage.jsonl"
        original_coverage = read_jsonl(coverage_path)
        false_count = deepcopy(original_coverage)
        false_count[0]["observed_source_count"] += 1
        write_jsonl(coverage_path, false_count)
        assert_error(course, "E_COVERAGE_COUNT")
        write_jsonl(coverage_path, original_coverage)

        sources_path = course / "data" / "source_inventory.jsonl"
        original_sources = read_jsonl(sources_path)
        unreadable = deepcopy(original_sources)
        unreadable[1]["readability_status"] = "unreadable"
        write_jsonl(sources_path, unreadable)
        assert_error(course, "E_UNKNOWN_DROPPED")
        write_jsonl(sources_path, original_sources)

        fake_archive = deepcopy(original_sources)
        fake_archive[0]["media_type"] = "archive"
        fake_archive[0]["extension"] = ".zip"
        fake_archive[0]["readability_status"] = "readable"
        write_jsonl(sources_path, fake_archive)
        assert_error(course, "E_PAGE_REF_INVALID")
        write_jsonl(sources_path, original_sources)

        duplicate_sequence = deepcopy(original_sources)
        duplicate_sequence[1]["page_scope"] = "main_images"
        duplicate_sequence[1]["sequence"] = 1
        write_jsonl(sources_path, duplicate_sequence)
        assert_error(course, "E_SEQUENCE_CONFLICT")
        write_jsonl(sources_path, original_sources)

        swapped_scopes = deepcopy(original_sources)
        swapped_scopes[0]["page_scope"] = "detail_page"
        swapped_scopes[1]["page_scope"] = "main_images"
        write_jsonl(sources_path, swapped_scopes)
        assert_error(course, "E_SCOPE_REFERENCE")
        write_jsonl(sources_path, original_sources)

        degraded_actions_path = degraded / "data" / "action_ledger.jsonl"
        original_degraded = read_jsonl(degraded_actions_path)
        overreached = deepcopy(original_degraded)
        overreached[0]["basis_type"] = "product_value"
        overreached[0]["value_ids"] = ["V-001"]
        write_jsonl(degraded_actions_path, overreached)
        assert_error(degraded, "E_P0_CREATED")
        write_jsonl(degraded_actions_path, original_degraded)

        manifest_path = course / "data" / "page_manifest.json"
        original_manifest = read_json(manifest_path)
        drift = deepcopy(original_manifest)
        drift["skill_version"] = "9.9.9"
        write_json(manifest_path, drift)
        assert_error(course, "E_VERSION_DRIFT")
        write_json(manifest_path, original_manifest)

        mixed_identity = deepcopy(original_manifest)
        mixed_identity["brand"] = "另一个品牌"
        mixed_identity["product"] = "另一个商品"
        write_json(manifest_path, mixed_identity)
        assert_error(course, "E_IDENTITY_MIXED")
        write_json(manifest_path, original_manifest)

        bad_page_id = deepcopy(original_manifest)
        bad_page_id["product_page_id"] = "PP-ffffffffffff"
        write_json(manifest_path, bad_page_id)
        assert_error(course, "E_IDENTITY_MIXED")
        write_json(manifest_path, original_manifest)

        bad_state_pair = deepcopy(original_manifest)
        bad_state_pair["analysis_status"] = "complete"
        bad_state_pair["delivery_status"] = "blocked"
        write_json(manifest_path, bad_state_pair)
        assert_error(course, "E_STATUS_PAIR")
        write_json(manifest_path, original_manifest)

        stale_state = deepcopy(original_manifest)
        stale_state["analysis_status"] = "stale"
        stale_state["delivery_status"] = "stale"
        write_json(manifest_path, stale_state)
        assert_error(course, "E_STALE_DELIVERY")
        write_json(manifest_path, original_manifest)

        upstream_path = course / "data" / "upstream_snapshot.json"
        original_upstream = read_json(upstream_path)
        forged_upstream = deepcopy(original_upstream)
        forged_upstream["product_value"]["usable"] = False
        write_json(upstream_path, forged_upstream)
        assert_error(course, "E_UPSTREAM_STATUS_FORGED")
        write_json(upstream_path, original_upstream)

        illegal_p0 = deepcopy(original_upstream)
        illegal_p0["product_value"]["p0_status"] = "P0-LOCKED"
        write_json(upstream_path, illegal_p0)
        assert_error(course, "E_UPSTREAM_STATUS_FORGED")
        write_json(upstream_path, original_upstream)

        blocked_value = deepcopy(original_upstream)
        for value in blocked_value["product_value"]["values"]:
            if value["value_id"] == blocked_value["product_value"]["recommended_value_id"]:
                value["downstream_readiness"] = "blocked"
        write_json(upstream_path, blocked_value)
        assert_error(course, "E_UPSTREAM_STATUS_FORGED")
        write_json(upstream_path, original_upstream)

        non_page_vis = deepcopy(original_upstream)
        non_page_vis["value_expression"]["vis"][0]["applicable_objects"] = ["直播间"]
        write_json(upstream_path, non_page_vis)
        assert_error(course, "E_UPSTREAM_SCHEMA")
        write_json(upstream_path, original_upstream)

        build_delivery(course, write=True)
        course_report_path = course / "01_商品页诊断与优化建议.md"
        clean_report = course_report_path.read_text(encoding="utf-8")
        course_report_path.write_text(clean_report + "\n调用V-001价值。\n", encoding="utf-8")
        assert_error(course, "E_COURSE_INTERNAL_LEAK")
        for leaked_id in ("调用DEC-01判断。", "internal: DEC-05"):
            course_report_path.write_text(clean_report + f"\n{leaked_id}\n", encoding="utf-8")
            assert_error(course, "E_COURSE_INTERNAL_LEAK")
        course_report_path.write_text(clean_report + "\n来源：D:/客户资料/页面.png\n", encoding="utf-8")
        assert_error(course, "E_ABSOLUTE_PATH_LEAK")
        for leaked_path in (
            "/tmp/client/page.png",
            "/var/data/client/page.png",
            "source:/tmp/client/page.png",
            "//server/share/client/page.png",
            "\\\\server\\share\\client\\page.png",
        ):
            course_report_path.write_text(
                clean_report + f"\nsource: {leaked_path}\n",
                encoding="utf-8",
            )
            assert_error(course, "E_ABSOLUTE_PATH_LEAK")
        course_report_path.write_text(
            clean_report + "\n公开链接：https://example.com/path/to/page\n",
            encoding="utf-8",
        )
        assert validate_delivery(course)["status"] == "passed"
        build_delivery(course, write=True)

        failed_out = temp_root / "transaction-failed"
        with patch("init_product_page_delivery.index_sources", side_effect=RuntimeError("synthetic failure")):
            try:
                init_delivery(
                    failed_out, sources, product_value, value_expression,
                    "", "", "", "", "combined", "diagnose", "course",
                    "2026-08-11T10:00:00+08:00", "", None,
                )
                raise AssertionError("合成初始化故障必须向上抛出")
            except RuntimeError as exc:
                assert "synthetic failure" in str(exc)
        assert not failed_out.exists(), "失败初始化不得残留半成品目录"

        preexisting_empty = temp_root / "transaction-preexisting-empty"
        preexisting_empty.mkdir()
        with patch("init_product_page_delivery.index_sources", side_effect=RuntimeError("synthetic failure")):
            try:
                init_delivery(
                    preexisting_empty, sources, product_value, value_expression,
                    "", "", "", "", "combined", "diagnose", "course",
                    "2026-08-11T10:00:00+08:00", "", None,
                )
                raise AssertionError("合成初始化故障必须向上抛出")
            except RuntimeError:
                pass
        assert preexisting_empty.is_dir() and not any(preexisting_empty.iterdir())

        unsafe_out = sources / "delivery-inside-source"
        try:
            init_delivery(
                unsafe_out, sources, product_value, value_expression,
                "", "", "", "", "combined", "diagnose", "course",
                "2026-08-11T10:00:00+08:00", "", None,
            )
            raise AssertionError("页面资料目录内部的输出位置必须被拒绝")
        except ValueError as exc:
            assert "输出目录不能位于页面资料目录内部" in str(exc)
        assert not unsafe_out.exists(), "位置预检必须在创建输出目录之前发生"

        build_delivery(course, write=True)
        assert validate_delivery(course)["status"] == "passed"
        assert SKILL_VERSION == "0.4.0"
        print("product-page synthetic tests passed")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
        try:
            test_parent.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    run_test()
