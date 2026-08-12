"""Offline synthetic tests for BrandBAI Product Value."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from build_product_value_report import build_delivery, public_text
from build_source_audit_cards import build_cards
from index_product_sources import index_sources
from init_product_value_delivery import build_plan, init_delivery
from product_value_common import now_iso, read_json, read_jsonl, write_json, write_jsonl
from validate_product_value_delivery import (
    suspicious_dense_cadence,
    suspicious_fixed_cadence,
    suspicious_repeating_cadence,
    validate_delivery,
)


def populate_valid_partial(delivery: Path) -> None:
    data = delivery / "data"
    clock_now = datetime.now().astimezone().replace(microsecond=0)
    created_at = (clock_now - timedelta(minutes=30)).isoformat()
    timestamp = (clock_now - timedelta(minutes=20)).isoformat()
    event_start = (clock_now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
    event_end = (clock_now + timedelta(days=1)).replace(hour=23, minute=59, second=59)
    dynamic_claim_text = f"活动时间{event_start.isoformat()}至{event_end.isoformat()}"
    dynamic_time_scope = f"{event_start.isoformat()}/{event_end.isoformat()}"
    source_dir = delivery.parent / f"{delivery.name}-source-materials"
    source_dir.mkdir()
    (source_dir / "商品包装.txt").write_text("独立小袋包装", encoding="utf-8")
    (source_dir / "品牌方向.txt").write_text("外出携带", encoding="utf-8")
    (source_dir / "活动信息.txt").write_text(dynamic_claim_text, encoding="utf-8")
    (source_dir / "原始资料包.zip").write_bytes(b"synthetic archive container")
    (source_dir / "详情页主图.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" fill="white"/><text x="30" y="80">独立小袋包装</text><text x="30" y="130">外出拿取更清楚</text></svg>',
        encoding="utf-8",
    )
    (source_dir / "详情页工艺图.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="4000"><rect width="400" height="4000" fill="white"/><text x="30" y="80">虚构工艺说明</text><text x="30" y="3950">仅作图片审计测试</text></svg>',
        encoding="utf-8",
    )
    dry_run = index_sources(source_dir, delivery, write=False)
    assert dry_run["status"] == "dry_run"
    assert read_jsonl(data / "source_inventory.jsonl") == []
    assert read_jsonl(data / "source_observation.jsonl") == []
    assert read_jsonl(data / "source_claim_ledger.jsonl") == []
    indexed = index_sources(source_dir, delivery, write=True)
    assert indexed["file_count"] == 6
    card_dry_run = build_cards(source_dir, delivery, write=False)
    assert card_dry_run["status"] == "dry_run"
    assert card_dry_run["audit_cards"] == 2
    cards = build_cards(source_dir, delivery, write=True)
    assert cards["audit_cards"] == 2
    inventory_ids = {
        item["filename"]: item["source_file_id"]
        for item in read_jsonl(data / "source_inventory.jsonl")
    }
    audit_cards = {
        item["source_file_id"]: item
        for item in read_jsonl(data / "source_audit_card_ledger.jsonl")
    }
    long_card_path = data / audit_cards[inventory_ids["详情页工艺图.svg"]]["audit_card_path"]
    assert 'height="13460" viewBox="0 0 1400 13460"' in long_card_path.read_text(encoding="utf-8")
    first_pass_at = clock_now - timedelta(minutes=10)
    second_image_first_pass_at = first_pass_at + timedelta(seconds=2)
    second_pass_at = first_pass_at + timedelta(seconds=7)
    first_image_second_pass_at = first_pass_at + timedelta(seconds=11)
    claim_pass_times = [first_pass_at + timedelta(seconds=value) for value in (19, 23, 28, 34, 41)]
    claim_recheck_times = [first_pass_at + timedelta(seconds=value) for value in (52, 59, 67, 76, 86)]
    write_jsonl(
        data / "source_observation.jsonl",
        [
            {
                "observation_id": "OBS-001",
                "source_file_id": inventory_ids["商品包装.txt"],
                "relative_path": "商品包装.txt",
                "content_type": "packaging",
                "title": "虚构商品包装信息",
                "visible_heading": "独立小袋包装",
                "visible_text_excerpt": "独立小袋包装",
                "inspection_method": "document_text",
                "inspection_status": "inspected",
                "inspected_at": timestamp,
                "audit_card_sha256": "",
                "first_pass_sequence": 0,
                "second_pass_sequence": 0,
                "second_pass_heading": "",
                "second_pass_excerpt": "",
                "second_pass_status": "not_applicable",
                "second_pass_at": "",
                "text_density": "low",
                "content_flags": ["packaging"],
            },
            {
                "observation_id": "OBS-002",
                "source_file_id": inventory_ids["品牌方向.txt"],
                "relative_path": "品牌方向.txt",
                "content_type": "brand_brief",
                "title": "虚构品牌方向说明",
                "visible_heading": "外出携带",
                "visible_text_excerpt": "外出携带",
                "inspection_method": "document_text",
                "inspection_status": "inspected",
                "inspected_at": timestamp,
                "audit_card_sha256": "",
                "first_pass_sequence": 0,
                "second_pass_sequence": 0,
                "second_pass_heading": "",
                "second_pass_excerpt": "",
                "second_pass_status": "not_applicable",
                "second_pass_at": "",
                "text_density": "low",
                "content_flags": ["audience"],
            },
            {
                "observation_id": "OBS-003",
                "source_file_id": inventory_ids["活动信息.txt"],
                "relative_path": "活动信息.txt",
                "content_type": "promotion",
                "title": "虚构限时活动信息",
                "visible_heading": dynamic_claim_text,
                "visible_text_excerpt": dynamic_claim_text,
                "inspection_method": "document_text",
                "inspection_status": "inspected",
                "inspected_at": timestamp,
                "audit_card_sha256": "",
                "first_pass_sequence": 0,
                "second_pass_sequence": 0,
                "second_pass_heading": "",
                "second_pass_excerpt": "",
                "second_pass_status": "not_applicable",
                "second_pass_at": "",
                "text_density": "low",
                "content_flags": ["transaction"],
            },
            {
                "observation_id": "OBS-004",
                "source_file_id": inventory_ids["详情页主图.svg"],
                "relative_path": "详情页主图.svg",
                "content_type": "product_page_image",
                "title": "虚构详情页主图",
                "visible_heading": "独立小袋包装",
                "visible_text_excerpt": "外出拿取更清楚",
                "inspection_method": "visual_stamped_card",
                "inspection_status": "inspected",
                "inspected_at": first_pass_at.isoformat(),
                "audit_card_sha256": audit_cards[inventory_ids["详情页主图.svg"]]["audit_card_sha256"],
                "first_pass_sequence": 1,
                "second_pass_sequence": 2,
                "second_pass_heading": "独立小袋包装",
                "second_pass_excerpt": "外出拿取更清楚",
                "second_pass_status": "match",
                "second_pass_at": first_image_second_pass_at.isoformat(),
                "text_density": "medium",
                "content_flags": ["packaging"],
            },
            {
                "observation_id": "OBS-005",
                "source_file_id": inventory_ids["详情页工艺图.svg"],
                "relative_path": "详情页工艺图.svg",
                "content_type": "product_page_image",
                "title": "虚构详情页工艺图",
                "visible_heading": "虚构工艺说明",
                "visible_text_excerpt": "仅作图片审计测试",
                "inspection_method": "visual_stamped_card",
                "inspection_status": "inspected",
                "inspected_at": second_image_first_pass_at.isoformat(),
                "audit_card_sha256": audit_cards[inventory_ids["详情页工艺图.svg"]]["audit_card_sha256"],
                "first_pass_sequence": 2,
                "second_pass_sequence": 1,
                "second_pass_heading": "虚构工艺说明",
                "second_pass_excerpt": "仅作图片审计测试",
                "second_pass_status": "match",
                "second_pass_at": second_pass_at.isoformat(),
                "text_density": "low",
                "content_flags": ["process"],
            },
            {
                "observation_id": "OBS-006",
                "source_file_id": inventory_ids["原始资料包.zip"],
                "relative_path": "原始资料包.zip",
                "content_type": "archive_container",
                "title": "原始资料包归档文件",
                "visible_heading": "",
                "visible_text_excerpt": "",
                "inspection_method": "unsupported_archive",
                "inspection_status": "unreadable",
                "inspected_at": timestamp,
                "audit_card_sha256": "",
                "first_pass_sequence": 0,
                "second_pass_sequence": 0,
                "second_pass_heading": "",
                "second_pass_excerpt": "",
                "second_pass_status": "not_applicable",
                "second_pass_at": "",
                "text_density": "none",
                "content_flags": [],
            },
        ],
    )
    write_jsonl(
        data / "source_claim_ledger.jsonl",
        [
            {
                "claim_id": "CLM-001",
                "source_file_id": inventory_ids["商品包装.txt"],
                "observation_id": "OBS-001",
                "claim_type": "packaging",
                "label": "包装形式",
                "verbatim_text": "独立小袋包装",
                "normalized_value": "",
                "unit": "",
                "visual_locator": "文本第1行",
                "critical": False,
                "claim_status": "match",
                "claimed_at": claim_pass_times[0].isoformat(),
                "rechecked_at": claim_recheck_times[0].isoformat(),
            },
            {
                "claim_id": "CLM-002",
                "source_file_id": inventory_ids["品牌方向.txt"],
                "observation_id": "OBS-002",
                "claim_type": "audience",
                "label": "品牌方向",
                "verbatim_text": "外出携带",
                "normalized_value": "",
                "unit": "",
                "visual_locator": "文本第1行",
                "critical": False,
                "claim_status": "match",
                "claimed_at": claim_pass_times[1].isoformat(),
                "rechecked_at": claim_recheck_times[1].isoformat(),
            },
            {
                "claim_id": "CLM-003",
                "source_file_id": inventory_ids["活动信息.txt"],
                "observation_id": "OBS-003",
                "claim_type": "transaction",
                "label": "活动信息",
                "verbatim_text": dynamic_claim_text,
                "normalized_value": "",
                "unit": "",
                "visual_locator": "文本第1行",
                "critical": False,
                "claim_status": "match",
                "claimed_at": claim_pass_times[2].isoformat(),
                "rechecked_at": claim_recheck_times[2].isoformat(),
            },
            {
                "claim_id": "CLM-004",
                "source_file_id": inventory_ids["详情页主图.svg"],
                "observation_id": "OBS-004",
                "claim_type": "packaging",
                "label": "主图包装文案",
                "verbatim_text": "独立小袋包装",
                "normalized_value": "",
                "unit": "",
                "visual_locator": "主图上部",
                "critical": False,
                "claim_status": "match",
                "claimed_at": claim_pass_times[3].isoformat(),
                "rechecked_at": claim_recheck_times[3].isoformat(),
            },
            {
                "claim_id": "CLM-005",
                "source_file_id": inventory_ids["详情页工艺图.svg"],
                "observation_id": "OBS-005",
                "claim_type": "process",
                "label": "工艺测试文案",
                "verbatim_text": "虚构工艺说明",
                "normalized_value": "",
                "unit": "",
                "visual_locator": "长图上部",
                "critical": False,
                "claim_status": "match",
                "claimed_at": claim_pass_times[4].isoformat(),
                "rechecked_at": claim_recheck_times[4].isoformat(),
            },
        ],
    )
    try:
        index_sources(source_dir, delivery, write=True)
    except FileExistsError:
        pass
    else:
        raise AssertionError("来源索引不得覆盖已有非空清单")
    manifest = read_json(data / "product_manifest.json")
    manifest.update(
        {
            "sku_status": "confirmed",
            "sku_basis": "包装背面规格栏明确标示示例规格A",
            "fc": "FC2",
            "sc": "SC1",
            "pkg_level": "PKG-L2",
            "analysis_status": "partial",
            "delivery_status": "conditional",
            "limitations": ["尚未获得独立检测资料，当前仅按包装信息建立价值假设（GAP-001）。"],
            "created_at": created_at,
            "updated_at": clock_now.isoformat(),
        }
    )
    write_json(data / "product_manifest.json", manifest)
    write_jsonl(
        data / "source_ledger.jsonl",
        [
            {
                "source_id": "SRC-001",
                "source_file_id": inventory_ids["商品包装.txt"],
                "observation_id": "OBS-001",
                "source_type": "product_page_image",
                "title": "虚构商品包装信息",
                "locator": "商品包装.txt｜包装正面与背面",
                "captured_at": timestamp,
                "sku_scope": "示例规格A",
                "status": "active",
                "notes": "仅用于离线测试的纯虚构资料",
            },
            {
                "source_id": "SRC-002",
                "source_file_id": inventory_ids["品牌方向.txt"],
                "observation_id": "OBS-002",
                "source_type": "brief",
                "title": "虚构品牌方向说明",
                "locator": "品牌方向.txt｜第1段",
                "captured_at": timestamp,
                "sku_scope": "示例规格A",
                "status": "active",
                "notes": "仅用于离线测试的纯虚构资料",
            },
            {
                "source_id": "SRC-003",
                "source_file_id": inventory_ids["活动信息.txt"],
                "observation_id": "OBS-003",
                "source_type": "promotion_banner",
                "title": "虚构限时活动信息",
                "locator": "活动信息.txt｜活动图片",
                "captured_at": timestamp,
                "sku_scope": "示例规格A",
                "status": "active",
                "notes": "仅用于动态日期一致性测试",
            },
            {
                "source_id": "SRC-004",
                "source_file_id": inventory_ids["详情页主图.svg"],
                "observation_id": "OBS-004",
                "source_type": "product_page_image",
                "title": "虚构详情页主图",
                "locator": "详情页主图.svg｜带身份审计卡",
                "captured_at": timestamp,
                "sku_scope": "示例规格A",
                "status": "active",
                "notes": "仅用于离线图片审计测试",
            },
            {
                "source_id": "SRC-005",
                "source_file_id": inventory_ids["详情页工艺图.svg"],
                "observation_id": "OBS-005",
                "source_type": "product_page_image",
                "title": "虚构详情页工艺图",
                "locator": "详情页工艺图.svg｜带身份审计卡",
                "captured_at": timestamp,
                "sku_scope": "示例规格A",
                "status": "active",
                "notes": "仅用于离线图片审计测试",
            },
        ],
    )
    write_jsonl(
        data / "fact_ledger.jsonl",
        [
            {
                "fact_id": "F-001",
                "fact_type": "F-PAGE",
                "statement": "包装标示采用独立小袋分装。",
                "source_id": "SRC-001",
                "claim_ids": ["CLM-001"],
                "source_quotes": ["独立小袋包装"],
                "locator": "包装背面",
                "sku_scope": "示例规格A",
                "time_scope": "当前包装版本",
                "status": "confirmed",
                "boundary": "仅证明包装结构，不证明保鲜效果优于其他商品。",
            },
            {
                "fact_id": "STRAT-001",
                "fact_type": "STRAT",
                "statement": "品牌希望优先服务需要外出携带的用户。",
                "source_id": "SRC-002",
                "claim_ids": ["CLM-002"],
                "source_quotes": ["外出携带"],
                "locator": "第1段",
                "sku_scope": "示例规格A",
                "time_scope": "本次任务",
                "status": "confirmed",
                "boundary": "这是品牌方向，不代表用户已经认可。",
            },
            {
                "fact_id": "H-001",
                "fact_type": "H",
                "statement": "独立小袋可能降低外出分装步骤。",
                "source_id": "SRC-001",
                "claim_ids": [],
                "source_quotes": [],
                "locator": "基于 F-001 的分析推导",
                "sku_scope": "示例规格A",
                "time_scope": "当前包装版本",
                "status": "conditional",
                "boundary": "需通过用户使用验证，不能写成普遍体验结论。",
            },
            {
                "fact_id": "DYN-001",
                "fact_type": "DYN",
                "statement": "虚构活动在本次交付日期内有效。",
                "source_id": "SRC-003",
                "claim_ids": ["CLM-003"],
                "source_quotes": [dynamic_claim_text],
                "locator": "活动图片",
                "sku_scope": "示例规格A",
                "time_scope": dynamic_time_scope,
                "status": "active",
                "boundary": "仅在完整日期区间内有效。",
            },
        ],
    )
    write_jsonl(
        data / "anchor_ledger.jsonl",
        [
            {
                "anchor_id": "ANCHOR-001",
                "anchor_type": "main",
                "statement": "独立小袋包装",
                "fact_ids": ["F-001"],
                "status": "active",
                "boundary": "参见F-001；识别锚不自动等于购买理由。",
            }
        ],
    )
    write_jsonl(
        data / "fabe_ledger.jsonl",
        [
            {
                "fabe_id": "FABE-001",
                "value_id": "V-001",
                "feature": "当前SKU采用独立小袋包装。",
                "feature_fact_ids": ["F-001"],
                "advantage": "独立小袋把商品预先分成可直接拿取的包装单元。",
                "benefit": "外出前可以少做一步分装准备。",
                "evidence": "包装正背面可直接核对独立小袋结构（SRC-001/F-001）。",
                "evidence_fact_ids": ["F-001"],
                "reference_frame": "当前包装结构与临时分装任务的内生推导",
                "user_language": ">口感之外，出门直接拿一袋，不用再找盒子分装。",
                "derivation_status": "reasoned",
                "boundary": "便利性需要用户验证，不写成所有人都更方便。",
            },
            {
                "fabe_id": "FABE-002",
                "value_id": "V-002",
                "feature": "当前SKU采用独立小袋包装。",
                "feature_fact_ids": ["F-001"],
                "advantage": "包装已经把整件商品分成更清楚的使用单元。",
                "benefit": "用户按袋拿取时更容易理解一次拿什么。",
                "evidence": "当前包装页面可见独立小袋。",
                "evidence_fact_ids": ["F-001"],
                "reference_frame": "散装或整包取用",
                "user_language": "一袋一袋拿，使用单位很清楚。",
                "derivation_status": "page_supported",
                "boundary": "不能证明独立包装能减少实际使用量。",
            },
            {
                "fabe_id": "FABE-003",
                "value_id": "V-003",
                "feature": "当前包装可核对商品形态和规格。",
                "feature_fact_ids": ["F-001"],
                "advantage": "购买前多一个可见的SKU核对入口。",
                "benefit": "用户更容易确认自己选的是当前规格。",
                "evidence": "包装正背面的商品信息。",
                "evidence_fact_ids": ["F-001"],
                "reference_frame": "仅凭商品名称选择",
                "user_language": "先看包装信息，确认是不是我要的规格。",
                "derivation_status": "page_supported",
                "boundary": "包装信息不能替代第三方检测。",
            },
        ],
    )
    write_jsonl(
        data / "value_ledger.jsonl",
        [
            {
                "value_id": "V-001",
                "layer": "P0",
                "p0_candidate": True,
                "p0_status": "P0-HYPOTHESIS",
                "user_task": "外出时减少临时分装步骤",
                "value_statement": "让外出携带更省一步准备。",
                "supporting_fact_ids": ["F-001", "STRAT-001", "H-001"],
                "strategic_potential": "medium",
                "execution_maturity": "low",
                "user_perception_goal": "用户能理解拿取和携带的便利性",
                "sku_scope": "示例规格A",
                "scope": "有外出携带需求的场景；参照临时自行分装",
                "cannot_prove": ["不能证明所有用户都更方便", "不能证明优于所有同类包装"],
                "downstream_readiness": "conditional",
            },
            {
                "value_id": "V-002",
                "layer": "P1",
                "p0_candidate": True,
                "p0_status": "P0-CANDIDATE",
                "user_task": "按次拿取",
                "value_statement": "按小袋拿取，使用单元更清楚。",
                "supporting_fact_ids": ["F-001"],
                "strategic_potential": "low",
                "execution_maturity": "medium",
                "user_perception_goal": "用户看懂包装的使用方式",
                "sku_scope": "示例规格A",
                "scope": "仅限当前独立小袋 SKU",
                "cannot_prove": ["不能证明能减少实际用量"],
                "downstream_readiness": "ready",
            },
            {
                "value_id": "V-003",
                "layer": "P2",
                "p0_candidate": False,
                "p0_status": "not_applicable",
                "user_task": "确认商品形态",
                "value_statement": "包装信息可用于核对当前购买规格。",
                "supporting_fact_ids": ["F-001"],
                "strategic_potential": "low",
                "execution_maturity": "medium",
                "user_perception_goal": "用户能核对当前规格",
                "sku_scope": "示例规格A",
                "scope": "当前包装版本",
                "cannot_prove": ["不能替代第三方检测"],
                "downstream_readiness": "ready",
            },
        ],
    )
    write_json(
        data / "p0_decision.json",
        {
            "decision_id": "P0D-001",
            "candidate_value_ids": ["V-001", "V-002"],
            "recommended_value_id": "V-001",
            "status": "P0-HYPOTHESIS",
            "rationale": "V-001的外出准备任务与品牌方向一致；相比V-002仍缺少用户和竞争验证。",
            "public_rationale": "外出前少一步分装与品牌当前方向一致，但仍需真实用户和同类商品对照验证。",
            "current_execution_axis": "当前执行主轴调用：让外出携带更省一步准备。",
            "current_execution_value_ids": ["V-001"],
            "cannot_prove": ["不能写成消费者已经认可的核心心智。"],
            "validation_questions": ["目标用户是否真实存在临时分装负担？", "同类商品是否普遍采用相同结构？"],
            "decided_at": timestamp,
            "valid_until": "补充用户或竞争资料前",
            "supersedes": "",
        },
    )
    write_jsonl(
        data / "gap_ledger.jsonl",
        [
            {
                "gap_id": "GAP-001",
                "category": "用户与竞争",
                "missing": "真实用户外出分装反馈和同类包装对照",
                "impact": "P0 只能保持为优先验证假设",
                "minimum_needed": "目标用户访谈或评论样本，以及主要替代商品包装信息",
                "priority": "P0",
                "state": "open",
            }
        ],
    )


def test_partial_delivery(root: Path) -> None:
    delivery = root / "partial"
    plan = build_plan(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    assert plan["dry_run"] is True
    assert "data/source_inventory.jsonl" in plan["will_create"]
    assert "data/source_audit_card_ledger.jsonl" in plan["will_create"]
    assert "data/source_audit_cards/" in plan["will_create"]
    assert "data/source_observation.jsonl" in plan["will_create"]
    assert "data/source_claim_ledger.jsonl" in plan["will_create"]
    assert "data/fabe_ledger.jsonl" in plan["will_create"]
    assert not delivery.exists(), "Dry Run 计划不应创建目录"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    try:
        init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    except FileExistsError:
        pass
    else:
        raise AssertionError("初始化脚本必须拒绝覆盖非空目录")
    populate_valid_partial(delivery)
    dry_run = build_delivery(delivery, write=False)
    assert dry_run["status"] == "dry_run"
    build_delivery(delivery, write=True)
    result = validate_delivery(delivery)
    assert result["status"] == "passed", result
    report = (delivery / "01_商品价值底座.md").read_text(encoding="utf-8")
    assert "FABE价值证据链" in report
    assert "V-001" not in report
    assert "PV-" not in report
    assert "SRC-001" not in report
    assert "V-001的" not in report
    assert "见F-001" not in report
    assert "的外出准备任务" not in report
    assert "参见；" not in report
    assert "仍需真实用户和同类商品对照验证" in report
    assert "当前资料不能证明" in report
    assert "| >口感" not in report
    assert "(,)" not in report
    assert "(/)" not in report
    assert "暂无高优先级补充项" not in report
    assert "真实用户外出分装反馈" in report
    assert "按小袋拿取，使用单元更清楚。" in report
    source_report = (delivery / "02_资料说明与缺口.md").read_text(encoding="utf-8")
    assert "商品详情页图片" in source_report
    assert "product_page_image" not in source_report

    helper_script = delivery / "fix_all_errors.py"
    helper_script.write_text("# synthetic forbidden correction helper\n", encoding="utf-8")
    helper_broken = validate_delivery(delivery)
    assert helper_broken["status"] == "failed"
    assert any("正式交付根目录不得包含修正脚本" in error for error in helper_broken["errors"])
    helper_script.unlink()

    value_path = delivery / "data" / "value_ledger.jsonl"
    values = read_jsonl(value_path)
    values[1]["layer"] = "deferred"
    values[1]["downstream_readiness"] = "blocked"
    write_jsonl(value_path, values)
    build_delivery(delivery, write=True)
    candidate_report = (delivery / "01_商品价值底座.md").read_text(encoding="utf-8")
    assert "按小袋拿取，使用单元更清楚。" in candidate_report
    assert "当前未选为核心价值" in candidate_report
    assert validate_delivery(delivery)["status"] == "passed"

    values[0]["supporting_fact_ids"].append("F-999")
    write_jsonl(value_path, values)
    broken = validate_delivery(delivery)
    assert broken["status"] == "failed"
    assert any("F-999" in error for error in broken["errors"])


def test_dynamic_and_semantic_guardrails(root: Path) -> None:
    delivery = root / "guardrails"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)

    fact_path = delivery / "data" / "fact_ledger.jsonl"
    facts = read_jsonl(fact_path)
    dyn = next(item for item in facts if item["fact_id"] == "DYN-001")
    original_time_scope = dyn["time_scope"]
    original_boundary = dyn["boundary"]

    current_year = datetime.now().astimezone().year
    dyn["time_scope"] = f"{current_year + 1}-08-04T00:00:00+08:00/{current_year + 1}-08-19T23:59:59+08:00"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    inferred_year_broken = validate_delivery(delivery)
    assert inferred_year_broken["status"] == "failed"
    assert any("补全的年份与来源 captured_at 不一致" in error for error in inferred_year_broken["errors"])
    assert any("必须在 boundary 明确披露推定依据" in error for error in inferred_year_broken["errors"])

    dyn["time_scope"] = f"{current_year}-08-04/{current_year}-08-19"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    lost_time_broken = validate_delivery(delivery)
    assert lost_time_broken["status"] == "failed"
    assert any("必须保留完整日期、时刻和时区" in error for error in lost_time_broken["errors"])

    dyn["time_scope"] = original_time_scope
    dyn["boundary"] = original_boundary
    dyn["boundary"] = "该活动已过期。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    date_broken = validate_delivery(delivery)
    assert date_broken["status"] == "failed"
    assert any("仍处活动期" in error for error in date_broken["errors"])

    dyn["boundary"] = "仅在完整日期区间内有效。"
    write_jsonl(fact_path, facts)
    value_path = delivery / "data" / "value_ledger.jsonl"
    values = read_jsonl(value_path)
    values[0]["value_statement"] = "获得传统滋养收益，并确保原料品质。"
    write_jsonl(value_path, values)
    build_delivery(delivery, write=True)
    semantic_broken = validate_delivery(delivery)
    assert semantic_broken["status"] == "failed"
    assert any("越界表达" in error for error in semantic_broken["errors"])

    facts[0]["statement"] = "采用传统九蒸九晒工艺。"
    facts.append(
        {
            "fact_id": "F-002",
            "fact_type": "F-EVIDENCE",
            "statement": "页面图片展示SGS检测报告编号 VHYF20250004-01。",
            "source_id": "SRC-001",
            "claim_ids": ["CLM-001"],
            "source_quotes": ["独立小袋包装"],
            "locator": "商品包装.txt｜页面内嵌报告",
            "sku_scope": "示例规格A",
            "time_scope": "当前页面版本",
            "status": "confirmed",
            "boundary": "精确编号仍需报告原件复核。",
            "evidence_detail_confidence": "medium",
            "exact_fields_verified": False,
            "verification_locator": "",
        }
    )
    write_jsonl(fact_path, facts)
    values[0]["scope"] = "全SKU适用"
    write_jsonl(value_path, values)
    source_path = delivery / "data" / "source_ledger.jsonl"
    sources = read_jsonl(source_path)
    sources[0]["locator"] = "重新编号后的图片1"
    write_jsonl(source_path, sources)
    build_delivery(delivery, write=True)
    traceability_broken = validate_delivery(delivery)
    assert traceability_broken["status"] == "failed"
    assert any("真实 relative_path" in error for error in traceability_broken["errors"])
    assert any("具体次数" in error for error in traceability_broken["errors"])
    assert any("含精确证据值" in error for error in traceability_broken["errors"])
    assert any("全 SKU" in error for error in traceability_broken["errors"])


def test_visual_observation_and_evidence_boundaries(root: Path) -> None:
    delivery = root / "visual-evidence"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)

    observation_path = delivery / "data" / "source_observation.jsonl"
    observations = read_jsonl(observation_path)
    observations[0]["title"] = "与来源台账不一致的标题"
    write_jsonl(observation_path, observations)
    mismatch = validate_delivery(delivery)
    assert mismatch["status"] == "failed"
    assert any("逐文件核对标题完全一致" in error for error in mismatch["errors"])

    observations[0]["title"] = "虚构商品包装信息"
    write_jsonl(observation_path, observations)
    fact_path = delivery / "data" / "fact_ledger.jsonl"
    facts = read_jsonl(fact_path)
    facts.append(
        {
            "fact_id": "F-002",
            "fact_type": "F-EVIDENCE",
            "statement": "页面图片展示某项检测为未检出。",
            "source_id": "SRC-004",
            "claim_ids": ["CLM-004"],
            "source_quotes": ["独立小袋包装"],
            "locator": "详情页主图.svg｜页面内嵌检测图",
            "sku_scope": "示例规格A",
            "time_scope": "当前页面版本",
            "status": "confirmed",
            "boundary": "仅保留页面可辨识的大字结论；报告编号 VHYF20250004-01 未经原件核验。",
            "evidence_detail_confidence": "high",
            "exact_fields_verified": True,
            "verification_locator": "详情页主图.svg",
        }
    )
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    image_exact = validate_delivery(delivery)
    assert image_exact["status"] == "failed"
    assert any("页面图片，不得设置 exact_fields_verified=true" in error for error in image_exact["errors"])
    assert any("证据细节可信度最高只能是 medium" in error for error in image_exact["errors"])
    assert any("不得在任何字段抄录" in error for error in image_exact["errors"])

    facts.pop()
    facts.append(
        {
            "fact_id": "F-002",
            "fact_type": "F-PAGE",
            "statement": "报告编号 VHYF20250004-01。",
            "source_id": "SRC-004",
            "claim_ids": ["CLM-004"],
            "source_quotes": ["独立小袋包装"],
            "locator": "详情页主图.svg",
            "sku_scope": "示例规格A",
            "time_scope": "当前页面版本",
            "status": "confirmed",
            "boundary": "仅用于测试事实类型绕过。",
        }
    )
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    wrong_fact_type = validate_delivery(delivery)
    assert wrong_fact_type["status"] == "failed"
    assert any("必须改为原件级 F-EVIDENCE" in error for error in wrong_fact_type["errors"])
    facts.pop()
    write_jsonl(fact_path, facts)
    image_observation = next(item for item in observations if item["observation_id"] == "OBS-004")
    original_card_hash = image_observation["audit_card_sha256"]
    image_observation["audit_card_sha256"] = "0" * 64
    write_jsonl(observation_path, observations)
    wrong_binding = validate_delivery(delivery)
    assert wrong_binding["status"] == "failed"
    assert any("audit_card_sha256" in error for error in wrong_binding["errors"])

    image_observation["audit_card_sha256"] = original_card_hash
    image_observation["visible_text_excerpt"] = "报告编号 VHYF20250004-01"
    image_observation["second_pass_excerpt"] = "报告编号 VHYF20250004-01"
    write_jsonl(observation_path, observations)
    exact_smuggling = validate_delivery(delivery)
    assert exact_smuggling["status"] == "failed"
    assert any("不得在逐图观察中抄录" in error for error in exact_smuggling["errors"])

    image_observation["visible_text_excerpt"] = "外出拿取更清楚"
    image_observation["second_pass_excerpt"] = "外出拿取更清楚"
    write_jsonl(observation_path, observations)
    card_path = delivery / "data" / "source_audit_cards" / f"{image_observation['source_file_id']}.svg"
    original_card = card_path.read_bytes()
    card_path.write_bytes(original_card + b"\n")
    tampered_card = validate_delivery(delivery)
    assert tampered_card["status"] == "failed"
    assert any("审计卡 SHA-256" in error for error in tampered_card["errors"])
    card_path.write_bytes(original_card)

    second_image_observation = next(item for item in observations if item["observation_id"] == "OBS-005")
    original_second_first_at = second_image_observation["inspected_at"]
    second_image_observation["inspected_at"] = image_observation["inspected_at"]
    write_jsonl(observation_path, observations)
    batch_timestamp = validate_delivery(delivery)
    assert batch_timestamp["status"] == "failed"
    assert any("不能批量填入同一时间" in error for error in batch_timestamp["errors"])
    second_image_observation["inspected_at"] = original_second_first_at
    write_jsonl(observation_path, observations)

    original_first_second_at = image_observation["second_pass_at"]
    original_second_second_at = second_image_observation["second_pass_at"]
    image_observation["second_pass_at"] = original_second_second_at
    second_image_observation["second_pass_at"] = original_first_second_at
    write_jsonl(observation_path, observations)
    fabricated_reverse = validate_delivery(delivery)
    assert fabricated_reverse["status"] == "failed"
    assert any("逆序复核时间必须按 second_pass_sequence" in error for error in fabricated_reverse["errors"])
    image_observation["second_pass_at"] = original_first_second_at
    second_image_observation["second_pass_at"] = original_second_second_at
    write_jsonl(observation_path, observations)

    gap_path = delivery / "data" / "gap_ledger.jsonl"
    gaps = read_jsonl(gap_path)
    gaps[0]["minimum_needed"] = "补充报告编号 VHYF20250004-01 对应的原件"
    write_jsonl(gap_path, gaps)
    build_delivery(delivery, write=True)
    leaked_exact_value = validate_delivery(delivery)
    assert leaked_exact_value["status"] == "failed"
    assert any("未由原件级 F-EVIDENCE" in error for error in leaked_exact_value["errors"])


def test_audit_timestamp_and_sku_guardrails(root: Path) -> None:
    delivery = root / "audit-time-sku"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)

    manifest_path = delivery / "data" / "product_manifest.json"
    manifest = read_json(manifest_path)
    original_created_at = manifest["created_at"]
    observations = read_jsonl(delivery / "data" / "source_observation.jsonl")
    first_observation_at = datetime.fromisoformat(observations[3]["inspected_at"])
    manifest["created_at"] = (first_observation_at + timedelta(minutes=1)).isoformat()
    write_json(manifest_path, manifest)
    timezone_broken = validate_delivery(delivery)
    assert timezone_broken["status"] == "failed"
    assert any("早于 product_manifest.created_at" in error for error in timezone_broken["errors"])
    manifest["created_at"] = original_created_at
    write_json(manifest_path, manifest)

    claim_path = delivery / "data" / "source_claim_ledger.jsonl"
    claims = read_jsonl(claim_path)
    original_first_recheck = claims[0]["rechecked_at"]
    claims[0]["rechecked_at"] = (
        datetime.fromisoformat(claims[-1]["claimed_at"]) - timedelta(seconds=1)
    ).isoformat()
    write_jsonl(claim_path, claims)
    overlap_broken = validate_delivery(delivery)
    assert overlap_broken["status"] == "failed"
    assert any("先完成全部原文主张的第三遍摘录" in error for error in overlap_broken["errors"])
    claims[0]["rechecked_at"] = original_first_recheck
    write_jsonl(claim_path, claims)

    manifest = read_json(manifest_path)
    original_updated_at = manifest["updated_at"]
    manifest["updated_at"] = (datetime.now().astimezone() - timedelta(minutes=20)).isoformat()
    write_json(manifest_path, manifest)
    stale_updated_at = validate_delivery(delivery)
    assert stale_updated_at["status"] == "failed"
    assert any("updated_at 必须晚于全部" in error for error in stale_updated_at["errors"])
    manifest["updated_at"] = original_updated_at
    write_json(manifest_path, manifest)

    evenly_spaced = [
        datetime.now().astimezone().replace(microsecond=0) + timedelta(seconds=15 * index)
        for index in range(8)
    ]
    assert suspicious_fixed_cadence(evenly_spaced)
    assert not suspicious_fixed_cadence(
        [evenly_spaced[0] + timedelta(seconds=value) for value in (0, 4, 9, 15, 22, 31, 43, 58)]
    )

    claims = read_jsonl(claim_path)
    base = datetime.now().astimezone().replace(microsecond=0) - timedelta(minutes=4)
    for index, claim in enumerate(claims):
        claim["claimed_at"] = (base + timedelta(seconds=index * 15)).isoformat()
        claim["rechecked_at"] = (base + timedelta(minutes=2, seconds=index * 20)).isoformat()
    write_jsonl(claim_path, claims)
    cadence_broken = validate_delivery(delivery)
    assert cadence_broken["status"] == "failed"
    assert any("摘录时间呈固定间隔批量生成" in error for error in cadence_broken["errors"])
    assert any("复核时间呈固定间隔批量生成" in error for error in cadence_broken["errors"])

    future_base = datetime.now().astimezone().replace(microsecond=0) + timedelta(days=1)
    for index, claim in enumerate(claims):
        claim["claimed_at"] = (future_base + timedelta(seconds=(0, 4, 9, 15, 22)[index])).isoformat()
        claim["rechecked_at"] = (future_base + timedelta(minutes=1, seconds=(0, 7, 15, 24, 34)[index])).isoformat()
    write_jsonl(claim_path, claims)
    future_broken = validate_delivery(delivery)
    assert future_broken["status"] == "failed"
    assert any("晚于 source_claim_ledger.jsonl 实际写入时间" in error for error in future_broken["errors"])

    manifest = read_json(manifest_path)
    manifest["sku"] = "九独立装"
    manifest["sku_status"] = "partial"
    manifest["sku_basis"] = "商品标题标注九独立装；商品信息区标示150g约10-12小袋，二者不一致，待核对"
    write_json(manifest_path, manifest)
    sku_broken = validate_delivery(delivery)
    assert sku_broken["status"] == "failed"
    assert any("不得继续把标题片段写成当前 SKU" in error for error in sku_broken["errors"])


def test_fabe_and_public_copy_guardrails(root: Path) -> None:
    delivery = root / "public-copy"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    fabe_path = delivery / "data" / "fabe_ledger.jsonl"
    chains = read_jsonl(fabe_path)
    chains[1]["evidence_fact_ids"] = ["STRAT-001"]
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    direct_broken = validate_delivery(delivery)
    assert direct_broken["status"] == "failed"
    assert any("Evidence 必须至少包含一条 Feature" in error for error in direct_broken["errors"])

    chains[1]["evidence_fact_ids"] = ["F-001"]
    write_jsonl(fabe_path, chains)
    value_path = delivery / "data" / "value_ledger.jsonl"
    values = read_jsonl(value_path)
    values[0]["value_statement"] = "无额外添加，差异化最强，还能形成安全底线。"
    write_jsonl(value_path, values)
    build_delivery(delivery, write=True)
    semantic_broken = validate_delivery(delivery)
    assert semantic_broken["status"] == "failed"
    assert any("无添加或无防腐剂" in error for error in semantic_broken["errors"])
    assert any("缺少竞品或行业对照" in error for error in semantic_broken["errors"])
    assert any("笼统安全结论" in error for error in semantic_broken["errors"])

    values[0]["value_statement"] = "让外出携带更省一步准备。"
    write_jsonl(value_path, values)
    decision_path = delivery / "data" / "p0_decision.json"
    decision = read_json(decision_path)
    decision["public_rationale"] = "该卖点出现次数最多、覆盖页面最广，很多用户不知道如何携带。"
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    p0_broken = validate_delivery(delivery)
    assert p0_broken["status"] == "failed"
    assert any("不能决定 P0" in error for error in p0_broken["errors"])
    assert any("不能声称最常见、主流、普遍或多数用户" in error for error in p0_broken["errors"])

    decision["public_rationale"] = "这是最常见的购买任务，但当前还没有用户原声。"
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    most_common_broken = validate_delivery(delivery)
    assert most_common_broken["status"] == "failed"
    assert any("不能声称最常见、主流、普遍或多数用户" in error for error in most_common_broken["errors"])

    decision["public_rationale"] = "外出前少一步分装与品牌当前方向一致，但仍需真实用户和同类商品对照验证。"
    write_json(decision_path, decision)
    chains = read_jsonl(fabe_path)
    original_advantage = chains[0]["advantage"]
    original_benefit = chains[0]["benefit"]

    chains[0]["advantage"] = "相对添加多种辅料的产品，当前商品更简单。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    misleading_comparison = validate_delivery(delivery)
    assert misleading_comparison["status"] == "failed"
    assert any("替代性比较" in error for error in misleading_comparison["errors"])

    chains[0]["advantage"] = original_advantage
    chains[0]["benefit"] = "黄精片仅适合泡水，因此即食形态使用更方便。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    unsupported_usage = validate_delivery(delivery)
    assert unsupported_usage["status"] == "failed"
    assert any("所引原文未作该限制" in error for error in unsupported_usage["errors"])

    chains[0]["benefit"] = original_benefit
    chains[0]["reference_frame"] = "用户处理生黄精的旧习惯"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    unsupported_habit = validate_delivery(delivery)
    assert unsupported_habit["status"] == "failed"
    assert any("未引用 U 用户证据" in error for error in unsupported_habit["errors"])

    chains[0]["reference_frame"] = "当前包装结构与临时分装任务的内生推导"
    chains[0]["benefit"] = "不用担心外出分装麻烦。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    absolute_reassurance = validate_delivery(delivery)
    assert absolute_reassurance["status"] == "failed"
    assert any("绝对化的“不用担心”" in error for error in absolute_reassurance["errors"])

    chains[0]["benefit"] = original_benefit
    chains[0]["advantage"] = "相比散装或大包装，独立小袋更利于外出携带。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    invented_product_comparison = validate_delivery(delivery)
    assert invented_product_comparison["status"] == "failed"
    assert any("无来源的产品替代对象" in error for error in invented_product_comparison["errors"])

    for unsupported_comparator in (
        "相对多配料复合食品，单一配料更容易看清。",
        "相对整袋大包装，当前包装更便于拿取。",
        "相对一般产区，页面描述了更具体的环境。",
        "相对部分使用硫熏工艺保色保鲜的加工方式，本品页面写明未经硫熏。",
    ):
        chains[0]["advantage"] = unsupported_comparator
        write_jsonl(fabe_path, chains)
        build_delivery(delivery, write=True)
        unsupported_comparison = validate_delivery(delivery)
        assert unsupported_comparison["status"] == "failed"
        assert any("无来源的产品替代对象" in error for error in unsupported_comparison["errors"])

    chains[0]["advantage"] = original_advantage
    write_jsonl(fabe_path, chains)
    decision["public_rationale"] = "生黄精不宜直接食用，当前商品可减少准备步骤。"
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    invented_restriction = validate_delivery(delivery)
    assert invented_restriction["status"] == "failed"
    assert any("新增了原文没有的限制性结论" in error for error in invented_restriction["errors"])

    decision["public_rationale"] = "外出前少一步分装与品牌当前方向一致，但仍需真实用户和同类商品对照验证。"
    write_json(decision_path, decision)

    chains[0]["benefit"] = "未经二氧化硫熏制，因此不引入二氧化硫残留风险。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    sulfur_overreach = validate_delivery(delivery)
    assert sulfur_overreach["status"] == "failed"
    assert any("不得把“未经二氧化硫熏制工艺”扩大" in error for error in sulfur_overreach["errors"])

    chains[0]["benefit"] = original_benefit
    chains[0]["advantage"] = "优惠可以叠加使用。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    unsupported_stacking = validate_delivery(delivery)
    assert unsupported_stacking["status"] == "failed"
    assert any("明确叠加规则" in error for error in unsupported_stacking["errors"])

    chains[0]["advantage"] = original_advantage
    write_jsonl(fabe_path, chains)


def test_narrative_integrity_and_advantage_quality(root: Path) -> None:
    delivery = root / "narrative-integrity"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)
    baseline = validate_delivery(delivery)
    assert baseline["status"] == "passed", baseline

    fabe_path = delivery / "data" / "fabe_ledger.jsonl"
    residual_cases = (
        ("boundary", "消除刺激性不扩大到 ；不预设/"),
        ("boundary", "多糖含量高低不直接推导；"),
        ("boundary", "单一原料不自动等于 ；不预设安全/健康收益"),
        ("boundary", "工艺描述不扩大到无残留风险，零残留不等同于；"),
        ("user_language", "食用安心（）"),
    )
    for field, residual in residual_cases:
        chains = read_jsonl(fabe_path)
        original = chains[0][field]
        chains[0][field] = residual
        write_jsonl(fabe_path, chains)
        build_delivery(delivery, write=True)
        broken = validate_delivery(delivery)
        assert broken["status"] == "failed"
        assert any(
            "不完整客户文本" in error or "空括号" in error
            for error in broken["errors"]
        ), broken
        chains[0][field] = original
        write_jsonl(fabe_path, chains)

    decision_path = delivery / "data" / "p0_decision.json"
    decision = read_json(decision_path)
    original_rationale = decision["rationale"]
    decision["rationale"] = "候选战略价值潜力低（工艺描述易越界为）。"
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    rationale_broken = validate_delivery(delivery)
    assert rationale_broken["status"] == "failed"
    assert any("p0_decision.rationale" in error and "不完整客户文本" in error for error in rationale_broken["errors"])
    decision["rationale"] = original_rationale
    write_json(decision_path, decision)

    chains = read_jsonl(fabe_path)
    original_advantage = chains[0]["advantage"]
    original_status = chains[0]["derivation_status"]
    chains[0]["advantage"] = "本品（基于页面内对比信息）"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    placeholder_broken = validate_delivery(delivery)
    assert placeholder_broken["status"] == "failed"
    assert any("占位式 Advantage" in error for error in placeholder_broken["errors"])

    chains[0]["advantage"] = "当前资料不足以形成可核对的相对优势，A层暂不成立。"
    chains[0]["derivation_status"] = "reasoned"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    status_broken = validate_delivery(delivery)
    assert status_broken["status"] == "failed"
    assert any("derivation_status 必须是 to_validate" in error for error in status_broken["errors"])

    chains[0]["derivation_status"] = "to_validate"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    explicit_gap = validate_delivery(delivery)
    assert explicit_gap["status"] == "passed", explicit_gap

    chains[0]["advantage"] = original_advantage
    chains[0]["derivation_status"] = original_status
    write_jsonl(fabe_path, chains)


def test_literal_claim_grounding(root: Path) -> None:
    delivery = root / "literal-claims"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)

    fact_path = delivery / "data" / "fact_ledger.jsonl"
    facts = read_jsonl(fact_path)
    facts[0]["statement"] = "包装标示每盒12袋。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    number_broken = validate_delivery(delivery)
    assert number_broken["status"] == "failed"
    assert any("数字未在所引原文主张中出现" in error for error in number_broken["errors"])

    facts[0]["statement"] = "包装标示独立小袋，适合老人。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    risky_word_broken = validate_delivery(delivery)
    assert risky_word_broken["status"] == "failed"
    assert any("高风险词" in error for error in risky_word_broken["errors"])

    facts[0]["statement"] = "页面写明黄精片软韧回甘。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    sensory_substitution = validate_delivery(delivery)
    assert sensory_substitution["status"] == "failed"
    assert any("回甜、回甘等近义词不得互换" in error for error in sensory_substitution["errors"])

    facts[0]["statement"] = "包装标示采用独立小袋分装。"
    write_jsonl(fact_path, facts)
    claim_path = delivery / "data" / "source_claim_ledger.jsonl"
    claims = read_jsonl(claim_path)

    facts[0]["statement"] = "包装标示采用独立小袋分装；如有胀袋，请勿食用。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    warning_fragment = validate_delivery(delivery)
    assert warning_fragment["status"] == "failed"
    assert any("关键字段或警示“如有胀袋”" in error for error in warning_fragment["errors"])

    facts[0]["statement"] = "包装标示采用独立小袋分装；生产日期见背面喷码。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    date_fragment = validate_delivery(delivery)
    assert date_fragment["status"] == "failed"
    assert any("关键字段或警示“生产日期”" in error for error in date_fragment["errors"])

    original_claim = dict(claims[0])
    claims[0].update(
        {
            "claim_type": "nutrition",
            "label": "脂肪",
            "verbatim_text": "独立小袋包装，脂肪0克",
            "critical": True,
        }
    )
    write_jsonl(claim_path, claims)
    facts[0]["statement"] = "包装标示采用独立小袋分装；脂肪0克、饱和脂肪0克。"
    facts[0]["source_quotes"] = ["独立小袋包装，脂肪0克"]
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    nutrition_fragment = validate_delivery(delivery)
    assert nutrition_fragment["status"] == "failed"
    assert any("关键字段或警示“饱和脂肪”" in error for error in nutrition_fragment["errors"])

    claims[0] = original_claim
    write_jsonl(claim_path, claims)
    facts[0]["statement"] = "包装标示采用独立小袋分装。"
    facts[0]["source_quotes"] = ["独立小袋包装"]
    write_jsonl(fact_path, facts)

    warning = dict(claims[3])
    warning.update(
        {
            "claim_id": "CLM-006",
            "claim_type": "warning",
            "label": "食用提示",
            "verbatim_text": "如有胀袋请勿食用",
            "visual_locator": "主图下部提示",
            "critical": True,
        }
    )
    claims.append(warning)
    write_jsonl(claim_path, claims)
    critical_unbound = validate_delivery(delivery)
    assert critical_unbound["status"] == "failed"
    assert any("关键原文字段，但没有进入任何事实记录" in error for error in critical_unbound["errors"])

    claims.pop()
    write_jsonl(claim_path, claims)
    faq_warning = dict(claims[3])
    faq_warning.update(
        {
            "claim_id": "CLM-006",
            "claim_type": "faq",
            "label": "特殊人群提示",
            "verbatim_text": "过敏体质禁止食用，特殊人群请遵医嘱",
            "critical": False,
        }
    )
    claims.append(faq_warning)
    write_jsonl(claim_path, claims)
    mislabeled_warning = validate_delivery(delivery)
    assert mislabeled_warning["status"] == "failed"
    assert any("claim_type 必须是 warning" in error for error in mislabeled_warning["errors"])
    assert any("critical 必须为 true" in error for error in mislabeled_warning["errors"])
    assert any("必须保留 warning 内容标记" in error for error in mislabeled_warning["errors"])
    claims.pop()
    write_jsonl(claim_path, claims)
    observation_path = delivery / "data" / "source_observation.jsonl"
    observations = read_jsonl(observation_path)
    observations[3]["content_flags"].append("warning")
    write_jsonl(observation_path, observations)
    missing_warning = validate_delivery(delivery)
    assert missing_warning["status"] == "failed"
    assert any("至少需要 1 条 warning 原文主张" in error for error in missing_warning["errors"])

    observations[3]["content_flags"].remove("warning")
    write_jsonl(observation_path, observations)
    facts[0]["boundary"] = "页面截图为medium置信度；证据细节可信度=medium；sku_status=unverified；参见CLM-046，仅证明包装结构。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    report = (delivery / "02_资料说明与缺口.md").read_text(encoding="utf-8")
    assert "medium置信度" not in report
    assert "页面截图可确认" in report
    assert "证据细节可信度=medium" not in report
    assert "sku_status=unverified" not in report
    assert "CLM-046" not in report
    assert validate_delivery(delivery)["status"] == "passed"


def test_sku_conflict_propagation_and_customer_fragments(root: Path) -> None:
    delivery = root / "sku-conflict"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    data = delivery / "data"

    manifest_path = data / "product_manifest.json"
    manifest = read_json(manifest_path)
    manifest.update(
        {
            "sku": "示例商品 150g/盒（小包数量待确认）",
            "sku_status": "partial",
            "sku_basis": "商品信息区显示150g、每盒约10~12小包；包装图疑似显示9独立装，二者冲突待确认",
            "delivery_status": "conditional",
        }
    )
    write_json(manifest_path, manifest)

    claims_path = data / "source_claim_ledger.jsonl"
    claims = read_jsonl(claims_path)
    claims[0].update(
        {
            "claim_type": "sku",
            "label": "净含量与小包数",
            "verbatim_text": "净含量150g，每盒约10~12小包",
            "critical": True,
        }
    )
    claims[3].update(
        {
            "claim_type": "packaging",
            "label": "包装数量",
            "verbatim_text": "150g/盒，9独立装",
            "critical": True,
        }
    )
    claims[4].update(
        {
            "claim_type": "sku",
            "label": "单包净含量",
            "verbatim_text": "单包净含量15g",
            "critical": True,
        }
    )
    write_jsonl(claims_path, claims)

    facts_path = data / "fact_ledger.jsonl"
    facts = read_jsonl(facts_path)
    facts[0].update(
        {
            "statement": "商品信息区标示净含量150g，每盒约10~12小包。",
            "source_quotes": ["净含量150g，每盒约10~12小包"],
            "boundary": "小包数量与包装图冲突，待实物确认。",
        }
    )
    facts.extend(
        [
            {
                "fact_id": "F-004",
                "fact_type": "F-PAGE",
                "statement": "包装图显示150g/盒、9独立装。",
                "source_id": "SRC-004",
                "claim_ids": ["CLM-004"],
                "source_quotes": ["150g/盒，9独立装"],
                "locator": "包装正面",
                "sku_scope": "当前商品",
                "time_scope": "当前页面",
                "status": "confirmed",
                "boundary": "与商品信息区的小包数量冲突。",
            },
            {
                "fact_id": "F-005",
                "fact_type": "F-PAGE",
                "statement": "包装图显示单包净含量15g。",
                "source_id": "SRC-005",
                "claim_ids": ["CLM-005"],
                "source_quotes": ["单包净含量15g"],
                "locator": "包装侧面",
                "sku_scope": "当前商品",
                "time_scope": "当前页面",
                "status": "confirmed",
                "boundary": "与总净含量和9独立装的算术关系冲突。",
            },
        ]
    )
    write_jsonl(facts_path, facts)

    gaps_path = data / "gap_ledger.jsonl"
    gaps = read_jsonl(gaps_path)
    gaps[0].update(
        {
            "category": "SKU规格",
            "missing": "150g/盒、约10~12小包、9独立装和15g/包之间存在冲突",
            "impact": "冲突规格不得进入商品价值",
            "minimum_needed": "清晰实物包装或SKU选择器",
            "state": "open",
        }
    )
    write_jsonl(gaps_path, gaps)
    build_delivery(delivery, write=True)
    conflicted = validate_delivery(delivery)
    assert conflicted["status"] == "failed"
    assert any("互不相容的小包数量" in error for error in conflicted["errors"])
    assert any("算术冲突" in error for error in conflicted["errors"])
    assert any("不得进入 FABE 推导" in error for error in conflicted["errors"])
    assert any("不得进入价值分层或 P0 候选" in error for error in conflicted["errors"])

    claims[3]["verbatim_text"] = "150G/oneBag/9g 9独立装"
    write_jsonl(claims_path, claims)
    facts = read_jsonl(facts_path)
    facts[-2]["source_quotes"] = ["150G/oneBag/9g 9独立装"]
    write_jsonl(facts_path, facts)
    build_delivery(delivery, write=True)
    malformed = validate_delivery(delivery)
    assert malformed["status"] == "failed"
    assert any("疑似 OCR 残片" in error for error in malformed["errors"])

    customer_delivery = root / "customer-fragments"
    init_delivery(customer_delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(customer_delivery)
    build_delivery(customer_delivery, write=True)
    report_path = customer_delivery / "02_资料说明与缺口.md"
    report = report_path.read_text(encoding="utf-8")
    report += "\n| 资料类型 | 当前说明 | 边界 |\n|---|---|---|\n| 页面事实 | 注册商标标识仅在 出现 | 与等工艺页口径一致， |\n"
    report_path.write_text(report, encoding="utf-8")
    fragment_broken = validate_delivery(customer_delivery)
    assert fragment_broken["status"] == "failed"
    assert any("客户残句" in error for error in fragment_broken["errors"])


def test_v013_p0_archive_comparator_and_report_regressions(root: Path) -> None:
    delivery = root / "v013-regressions"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)
    baseline = validate_delivery(delivery)
    assert baseline["status"] == "passed", baseline

    data = delivery / "data"
    inventory = read_jsonl(data / "source_inventory.jsonl")
    archive = next(item for item in inventory if item["filename"] == "原始资料包.zip")
    observations = read_jsonl(data / "source_observation.jsonl")
    archive_observation = next(item for item in observations if item["source_file_id"] == archive["source_file_id"])

    sources_path = data / "source_ledger.jsonl"
    sources = read_jsonl(sources_path)
    sources.append(
        {
            "source_id": "SRC-006",
            "source_file_id": archive["source_file_id"],
            "observation_id": archive_observation["observation_id"],
            "source_type": "F-PAGE",
            "title": archive_observation["title"],
            "locator": "原始资料包.zip｜归档文件",
            "captured_at": archive_observation["inspected_at"],
            "sku_scope": "示例规格A",
            "status": "active",
            "notes": "错误地把归档容器当成页面来源",
        }
    )
    write_jsonl(sources_path, sources)
    build_delivery(delivery, write=True)
    archive_as_page = validate_delivery(delivery)
    assert archive_as_page["status"] == "failed"
    assert any("压缩包或归档文件当成了可调用来源" in error for error in archive_as_page["errors"])
    write_jsonl(sources_path, sources[:-1])

    observations_path = data / "source_observation.jsonl"
    archive_observation["inspection_method"] = "document_text"
    archive_observation["inspection_status"] = "inspected"
    archive_observation["visible_heading"] = "归档文件"
    archive_observation["visible_text_excerpt"] = "错误地声称已读取"
    write_jsonl(observations_path, observations)
    build_delivery(delivery, write=True)
    archive_marked_read = validate_delivery(delivery)
    assert archive_marked_read["status"] == "failed"
    assert any("必须明确标记 unreadable" in error for error in archive_marked_read["errors"])
    archive_observation.update(
        {
            "inspection_method": "unsupported_archive",
            "inspection_status": "unreadable",
            "visible_heading": "",
            "visible_text_excerpt": "",
        }
    )
    write_jsonl(observations_path, observations)

    fabe_path = data / "fabe_ledger.jsonl"
    chains = read_jsonl(fabe_path)
    original_chain = dict(chains[0])
    chains[0]["advantage"] = "相较仅支持单一食用方式的产品，当前商品提供更多选择。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    expanded_comparator = validate_delivery(delivery)
    assert expanded_comparator["status"] == "failed"
    assert any("无来源的产品替代对象" in error for error in expanded_comparator["errors"])

    chains[0].update(original_chain)
    chains[0]["advantage"] = "当前资料不足以形成可核对的相对优势，A层暂不成立。"
    chains[0]["benefit"] = "无需另购不同形态产品。"
    chains[0]["derivation_status"] = "to_validate"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    unavailable_advantage_leak = validate_delivery(delivery)
    assert unavailable_advantage_leak["status"] == "failed"
    assert any("A 层暂不成立" in error for error in unavailable_advantage_leak["errors"])
    chains[0].update(original_chain)
    write_jsonl(fabe_path, chains)

    values_path = data / "value_ledger.jsonl"
    values = read_jsonl(values_path)
    original_value_statement = values[0]["value_statement"]
    values[0]["value_statement"] = "减少对多配料加工食品的查询顾虑。"
    write_jsonl(values_path, values)
    build_delivery(delivery, write=True)
    bare_target = validate_delivery(delivery)
    assert bare_target["status"] == "failed"
    assert any("无来源的产品替代对象" in error for error in bare_target["errors"])
    values[0]["value_statement"] = original_value_statement

    decision_path = data / "p0_decision.json"
    decision = read_json(decision_path)
    decision["status"] = "P0-SELECTED"
    values[0]["p0_status"] = "P0-SELECTED"
    write_json(decision_path, decision)
    write_jsonl(values_path, values)
    build_delivery(delivery, write=True)
    over_selected = validate_delivery(delivery)
    assert over_selected["status"] == "failed"
    assert any("只能标记为 P0-HYPOTHESIS" in error for error in over_selected["errors"])
    decision["status"] = "P0-HYPOTHESIS"
    values[0]["p0_status"] = "P0-HYPOTHESIS"
    write_json(decision_path, decision)
    write_jsonl(values_path, values)

    chains = read_jsonl(fabe_path)
    chains[0]["user_language"] = "由难入口温和转为难入口温和。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    contradiction = validate_delivery(delivery)
    assert contradiction["status"] == "failed"
    assert any("语义矛盾残句" in error for error in contradiction["errors"])
    chains[0].update(original_chain)
    write_jsonl(fabe_path, chains)

    build_delivery(delivery, write=True)
    report_path = delivery / "01_商品价值底座.md"
    report_path.write_text(
        report_path.read_text(encoding="utf-8")
        + "\n/005/006 //reference_frame 对应的回答已登记为 。\n",
        encoding="utf-8",
    )
    report_drift = validate_delivery(delivery)
    assert report_drift["status"] == "failed"
    assert any("与当前结构化账本不一致" in error for error in report_drift["errors"])
    assert any("内部删减残片" in error for error in report_drift["errors"])

    cleaned = public_text("FABE-004/005/006的A层；FABE-004/005/006的reference_frame；对应的回答已登记为 F-004。")
    assert "相关价值的 A 层" in cleaned
    assert "相关价值的参照系" in cleaned
    assert "对应回答已在相关事实中登记" in cleaned
    assert "/005/006" not in cleaned and "reference_frame" not in cleaned


def test_v014_client_semantic_and_cross_field_regressions(root: Path) -> None:
    cleaned = public_text(
        "小包数在F-002中以partial状态说明；无STRAT与U；F-EVIDENCE为页面图示；"
        "DYN截至updated_at仍有效；ZIP未读取；P0-HYPOTHESIS。"
    )
    assert "在相关事实中以部分确认状态说明" in cleaned
    assert "品牌战略资料" in cleaned and "用户原声" in cleaned
    assert "证据资料" in cleaned and "动态交易信息" in cleaned
    assert "本次更新时间" in cleaned and "压缩包" in cleaned
    assert "优先验证的核心价值" in cleaned
    assert "partial" not in cleaned and "STRAT" not in cleaned and "updated_at" not in cleaned

    delivery = root / "v014-regressions"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)
    baseline = validate_delivery(delivery)
    assert baseline["status"] == "passed", baseline

    data = delivery / "data"
    values_path = data / "value_ledger.jsonl"
    values = read_jsonl(values_path)
    original_values = [dict(value) for value in values]

    values[0]["user_task"] = "场景切换中不需要为不同形态再单独准备"
    write_jsonl(values_path, values)
    build_delivery(delivery, write=True)
    paraphrased_comparator = validate_delivery(delivery)
    assert paraphrased_comparator["status"] == "failed"
    assert any("无来源的产品替代对象" in error for error in paraphrased_comparator["errors"])
    values = [dict(value) for value in original_values]

    values[1]["user_task"] = "在活动窗口内叠加优惠"
    values[1]["user_perception_goal"] = "用户感知可叠加的优惠"
    values[1]["cannot_prove"] = ["原文未明确说明权益可与其他优惠叠加，不得写可叠加"]
    write_jsonl(values_path, values)
    build_delivery(delivery, write=True)
    stacking_contradiction = validate_delivery(delivery)
    assert stacking_contradiction["status"] == "failed"
    assert any("支撑事实所引原文没有明确叠加规则" in error for error in stacking_contradiction["errors"])
    assert any("结构化结论自相矛盾" in error for error in stacking_contradiction["errors"])
    write_jsonl(values_path, original_values)

    decision_path = data / "p0_decision.json"
    decision = read_json(decision_path)
    original_decision = dict(decision)
    decision["cannot_prove"] = list(decision["cannot_prove"]) + [
        "不能把DYN-001活动写成当前有效，虽然本次快照仍处活动期"
    ]
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    active_contradiction = validate_delivery(delivery)
    assert active_contradiction["status"] == "failed"
    assert any("否定了快照时仍处活动期" in error for error in active_contradiction["errors"])
    write_json(decision_path, original_decision)

    values = read_jsonl(values_path)
    values[1]["downstream_readiness"] = "blocked"
    write_jsonl(values_path, values)
    decision = dict(original_decision)
    decision["current_execution_value_ids"] = ["V-001", "V-002"]
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    blocked_axis = validate_delivery(delivery)
    assert blocked_axis["status"] == "failed"
    assert any("当前执行主轴不得引用暂缓或禁止调用" in error for error in blocked_axis["errors"])
    write_jsonl(values_path, original_values)
    write_json(decision_path, original_decision)

    fabe_path = data / "fabe_ledger.jsonl"
    chains = read_jsonl(fabe_path)
    original_chains = [dict(chain) for chain in chains]
    for chain in chains:
        chain["advantage"] = "当前资料不足以形成可核对的相对优势，A层暂不成立。"
        chain["derivation_status"] = "to_validate"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    all_advantages_removed = validate_delivery(delivery)
    assert all_advantages_removed["status"] == "failed"
    assert any("全部可用价值的 Advantage" in error for error in all_advantages_removed["errors"])
    write_jsonl(fabe_path, original_chains)

    timestamp_delivery = root / "v014-updated-at"
    init_delivery(timestamp_delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(timestamp_delivery)
    build_delivery(timestamp_delivery, write=True)
    manifest = read_json(timestamp_delivery / "data" / "product_manifest.json")
    logical_time = datetime.fromisoformat(manifest["updated_at"]).timestamp()
    report_path = timestamp_delivery / "01_商品价值底座.md"
    os.utime(report_path, (logical_time + 360, logical_time + 360))
    late_report = validate_delivery(timestamp_delivery)
    assert late_report["status"] == "failed"
    assert any("updated_at 之后超过 5 分钟" in error for error in late_report["errors"])


def test_v015_cross_ledger_and_public_copy_regressions(root: Path) -> None:
    cleaned = public_text(
        "CLM-019 在 SRC-007 包装面标示；V-001 / V-002 / 等候选；"
        "active_at_snapshot；cannot_prove。"
    )
    assert "相关原文在包装面标示" in cleaned
    assert "/ /" not in cleaned
    assert "采集时当前有效" in cleaned
    assert "当前资料不能证明" in cleaned

    dense_start = datetime.now().astimezone().replace(microsecond=0)
    dense_times = [
        dense_start + timedelta(seconds=sum((1, 2, 3)[offset % 3] for offset in range(index)))
        for index in range(12)
    ]
    assert suspicious_dense_cadence(dense_times)
    assert not suspicious_dense_cadence(
        [dense_start + timedelta(seconds=index * index + index * 8) for index in range(12)]
    )

    delivery = root / "v015-regressions"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)
    baseline = validate_delivery(delivery)
    assert baseline["status"] == "passed", baseline

    data = delivery / "data"
    claim_path = data / "source_claim_ledger.jsonl"
    claims = read_jsonl(claim_path)
    original_claims = [dict(claim) for claim in claims]
    claims[3]["verbatim_text"] = "检测方法 GB 5009.34-2022"
    write_jsonl(claim_path, claims)
    method_code = validate_delivery(delivery)
    assert method_code["status"] == "failed"
    assert any("精确小字" in error for error in method_code["errors"])
    write_jsonl(claim_path, original_claims)

    gap_path = data / "gap_ledger.jsonl"
    gaps = read_jsonl(gap_path)
    original_gaps = [dict(gap) for gap in gaps]
    gaps[0]["category"] = "sku"
    gaps[0]["missing"] = "包数冲突：10~12小包 vs 15袋"
    gaps[0]["impact"] = "冲突规格不得进入识别锚、FABE、价值或P0"
    write_jsonl(gap_path, gaps)
    anchor_path = data / "anchor_ledger.jsonl"
    anchors = read_jsonl(anchor_path)
    original_anchors = [dict(anchor) for anchor in anchors]
    anchors[0]["statement"] = "约10~12小包独立装"
    write_jsonl(anchor_path, anchors)
    build_delivery(delivery, write=True)
    conflict = validate_delivery(delivery)
    assert conflict["status"] == "failed"
    assert any("没有完整进入 source_claim_ledger.jsonl" in error for error in conflict["errors"])
    assert any("不得进入识别锚、FABE 或价值结论" in error for error in conflict["errors"])
    source_report = (delivery / "02_资料说明与缺口.md").read_text(encoding="utf-8")
    assert "商品规格" in source_report
    assert "| sku |" not in source_report
    write_jsonl(gap_path, original_gaps)
    write_jsonl(anchor_path, original_anchors)

    fabe_path = data / "fabe_ledger.jsonl"
    chains = read_jsonl(fabe_path)
    original_chains = [dict(chain) for chain in chains]
    chains[0]["advantage"] = "与配料表同时列出多种原料的同类食品相比，更容易理解当前配料。"
    write_jsonl(fabe_path, chains)
    build_delivery(delivery, write=True)
    comparator = validate_delivery(delivery)
    assert comparator["status"] == "failed"
    assert any("比较语言" in error or "市场或产品比较语言" in error for error in comparator["errors"])
    write_jsonl(fabe_path, original_chains)

    fact_path = data / "fact_ledger.jsonl"
    facts = read_jsonl(fact_path)
    original_facts = [dict(fact) for fact in facts]
    facts[0]["boundary"] = "页面写为未经二次硫熏制工艺。"
    write_jsonl(fact_path, facts)
    build_delivery(delivery, write=True)
    chemical_typo = validate_delivery(delivery)
    assert chemical_typo["status"] == "failed"
    assert any("二次硫" in error for error in chemical_typo["errors"])
    write_jsonl(fact_path, original_facts)

    decision_path = data / "p0_decision.json"
    decision = read_json(decision_path)
    decision["current_execution_axis"] = "围绕包装便利与其他支撑价值展开。"
    write_json(decision_path, decision)
    build_delivery(delivery, write=True)
    axis_drift = validate_delivery(delivery)
    assert axis_drift["status"] == "failed"
    assert any("按顺序自动拼接" in error for error in axis_drift["errors"])


def test_v016_audit_semantics_and_client_cleanup(root: Path) -> None:
    cadence_start = datetime.now().astimezone().replace(microsecond=0)
    cadence_times = [cadence_start]
    for index in range(15):
        cadence_times.append(cadence_times[-1] + timedelta(seconds=(6, 7, 8, 9)[index % 4]))
    assert suspicious_repeating_cadence(cadence_times)
    assert not suspicious_repeating_cadence(
        [cadence_start + timedelta(seconds=index * index + index * 11) for index in range(16)]
    )

    cleaned = public_text(
        "未取得 U 用户原声；user_task 与 user_perception_goal 待补；"
        "证据细节可信度=medium；exact_fields_verified=否；资料包.zip；read"
    )
    assert "用户原声 用户原声" not in cleaned
    assert "user_task" not in cleaned
    assert "user_perception_goal" not in cleaned
    assert "证据细节可信度" not in cleaned
    assert "exact_fields_verified" not in cleaned
    assert ".压缩包" not in cleaned
    assert "已读取" in cleaned

    delivery = root / "v016-regressions"
    init_delivery(delivery, "示例品牌", "示例商品", "示例品类", "示例规格A", "mixed")
    populate_valid_partial(delivery)
    build_delivery(delivery, write=True)
    baseline = validate_delivery(delivery)
    assert baseline["status"] == "passed", baseline

    data = delivery / "data"
    manifest_path = data / "product_manifest.json"
    manifest = read_json(manifest_path)
    original_manifest = dict(manifest)
    manifest["sku_basis"] = "商品信息页支持规格A，但本地文件名九独立装形成冲突。"
    write_json(manifest_path, manifest)
    filename_evidence = validate_delivery(delivery)
    assert filename_evidence["status"] == "failed"
    assert any("文件名或文件路径" in error for error in filename_evidence["errors"])
    write_json(manifest_path, original_manifest)

    fabe_path = data / "fabe_ledger.jsonl"
    chains = read_jsonl(fabe_path)
    original_chains = [dict(chain) for chain in chains]
    chains[0]["benefit"] = "可直接食用，不必另购其他形态产品。"
    write_jsonl(fabe_path, chains)
    unsupported_purchase = validate_delivery(delivery)
    assert unsupported_purchase["status"] == "failed"
    assert any("产品替代对象" in error for error in unsupported_purchase["errors"])
    chains = [dict(chain) for chain in original_chains]
    chains[0]["advantage"] = "相比配料多栏的产品，本品信息更简短。"
    write_jsonl(fabe_path, chains)
    unsupported_ingredient_comparison = validate_delivery(delivery)
    assert unsupported_ingredient_comparison["status"] == "failed"
    assert any("产品替代对象" in error or "比较语言" in error for error in unsupported_ingredient_comparison["errors"])
    write_jsonl(fabe_path, original_chains)

    decision_path = data / "p0_decision.json"
    decision = read_json(decision_path)
    original_decision = dict(decision)
    decision["public_rationale"] = "这些价值直接对应用户对处理工序与安全选材的核心顾虑。"
    write_json(decision_path, decision)
    unsupported_user_concern = validate_delivery(delivery)
    assert unsupported_user_concern["status"] == "failed"
    assert any("用户的核心" in error for error in unsupported_user_concern["errors"])
    write_json(decision_path, original_decision)

    values_path = data / "value_ledger.jsonl"
    values = read_jsonl(values_path)
    original_values = [dict(value) for value in values]
    values[0]["user_task"] = "担心硫熏工艺对安全的影响。"
    write_jsonl(values_path, values)
    unsupported_safety = validate_delivery(delivery)
    assert unsupported_safety["status"] == "failed"
    assert any("无硫熏主张扩写" in error for error in unsupported_safety["errors"])
    write_jsonl(values_path, original_values)

    claim_path = data / "source_claim_ledger.jsonl"
    claims = read_jsonl(claim_path)
    original_claims = [dict(claim) for claim in claims]
    seed = dict(claims[0])
    periodic_claims = []
    claim_start = datetime.now().astimezone().replace(microsecond=0) - timedelta(minutes=6)
    claim_times = [claim_start]
    for index in range(12):
        claim_times.append(claim_times[-1] + timedelta(seconds=(6, 7, 8, 9)[index % 4]))
    recheck_start = claim_times[-1] + timedelta(seconds=30)
    recheck_times = [recheck_start]
    for index in range(12):
        recheck_times.append(recheck_times[-1] + timedelta(seconds=(6, 7, 8, 9)[index % 4]))
    for index in range(13):
        claim = dict(seed)
        claim["claim_id"] = f"CLM-{index + 1:03d}"
        claim["claim_type"] = "other"
        claim["critical"] = False
        claim["claimed_at"] = claim_times[index].isoformat()
        claim["rechecked_at"] = recheck_times[index].isoformat()
        periodic_claims.append(claim)
    write_jsonl(claim_path, periodic_claims)
    repeating_claims = validate_delivery(delivery)
    assert repeating_claims["status"] == "failed"
    assert any("重复循环节奏" in error for error in repeating_claims["errors"])
    write_jsonl(claim_path, original_claims)


def test_insufficient_delivery(root: Path) -> None:
    delivery = root / "insufficient"
    init_delivery(delivery, "示例品牌", "待确认商品", "示例品类", "待确认", "document")
    data = delivery / "data"
    manifest = read_json(data / "product_manifest.json")
    manifest.update(
        {
            "sku_status": "unverified",
            "sku_basis": "当前只有商品名称，尚无包装或规格表",
            "analysis_status": "insufficient",
            "delivery_status": "blocked",
            "limitations": ["无法确认当前 SKU，不得形成价值结论。"],
            "updated_at": now_iso(),
        }
    )
    write_json(data / "product_manifest.json", manifest)
    write_jsonl(
        data / "gap_ledger.jsonl",
        [
            {
                "gap_id": "GAP-001",
                "category": "商品身份",
                "missing": "当前 SKU",
                "impact": "无法隔离商品事实",
                "minimum_needed": "当前商品链接、包装或 SKU 表",
                "priority": "P0",
                "state": "open",
            }
        ],
    )
    build_delivery(delivery, write=True)
    result = validate_delivery(delivery)
    assert result["status"] == "passed", result


def main() -> int:
    root = Path.cwd() / f".brandbai-product-value-test-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        test_partial_delivery(root)
        test_dynamic_and_semantic_guardrails(root)
        test_visual_observation_and_evidence_boundaries(root)
        test_audit_timestamp_and_sku_guardrails(root)
        test_fabe_and_public_copy_guardrails(root)
        test_narrative_integrity_and_advantage_quality(root)
        test_literal_claim_grounding(root)
        test_sku_conflict_propagation_and_customer_fragments(root)
        test_v013_p0_archive_comparator_and_report_regressions(root)
        test_v014_client_semantic_and_cross_field_regressions(root)
        test_v015_cross_ledger_and_public_copy_regressions(root)
        test_v016_audit_semantics_and_client_cleanup(root)
        test_insufficient_delivery(root)
    finally:
        shutil.rmtree(root)
    print("PASS: product value delivery synthetic tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
