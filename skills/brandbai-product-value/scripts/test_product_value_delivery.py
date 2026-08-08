"""Offline synthetic tests for BrandBAI Product Value."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from build_product_value_report import build_delivery
from build_source_audit_cards import build_cards
from index_product_sources import index_sources
from init_product_value_delivery import build_plan, init_delivery
from product_value_common import now_iso, read_json, read_jsonl, write_json, write_jsonl
from validate_product_value_delivery import validate_delivery


def populate_valid_partial(delivery: Path) -> None:
    data = delivery / "data"
    timestamp = now_iso()
    source_dir = delivery.parent / f"{delivery.name}-source-materials"
    source_dir.mkdir()
    (source_dir / "商品包装.txt").write_text("独立小袋包装", encoding="utf-8")
    (source_dir / "品牌方向.txt").write_text("外出携带", encoding="utf-8")
    (source_dir / "活动信息.txt").write_text("虚构活动日期", encoding="utf-8")
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
    indexed = index_sources(source_dir, delivery, write=True)
    assert indexed["file_count"] == 5
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
    first_pass_at = datetime.now().astimezone().replace(microsecond=0)
    second_image_first_pass_at = first_pass_at + timedelta(seconds=1)
    second_pass_at = first_pass_at + timedelta(seconds=2)
    first_image_second_pass_at = first_pass_at + timedelta(seconds=3)
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
            },
            {
                "observation_id": "OBS-003",
                "source_file_id": inventory_ids["活动信息.txt"],
                "relative_path": "活动信息.txt",
                "content_type": "promotion",
                "title": "虚构限时活动信息",
                "visible_heading": "虚构活动日期",
                "visible_text_excerpt": "虚构活动日期",
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
            "updated_at": timestamp,
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
                "locator": "活动图片",
                "sku_scope": "示例规格A",
                "time_scope": f"{(datetime.now().astimezone().date() - timedelta(days=1)).isoformat()}~{(datetime.now().astimezone().date() + timedelta(days=1)).isoformat()}",
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
                "advantage": "相比临时自行分装，商品已经按小袋形成拿取单元。",
                "benefit": "外出前可以少做一步分装准备。",
                "evidence": "包装正背面可直接核对独立小袋结构（SRC-001/F-001）。",
                "evidence_fact_ids": ["F-001"],
                "reference_frame": "临时自行分装的旧习惯",
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
            "current_execution_axis": "先说明独立小袋如何减少外出前的分装步骤。",
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
    source_report = (delivery / "02_资料说明与缺口.md").read_text(encoding="utf-8")
    assert "商品详情页图片" in source_report
    assert "product_page_image" not in source_report

    value_path = delivery / "data" / "value_ledger.jsonl"
    values = read_jsonl(value_path)
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

    gap_path = delivery / "data" / "gap_ledger.jsonl"
    gaps = read_jsonl(gap_path)
    gaps[0]["minimum_needed"] = "补充报告编号 VHYF20250004-01 对应的原件"
    write_jsonl(gap_path, gaps)
    build_delivery(delivery, write=True)
    leaked_exact_value = validate_delivery(delivery)
    assert leaked_exact_value["status"] == "failed"
    assert any("未由原件级 F-EVIDENCE" in error for error in leaked_exact_value["errors"])


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
    assert any("不能声称很多或多数用户" in error for error in p0_broken["errors"])


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
        test_fabe_and_public_copy_guardrails(root)
        test_insufficient_delivery(root)
    finally:
        shutil.rmtree(root)
    print("PASS: product value delivery synthetic tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
