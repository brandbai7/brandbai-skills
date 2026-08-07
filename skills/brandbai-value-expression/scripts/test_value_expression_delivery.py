"""Synthetic end-to-end tests for BrandBAI Value Expression."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from build_value_expression_report import build_delivery
from init_value_expression_delivery import build_plan, init_delivery
from validate_value_expression_delivery import validate_delivery
from value_expression_common import ROUTES, now_iso, read_json, read_jsonl, write_json, write_jsonl


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
                "primary_metrics": ["前5秒留存", "评论中的气泡感复述"],
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
        plan = build_plan(delivery, upstream, None)
        assert plan["dry_run"] is True
        assert not delivery.exists(), "dry-run 不得创建交付目录"
        init_delivery(delivery, upstream, None)
        populate_expression(delivery)
        dry_run = build_delivery(delivery, write=False)
        assert dry_run["status"] == "dry_run"
        build_delivery(delivery, write=True)
        passed = validate_delivery(delivery)
        assert passed["status"] == "passed", json.dumps(passed, ensure_ascii=False, indent=2)
        report = (delivery / "01_卖点可视化呈现.md").read_text(encoding="utf-8")
        assert "## 3｜核心卖点感知化呈现卡" in report
        assert "VIS-001" not in report and "V-001" not in report

        vis_path = delivery / "data" / "vis_ledger.jsonl"
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
