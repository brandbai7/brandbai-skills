"""Synthetic end-to-end tests for BrandBAI Value Expression."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from build_value_expression_report import build_delivery
from init_value_expression_delivery import build_plan, init_delivery
from validate_value_expression_delivery import validate_delivery
from value_expression_common import (
    ROUTES,
    now_iso,
    read_json,
    read_jsonl,
    value_expression_id,
    write_json,
    write_jsonl,
)


def make_product_value_delivery(root: Path) -> Path:
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
            "limitations": ["当前只有公开商品页资料。"],
            "updated_at": timestamp,
        },
    )
    write_jsonl(
        data / "fact_ledger.jsonl",
        [
            {
                "fact_id": "F-001",
                "fact_type": "F",
                "statement": "每瓶300毫升。",
                "source_id": "SRC-001",
                "locator": "商品页规格区",
                "boundary": "仅适用于当前SKU。",
            },
            {
                "fact_id": "EX-001",
                "fact_type": "EX",
                "statement": "随时来一瓶。",
                "source_id": "SRC-001",
                "locator": "商品页首屏",
                "boundary": "这是页面表达，不代表效果已验证。",
            },
            {
                "fact_id": "F-002",
                "fact_type": "F-EVIDENCE",
                "statement": "详情页截图显示检测结果为ND（未检出），单项结论符合。",
                "source_id": "SRC-002",
                "source_quotes": ["ND", "未检出", "符合"],
                "locator": "商品页检测截图",
                "boundary": "仅为详情页截图级证据，精确小字未核验。",
                "evidence_detail_confidence": "medium",
                "exact_fields_verified": False,
                "verification_locator": "",
            },
        ],
    )
    write_jsonl(data / "fabe_ledger.jsonl", [{"fabe_id": "FABE-001"}])
    write_jsonl(data / "anchor_ledger.jsonl", [{"anchor_id": "ANCHOR-001"}])
    write_jsonl(
        data / "value_ledger.jsonl",
        [
            {
                "value_id": "V-001",
                "layer": "P0",
                "p0_status": "recommended",
                "user_task": "快速看懂核心体验",
                "value_statement": "入口有明显气泡感",
                "user_perception_goal": "看见并听见气泡感",
                "downstream_readiness": "ready",
                "cannot_prove": ["不能承诺所有人的味觉感受相同"],
            },
            {
                "value_id": "V-002",
                "layer": "P1",
                "p0_status": "supporting",
                "user_task": "判断规格是否适合",
                "value_statement": "小瓶便于单次饮用",
                "user_perception_goal": "一眼理解瓶型和份量",
                "downstream_readiness": "ready",
                "cannot_prove": [],
            },
            {
                "value_id": "V-003",
                "layer": "P2",
                "p0_status": "supporting",
                "user_task": "确认当前规格",
                "value_statement": "整箱12瓶",
                "user_perception_goal": "明确收到的数量",
                "downstream_readiness": "ready",
                "cannot_prove": [],
            },
        ],
    )
    write_json(
        data / "p0_decision.json",
        {
            "decision_id": "P0D-001",
            "status": "P0-LOCKED",
            "recommended_value_id": "V-001",
        },
    )
    return delivery


def route_rows() -> list[dict[str, object]]:
    choices = {
        "V-001": ("感官化", ["情境化", "差异化"]),
        "V-002": ("数字化", ["情境化"]),
        "V-003": ("证据化", ["数字化"]),
    }
    rows: list[dict[str, object]] = []
    number = 1
    for value_id, (primary, supporting) in choices.items():
        for route in sorted(ROUTES):
            role = "primary" if route == primary else "supporting" if route in supporting else "not_prioritized"
            rows.append(
                {
                    "scan_id": f"PATH-{number:03d}",
                    "value_id": value_id,
                    "route": route,
                    "role": role,
                    "translation": f"用{route}解释当前价值。",
                    "reason": "保留完整扫描并说明本轮优先级。",
                    "fact_ids": ["F-001"],
                    "expression_ids": ["EX-001"],
                    "boundary": "只使用当前商品事实，不扩大承诺。",
                }
            )
            number += 1
    return rows


def vis_row(
    vis_id: str,
    value_id: str,
    slot_number: str,
    asset_group: str,
    primary_route: str,
    supporting_routes: list[str],
    priority: int,
) -> dict[str, object]:
    return {
        "vis_id": vis_id,
        "value_id": value_id,
        "secondary_value_ids": [],
        "asset_group": asset_group,
        "slot_number": slot_number,
        "user_question": "这个特点和我有什么关系？",
        "target_perception": "用户能看懂、听见并复述当前价值。",
        "decision_task": "看懂" if value_id == "V-001" else "选对",
        "primary_route": primary_route,
        "supporting_routes": supporting_routes,
        "fact_ids": ["F-001"],
        "expression_ids": ["EX-001"],
        "human_language": f"这是第{priority}个可感知卖点。",
        "visual_track": "商品与关键状态同框，主体清楚。",
        "action_track": "用一次完整动作展示状态变化。",
        "sound_track": "保留真实动作声，不伪造效果。",
        "subtitle_track": "字幕只写当前事实和用户能理解的话。",
        "prop_track": "只使用能帮助理解商品的真实道具。",
        "scene_track": "放进真实、可复现的使用场景。",
        "effect_bgm_track": "特效和音乐只辅助节奏，不替代商品证据。",
        "commerce_handoff_track": "展示当前商品和规格，动态权益留空。",
        "must_keep": "商品身份、核心事实和表达边界。",
        "variable_parts": "镜头距离、人物和场景可以做单变量替换。",
        "misuse": "不要把建议方案写成已经验证的效果。",
        "applicable_objects": ["种草", "挂车成交短视频", "商品页"],
        "must_preserve_tracks": ["视觉", "动作", "字幕"],
        "adaptable_tracks": ["场景", "特效BGM"],
        "validation_status": "suggested_untested",
        "boundary": "仅为待验证的感知化假设。",
        "external_priority": priority,
    }


def populate_expression(delivery: Path) -> None:
    data = delivery / "data"
    manifest = read_json(data / "expression_manifest.json")
    manifest.update(
        {
            "analysis_status": "partial",
            "delivery_status": "conditional",
            "limitations": ["当前只有公开商品页资料。", "所有新增呈现均为未测试建议。"],
            "updated_at": now_iso(),
        }
    )
    write_json(data / "expression_manifest.json", manifest)
    existing = read_jsonl(data / "existing_expression_ledger.jsonl")
    existing[0].update(
        {
            "value_ids": ["V-001"],
            "page_shows": "商品正面和使用场景。",
            "current_perception": "能识别商品，但核心体验还不够具体。",
            "reusable": "商品正面识别。",
            "gap": "缺少完整动作和真实声音。",
            "status": "page_existing_unvalidated",
        }
    )
    existing.append(
        {
            "expression_id": "PEX-001",
            "expression_origin": "source_material",
            "source_form": "detail_page",
            "value_ids": ["V-001"],
            "fact_ids": ["F-001"],
            "source_statement": "详情页以商品正面和透明杯展示当前饮品。",
            "source_id": "SOURCE-MATERIAL-001",
            "locator": "详情页第1页",
            "page_says": "每瓶300毫升。",
            "page_shows": "商品正面与透明杯同框。",
            "current_perception": "能看懂商品和单瓶规格。",
            "reusable": "商品正面与透明杯同框。",
            "gap": "尚未验证表达效果。",
            "status": "page_existing_unvalidated",
            "boundary": "只表示页面采用过该表达，不代表已经有效。",
        }
    )
    write_jsonl(data / "existing_expression_ledger.jsonl", existing)
    write_jsonl(data / "six_path_ledger.jsonl", route_rows())

    applicable = {"05": ["VIS-001"], "09": ["VIS-002"], "12": ["VIS-003"]}
    slot_names = {
        "01": "结构与内容物", "02": "商品识别", "03": "规格数量", "04": "制造过程",
        "05": "核心感官", "06": "使用动作", "07": "前后状态", "08": "局部细节",
        "09": "证据与参数", "10": "品牌信任", "11": "选款确认", "12": "场景与氛围",
    }
    slots = []
    for number in (f"{index:02d}" for index in range(1, 13)):
        slots.append(
            {
                "slot_id": f"SLOT-{number}",
                "slot_number": number,
                "asset_group": "欲望建立" if int(number) <= 8 else "阻力解除" if int(number) <= 11 else "氛围连接",
                "slot_name": slot_names[number],
                "status": "applicable" if number in applicable else "not_applicable",
                "reason": "当前价值与资料支持该槽位。" if number in applicable else "当前没有足够事实支持，保留为不适用。",
                "vis_ids": applicable.get(number, []),
            }
        )
    write_jsonl(data / "slot_scan_ledger.jsonl", slots)
    write_jsonl(
        data / "vis_ledger.jsonl",
        [
            vis_row("VIS-001", "V-001", "05", "欲望建立", "感官化", ["情境化", "差异化"], 1),
            vis_row("VIS-002", "V-002", "09", "阻力解除", "数字化", ["情境化"], 2),
            vis_row("VIS-003", "V-003", "12", "氛围连接", "证据化", ["数字化"], 3),
        ],
    )
    write_jsonl(
        data / "validation_ledger.jsonl",
        [
            {
                "test_id": "TEST-001",
                "vis_ids": ["VIS-001"],
                "validation_task": "比较两种气泡呈现动作是否更容易被用户复述。",
                "must_keep": "商品、核心事实、字幕和发布条件保持一致。",
                "single_variable": "只改变开瓶近景与倒入杯中近景。",
                "control_version": "对照版使用开瓶近景。",
                "test_version": "测试版使用倒入杯中近景。",
                "primary_metrics": ["前5秒留存", "评论中的气泡感复述"],
                "measurement_method": "分别读取两版前5秒留存；在相同观察窗口内独立编码评论是否复述气泡感。",
                "decision_rule": "先比较同口径留存，再单独比较评论复述；样本不足时只记录方向，不升级资产状态。",
                "writeback": "将结果回写为候选、已验证或不建议误用。",
                "status": "suggested",
                "requirements": "需要两条同条件真实素材及同口径观察窗口。",
                "boundary": "未执行前不设置效果结论或虚假阈值。",
            }
        ],
    )
    write_jsonl(
        data / "gap_ledger.jsonl",
        [
            {
                "gap_id": "GAP-001",
                "category": "执行证据",
                "missing": "真实动作、声音和对应数据",
                "impact": "当前只能形成未测试的呈现建议",
                "minimum_needed": "补充同条件素材、数据和评论观察窗口",
                "priority": "high",
                "state": "open",
            }
        ],
    )


def run_test() -> None:
    test_parent = Path.cwd() / "_skill_test_artifacts"
    test_parent.mkdir(parents=True, exist_ok=True)
    temp_root = test_parent / f"brandbai-value-expression-{uuid.uuid4().hex}"
    temp_root.mkdir()
    try:
        upstream = make_product_value_delivery(temp_root)
        delivery = temp_root / "value-expression"
        source_material = temp_root / "source-material.pdf"
        source_material.write_bytes(b"synthetic source material")
        plan = build_plan(delivery, upstream, source_material, "V2")
        assert plan["dry_run"] is True
        assert plan["output_version"] == "V2"
        assert plan["value_expression_id"] == value_expression_id("PV-0123456789ab", "V2")
        assert not delivery.exists(), "dry-run 不得创建交付目录"
        try:
            build_plan(delivery, upstream, source_material, "V0")
            raise AssertionError("非法 output_version 应被拒绝")
        except ValueError as exc:
            assert "output_version" in str(exc)
        init_delivery(delivery, upstream, source_material, "V2")
        initialized_manifest = read_json(delivery / "data" / "expression_manifest.json")
        assert initialized_manifest["output_version"] == "V2"
        assert initialized_manifest["value_expression_id"] == value_expression_id("PV-0123456789ab", "V2")
        populate_expression(delivery)
        dry_run = build_delivery(delivery, write=False)
        assert dry_run["status"] == "dry_run"
        build_delivery(delivery, write=True)
        passed = validate_delivery(delivery)
        assert passed["status"] == "passed", json.dumps(passed, ensure_ascii=False, indent=2)
        report = (delivery / "01_卖点可视化呈现.md").read_text(encoding="utf-8")
        assert "## 3｜核心卖点感知化呈现卡" in report
        assert "VIS-001" not in report and "V-001" not in report

        manifest_path = delivery / "data" / "expression_manifest.json"
        current_manifest = read_json(manifest_path)
        old_manifest = dict(current_manifest)
        old_manifest["schema_version"] = "0.1.0"
        old_manifest["skill_version"] = "0.1.1"
        write_json(manifest_path, old_manifest)
        failed = validate_delivery(delivery)
        assert any("旧交付需要用当前版本重新初始化" in error for error in failed["errors"])
        assert any("不得用新校验器给旧Skill交付补签" in error for error in failed["errors"])
        write_json(manifest_path, current_manifest)

        mismatched_manifest = dict(current_manifest)
        mismatched_manifest["value_expression_id"] = "VE-000000000000"
        write_json(manifest_path, mismatched_manifest)
        failed = validate_delivery(delivery)
        assert any("product_value_id / output_version 不一致" in error for error in failed["errors"])
        write_json(manifest_path, current_manifest)

        report_path = delivery / "02_资料说明与验证计划.md"
        report_path.write_text(report_path.read_text(encoding="utf-8") + "\n手工补写页面盘点。\n", encoding="utf-8")
        failed = validate_delivery(delivery)
        assert any("与 data 账本不同步" in error for error in failed["errors"])
        build_delivery(delivery, write=True)
        assert validate_delivery(delivery)["status"] == "passed"

        existing_path = delivery / "data" / "existing_expression_ledger.jsonl"
        existing = read_jsonl(existing_path)
        write_jsonl(existing_path, [item for item in existing if item.get("expression_origin") != "source_material"])
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("没有 source_material / PEX" in error for error in failed["errors"])
        write_jsonl(existing_path, existing)
        build_delivery(delivery, write=True)
        assert validate_delivery(delivery)["status"] == "passed"

        contradictory_existing = json.loads(json.dumps(existing, ensure_ascii=False))
        contradictory_existing[-1]["page_shows"] = "透明亚克力展架中的页面报告截图。"
        scans_path = delivery / "data" / "six_path_ledger.jsonl"
        original_scans = read_jsonl(scans_path)
        contradictory_scans = json.loads(json.dumps(original_scans, ensure_ascii=False))
        contradictory_scans[0]["boundary"] = "不得虚构透明亚克力展架、报告翻页等实际不存在的素材。"
        write_jsonl(existing_path, contradictory_existing)
        write_jsonl(scans_path, contradictory_scans)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("不得同时把它写成实际不存在" in error for error in failed["errors"])
        write_jsonl(existing_path, existing)
        write_jsonl(scans_path, original_scans)
        build_delivery(delivery, write=True)
        assert validate_delivery(delivery)["status"] == "passed"

        vis_path = delivery / "data" / "vis_ledger.jsonl"
        vis = read_jsonl(vis_path)
        original_vis = json.loads(json.dumps(vis, ensure_ascii=False))

        vis[2]["external_priority"] = None
        write_jsonl(vis_path, vis)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("核心呈现卡必须各覆盖一个主价值" in error for error in failed["errors"])

        vis = json.loads(json.dumps(original_vis, ensure_ascii=False))
        vis[0]["human_language"] = "一箱可以喝整周。"
        write_jsonl(vis_path, vis)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("使用周期缺少上游事实支持" in error for error in failed["errors"])

        vis = json.loads(json.dumps(original_vis, ensure_ascii=False))
        vis[0]["fact_ids"] = ["F-002"]
        vis[0]["subtitle_track"] = "单位μg/g，限值10，结果ND。"
        write_jsonl(vis_path, vis)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("未核验的精确字段" in error for error in failed["errors"])

        vis = json.loads(json.dumps(original_vis, ensure_ascii=False))
        vis[0]["fact_ids"] = ["F-002"]
        vis[0]["visual_track"] = "展示检测报告原件并停在ND一行。"
        write_jsonl(vis_path, vis)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("称为原件" in error for error in failed["errors"])

        vis = json.loads(json.dumps(original_vis, ensure_ascii=False))
        vis[0]["user_question"] = "打开一包能否同时看到全部五味内容物？"
        write_jsonl(vis_path, vis)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("单包内容物" in error for error in failed["errors"])

        write_jsonl(vis_path, original_vis)
        validation_path = delivery / "data" / "validation_ledger.jsonl"
        validations = read_jsonl(validation_path)
        original_validations = json.loads(json.dumps(validations, ensure_ascii=False))
        validations[0]["validation_task"] = "只把上下分屏顺序互换。"
        validations[0]["single_variable"] = "只改左右分屏顺序。"
        write_jsonl(validation_path, validations)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("方向描述不一致" in error for error in failed["errors"])

        validations = json.loads(json.dumps(original_validations, ensure_ascii=False))
        validations[0]["primary_metrics"] = ["前5秒留存的评论复述比例"]
        write_jsonl(validation_path, validations)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("不可直接观测" in error for error in failed["errors"])

        validations = json.loads(json.dumps(original_validations, ensure_ascii=False))
        validations[0]["single_variable"] = "是否包含详情页截图作为证据画面"
        validations[0]["control_version"] = "对照版字幕写'原生味'，不出现详情页截图。"
        validations[0]["test_version"] = "测试版字幕写'无熏硫 原生味'，出现详情页截图。"
        write_jsonl(validation_path, validations)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("不得同时改变字幕" in error for error in failed["errors"])

        validations = json.loads(json.dumps(original_validations, ensure_ascii=False))
        validations[0]["validation_task"] = "比较两种方式对一包全部内容物证明的影响。"
        validations[0]["single_variable"] = "是否连续展示当前SKU单包全部内容物。"
        validations[0]["control_version"] = "对照版采用预先摆盘展示五种原料。"
        validations[0]["test_version"] = "测试版采用当前SKU单包连续倒出全部内容物。"
        validations[0]["primary_metrics"] = ["评论中的一包全部内容物复述"]
        write_jsonl(validation_path, validations)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("不得使用预摆盘" in error for error in failed["errors"])

        validations = json.loads(json.dumps(original_validations, ensure_ascii=False))
        validations[0]["decision_rule"] = "不达样本显著性不升级。"
        write_jsonl(validation_path, validations)
        build_delivery(delivery, write=True)
        failed = validate_delivery(delivery)
        assert any("没有登记样本量或统计检验方法" in error for error in failed["errors"])

        write_jsonl(validation_path, original_validations)
        write_jsonl(vis_path, original_vis)
        build_delivery(delivery, write=True)
        vis = read_jsonl(vis_path)
        original_sound = vis[0].pop("sound_track")
        write_jsonl(vis_path, vis)
        failed = validate_delivery(delivery)
        assert failed["status"] == "failed"
        assert any("sound_track" in error for error in failed["errors"])
        vis[0]["sound_track"] = original_sound
        write_jsonl(vis_path, vis)
        assert validate_delivery(delivery)["status"] == "passed"
        print("value-expression synthetic tests passed")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
        try:
            test_parent.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    run_test()
