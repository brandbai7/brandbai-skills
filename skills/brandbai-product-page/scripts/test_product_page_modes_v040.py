"""Focused regression tests for the standalone and evidence-enhanced 0.4 modes."""

from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

from build_product_page_report import build_delivery
from init_product_page_delivery import init_delivery
from product_page_common import now_iso, read_json, read_jsonl, write_json, write_jsonl
from test_product_page_delivery import make_page_sources, populate_degraded
from validate_product_page_delivery import validate_delivery


def assert_passed(delivery: Path) -> None:
    result = validate_delivery(delivery)
    assert result["status"] == "passed", json.dumps(result, ensure_ascii=False, indent=2)


def run_test() -> None:
    root = Path(__file__).resolve().parent / "_skill_test_artifacts" / f"product-page-v040-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    try:
        page_sources = make_page_sources(root)

        page_only = root / "page-only"
        init_delivery(
            page_only, page_sources, None, None,
            "测试品牌", "测试饮品", "饮料", "300毫升乘12瓶",
            "combined", "diagnose", "course", "2026-08-22T10:00:00+08:00", "", None,
            analysis_mode="diagnose_existing",
        )
        populate_degraded(page_only)
        actions_path = page_only / "data" / "action_ledger.jsonl"
        seed = read_jsonl(actions_path)[0]
        actions = []
        for index in range(1, 6):
            item = deepcopy(seed)
            item["action_id"] = f"ACT-{index:03d}"
            item["priority"] = index
            item["page_location"] = f"主图候选位置{index}"
            item["action_detail"] = f"只依据页面可见内容完成第{index}项结构澄清，不新增商品主张。"
            item["recommendation_label"] = "可直接优化"
            actions.append(item)
        write_jsonl(actions_path, actions)
        build_delivery(page_only, write=True)
        assert_passed(page_only)
        report = (page_only / "01_商品页诊断与优化建议.md").read_text(encoding="utf-8")
        assert report.count("### 优先") == 5
        assert "可直接优化" in report

        supporting = root / "supporting"
        supporting.mkdir()
        (supporting / "evidence.txt").write_text("当前规格为300毫升乘12瓶。", encoding="utf-8")
        enhanced = root / "enhanced"
        init_delivery(
            enhanced, page_sources, None, None,
            "测试品牌", "测试饮品", "饮料", "300毫升乘12瓶",
            "combined", "diagnose", "professional", "2026-08-22T10:00:00+08:00", "", None,
            analysis_mode="enhance_with_evidence", supporting_sources=supporting,
        )
        populate_degraded(enhanced)
        data = enhanced / "data"
        manifest = read_json(data / "page_manifest.json")
        manifest.update(
            {
                "analysis_mode": "enhance_with_evidence",
                "run_status": "partial",
                "analysis_status": "partial",
                "delivery_status": "conditional",
                "updated_at": now_iso(),
            }
        )
        write_json(data / "page_manifest.json", manifest)
        support_rows = read_jsonl(data / "supporting_source_inventory.jsonl")
        support_rows[0]["source_role"] = "evidence_document"
        support_rows[0]["readability_status"] = "readable"
        write_jsonl(data / "supporting_source_inventory.jsonl", support_rows)
        claim = {
            "claim_id": "CLAIM-001",
            "statement": "当前成交规格为300毫升乘12瓶。",
            "claim_type": "confirmed_fact",
            "supporting_source_ids": ["SUP-SF-001"],
            "applicable_sku": "300毫升乘12瓶",
            "support_scope": "规格与实际到手",
            "evidence_status": "usable",
            "can_support": "交易区与详情页的当前规格说明",
            "cannot_prove": "不能证明其他规格、销量或转化结果",
            "dynamic_status": "not_dynamic",
            "human_confirmation": "发布前由商品负责人复核当前链接选中项",
            "boundary": "仅适用于本次当前SKU。",
        }
        write_jsonl(data / "claim_ledger.jsonl", [claim])
        enhanced_actions = read_jsonl(data / "action_ledger.jsonl")
        enhanced_actions[0].update(
            {
                "basis_type": "supplemental_evidence",
                "basis_summary": "当前规格文件与页面位置共同支持",
                "supporting_source_ids": ["SUP-SF-001"],
                "claim_ids": ["CLAIM-001"],
                "recommendation_label": "待上线验证",
            }
        )
        write_jsonl(data / "action_ledger.jsonl", enhanced_actions)
        write_jsonl(data / "gap_ledger.jsonl", [])
        build_delivery(enhanced, write=True)
        assert_passed(enhanced)

        bad_claim = deepcopy(claim)
        bad_claim["claim_type"] = "user_signal"
        write_jsonl(data / "claim_ledger.jsonl", [bad_claim])
        failed = validate_delivery(enhanced)
        assert any("E_COMMENT_AS_PRODUCT_FACT" in item for item in failed["errors"])

        bad_claim = deepcopy(claim)
        bad_claim["applicable_sku"] = "其他规格"
        write_jsonl(data / "claim_ledger.jsonl", [bad_claim])
        failed = validate_delivery(enhanced)
        assert any("E_SKU_APPLICABILITY" in item for item in failed["errors"])

        print("product-page v0.4 mode tests passed")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            root.parent.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    run_test()
