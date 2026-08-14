"""Build ordinary Markdown reports from BrandBAI Value Expression ledgers."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from value_expression_common import bullet_lines, delivery_paths, md, read_json, read_jsonl, write_text


ANALYSIS_LABELS = {
    "draft": "工作中", "complete": "当前完成", "partial": "部分完成",
    "insufficient": "资料不足", "stale": "上游变化，当前失效",
}
DELIVERY_LABELS = {
    "ready": "可正式调用", "conditional": "有条件调用",
    "blocked": "暂不可调用", "stale": "停止调用",
}
LAYER_LABELS = {"P0": "核心价值 P0", "P1": "购买支撑 P1", "P2": "信任与买前确认 P2", "deferred": "暂缓"}
ROLE_LABELS = {
    "primary": "主路径", "supporting": "辅助路径",
    "not_prioritized": "本轮不优先", "not_applicable": "不适用",
}
VIS_STATUS_LABELS = {
    "page_existing_unvalidated": "页面已有／未验证",
    "suggested_untested": "建议假设／未测试",
    "candidate": "候选资产",
    "validated": "已验证资产",
    "blocked": "暂不可用",
    "stale": "已失效",
}
TEST_STATUS_LABELS = {
    "suggested": "建议验证", "ready": "可执行", "running": "验证中",
    "completed": "已完成", "blocked": "待补输入", "stale": "已失效",
}
SLOT_STATUS_LABELS = {"applicable": "适用", "not_applicable": "不适用"}


def load_delivery(delivery: Path) -> dict[str, Any]:
    paths = delivery_paths(delivery.resolve())
    return {
        "paths": paths,
        "manifest": read_json(paths["manifest"]),
        "upstream": read_json(paths["upstream"]),
        "existing": read_jsonl(paths["existing"]),
        "scans": read_jsonl(paths["paths"]),
        "slots": read_jsonl(paths["slots"]),
        "vis": read_jsonl(paths["vis"]),
        "validations": read_jsonl(paths["validation"]),
        "gaps": read_jsonl(paths["gaps"]),
    }


def value_map(upstream: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("value_id", "")): item
        for item in upstream.get("values", [])
        if isinstance(item, dict) and item.get("value_id")
    }


def selected_vis(vis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen = [item for item in vis if isinstance(item.get("external_priority"), int)]
    if chosen:
        return sorted(chosen, key=lambda item: int(item["external_priority"]))[:5]
    return vis[:5]


def value_label(item: dict[str, Any]) -> str:
    return LAYER_LABELS.get(str(item.get("layer", "")), str(item.get("layer", "")))


def existing_text(
    expression_ids: list[str],
    fact_ids: list[str],
    existing: dict[str, dict[str, Any]],
    facts: dict[str, dict[str, Any]],
) -> str:
    parts = [existing[item].get("page_says", "") for item in expression_ids if item in existing]
    if not parts:
        parts = [facts[item].get("statement", "") for item in fact_ids if item in facts and facts[item].get("fact_type") == "F-PAGE"][:2]
    parts = [str(item).strip().rstrip("。；;") for item in parts if str(item).strip()]
    return "；".join(parts) if parts else "当前价值底座已确认相关事实，但没有单独登记可直接复用的传播原话"


def perceptions_for_object(vis: list[dict[str, Any]], object_name: str) -> str:
    rows = [item for item in vis if object_name in item.get("applicable_objects", [])]
    rows = sorted(rows, key=lambda item: (item.get("external_priority") is None, item.get("external_priority") or 99))
    values = [str(item.get("human_language", "")).strip() for item in rows[:3] if str(item.get("human_language", "")).strip()]
    return "；".join(values) if values else "当前没有可调用呈现，需先补齐感知资产"


def build_report_01(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    upstream = data["upstream"]
    values = value_map(upstream)
    existing = {str(item.get("expression_id", "")): item for item in data["existing"]}
    facts = {
        str(item.get("fact_id", "")): item
        for item in upstream.get("facts", [])
        if isinstance(item, dict) and item.get("fact_id")
    }
    vis = data["vis"]
    chosen = selected_vis(vis)
    vis_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in vis:
        vis_by_value[str(item.get("value_id", ""))].append(item)
    ordered_values = sorted(
        [item for item in values.values() if item.get("layer") in {"P0", "P1", "P2"} and item.get("downstream_readiness") != "blocked"],
        key=lambda item: ({"P0": 0, "P1": 1, "P2": 2}.get(str(item.get("layer", "")), 9), str(item.get("value_id", ""))),
    )
    lines = [
        f"# 卖点可视化呈现｜{manifest.get('brand', '')} {manifest.get('product', '')}",
        "",
        "> 怎么拍、怎么演、怎么让用户真正感受到",
        "",
        f"- 当前 SKU/版本：{md(manifest.get('sku'))}",
        f"- 上游商品价值版本：{md(manifest.get('upstream_output_version'))}",
        f"- 当前状态：{ANALYSIS_LABELS.get(manifest.get('analysis_status'), md(manifest.get('analysis_status')))}",
        f"- 调用状态：{DELIVERY_LABELS.get(manifest.get('delivery_status'), md(manifest.get('delivery_status')))}",
        "- 说明：本文件只把既有商品价值翻译成感知呈现，不重新选择核心价值，也不直接生成完整脚本。",
        "",
        "## 1｜卖点感知化总览",
        "",
        "| 商品价值 | 用户要具体感受到什么 | 核心呈现方式 | 当前状态 |",
        "|---|---|---|---|",
    ]
    for value in ordered_values:
        value_id = str(value.get("value_id", ""))
        expressions = vis_by_value.get(value_id, [])
        first = sorted(expressions, key=lambda item: (item.get("external_priority") is None, item.get("external_priority") or 99))[0] if expressions else {}
        lines.append(
            f"| {md(value_label(value))}｜{md(value.get('value_statement'))} | {md(first.get('target_perception'), value.get('user_perception_goal', '未形成可调用感知'))} | {md(first.get('primary_route'))} + {md(first.get('supporting_routes'))} | {VIS_STATUS_LABELS.get(first.get('validation_status'), '待形成呈现')} |"
        )

    lines.extend([
        "",
        "## 2｜品牌语言翻译为用户语言",
        "",
        "| 品牌／详情页怎么说 | 用户真正想知道什么 | 用户能听懂、能复述的话 |",
        "|---|---|---|",
    ])
    for item in chosen:
        source = existing_text(
            list(map(str, item.get("expression_ids", []))),
            list(map(str, item.get("fact_ids", []))),
            existing,
            facts,
        )
        lines.append(f"| {md(source)} | {md(item.get('user_question'))} | {md(item.get('human_language'))} |")

    lines.extend(["", "## 3｜核心卖点感知化呈现卡", ""])
    if not chosen:
        lines.append("当前没有可对外调用的核心呈现资产。")
    for index, item in enumerate(chosen, start=1):
        value = values.get(str(item.get("value_id", "")), {})
        lines.extend([
            f"### 呈现卡{index}｜{md(item.get('human_language'))}",
            "",
            f"- 对应商品价值：{md(value_label(value))}｜{md(value.get('value_statement'))}",
            f"- 用户感知任务：{md(item.get('decision_task'))}｜{md(item.get('target_perception'))}",
            f"- 主翻译路径：{md(item.get('primary_route'))}",
            f"- 辅助路径：{md(item.get('supporting_routes'))}",
            f"- 画面：{md(item.get('visual_track'))}",
            f"- 动作：{md(item.get('action_track'))}",
            f"- 声音：{md(item.get('sound_track'))}",
            f"- 字幕：{md(item.get('subtitle_track'))}",
            f"- 道具：{md(item.get('prop_track'))}",
            f"- 场景与人物状态：{md(item.get('scene_track'))}",
            f"- 特效／BGM：{md(item.get('effect_bgm_track'))}",
            f"- 商品／包装／商品页承接：{md(item.get('commerce_handoff_track'))}",
            f"- 必须保留：{md(item.get('must_keep'))}",
            f"- 可变部分：{md(item.get('variable_parts'))}",
            f"- 不建议误用：{md(item.get('misuse'))}",
            f"- 适用经营对象：{md(item.get('applicable_objects'))}",
            f"- 当前验证状态：{VIS_STATUS_LABELS.get(item.get('validation_status'), md(item.get('validation_status')))}",
            f"- 表达边界：{md(item.get('boundary'))}",
            "",
        ])

    p0_vis = [item for item in chosen if values.get(str(item.get("value_id", "")), {}).get("layer") == "P0"]
    p1_vis = [item for item in chosen if values.get(str(item.get("value_id", "")), {}).get("layer") == "P1"]
    p2_vis = [item for item in chosen if values.get(str(item.get("value_id", "")), {}).get("layer") == "P2"]
    def first_language(rows: list[dict[str, Any]], fallback: str) -> str:
        return str(rows[0].get("human_language", "")) if rows else fallback

    lines.extend([
        "## 4｜内容功能位置怎么调用",
        "",
        "本表只说明呈现资产可以承担什么功能，不代表固定播放顺序，也不是完整内容信息链。",
        "",
        "| 功能位置 | 作用 | 当前可调用方式 |",
        "|---|---|---|",
        f"| 注意入口 | 让用户停下并知道内容与自己有关 | 用真实触发场景承接“{md(first_language(p0_vis, '核心价值待形成呈现'))}”，具体入口仍需账号与人群输入 |",
        "| 商品识别 | 让用户知道卖的是什么 | 调用商品全貌、一级识别锚与当前SKU，不让包装符号替代核心价值 |",
        f"| 卖点感知 | 让用户真正看懂并感受到核心价值与购买支撑 | 核心调用“{md(first_language(p0_vis, '核心价值待形成呈现'))}”；辅助调用“{md(first_language(p1_vis, '购买支撑待形成呈现'))}” |",
        f"| 信任与选款 | 处理疑问、证据和适用边界 | 调用“{md(first_language(p2_vis, '信任资产待形成呈现'))}”，证据只回答对应顾虑 |",
        "| 价值与行动 | 让用户知道为什么继续了解或购买 | 只能在SKU、入口、权益和下一触点确认后组装，不在本阶段生成CTA |",
        "| 预期管理 | 保证商品、规格、权益与实际到手一致 | 使用商品身份、规格、适用边界和当前有效交易信息；动态字段必须带时点 |",
        "",
        "## 5｜五大作业对象调用地图",
        "",
        "| 作业对象 | 卖点呈现重点 | 当前可调用资产 | 执行条件 |",
        "|---|---|---|---|",
    ])
    object_focus = {
        "种草": "场景、自我相关、生活状态和自然植入",
        "直播引流短视频": "进房理由与直播可继续承接的问题",
        "挂车成交短视频": "商品识别、价值感知、价值权衡和行动收口",
        "直播间": "真实动作演示、评论答疑和商品卡同步",
        "商品页": "主图、动图、标题、SKU、证据和信息顺序",
    }
    for object_name, focus in object_focus.items():
        lines.append(f"| {object_name} | {focus} | {md(perceptions_for_object(vis, object_name))} | 待确认具体人群、任务、账号／载体与交易承接后再编排 |")

    lines.extend([
        "",
        "## 6｜第一轮内容验证",
        "",
        "当前只输出建议验证任务；未提供真实业务输入、样本量和历史基线时，不设置虚假阈值和正式执行话术。",
        "",
        "| 验证任务 | 对照版 | 测试版 | 必须保留 | 唯一变量 | 指标与获取方式 | 判断与回写 | 当前状态 |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for item in data["validations"][:3]:
        lines.append(
            f"| {md(item.get('validation_task'))} | {md(item.get('control_version'))} | {md(item.get('test_version'))} | {md(item.get('must_keep'))} | {md(item.get('single_variable'))} | {md(item.get('primary_metrics'))}；{md(item.get('measurement_method'))} | {md(item.get('decision_rule'))}；{md(item.get('writeback'))} | {TEST_STATUS_LABELS.get(item.get('status'), md(item.get('status')))} |"
        )
    if not data["validations"]:
        lines.append("| 尚未形成验证任务 | 待定义 | 待定义 | 当前商品与核心价值不变 | 待业务目标确定后只选择一个主变量 | 按真实经营任务确定 | 回写候选／已验证资产 | 待补输入 |")

    lines.extend([
        "",
        "## 7｜资产回写闭环",
        "",
        "```text",
        "前置感知化假设",
        "→ 真实内容执行",
        "→ 数据与评论对位",
        "→ 已验证／候选呈现组合",
        "→ 必须保留／可变／待补强／不建议误用",
        "→ 下一轮执行卡",
        "```",
        "",
        "页面出现过只能说明品牌使用了某种表达，不能证明这种表达有效。只有真实素材、页面版本或直播演示与对应数据、评论和观察窗口对位后，才能升级为已验证资产。",
        "",
        "## 8｜当前边界与下一步",
        "",
        "### 当前边界",
        "",
        bullet_lines(manifest.get("limitations", []), "暂无额外边界"),
        "",
        "### 优先补充",
        "",
        bullet_lines([f"{item.get('missing')}；最低需要：{item.get('minimum_needed')}" for item in data["gaps"] if item.get("priority") == "high"][:5], "暂无高优先级缺口"),
        "",
        "### 下一步",
        "",
        "- 现在可以：把本报告中的原子呈现作为条件式素材库，用于讨论怎么让商品价值被看见、听见和理解。",
        "- 暂时不要：直接把呈现卡按顺序拼成脚本、指定达人原话、调用过期权益或声称某种呈现已经有效。",
        "- 补齐后产出：通过真实业务输入门后再组装具体内容；通过执行与数据对位后再做资产回写。",
    ])
    return "\n".join(lines)


def build_report_02(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    upstream = data["upstream"]
    values = value_map(upstream)
    vis_map = {str(item.get("vis_id", "")): item for item in data["vis"]}
    scans_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in data["scans"]:
        scans_by_value[str(item.get("value_id", ""))].append(item)
    lines = [
        f"# {manifest.get('brand', '')}｜{manifest.get('product', '')} 资料说明与验证计划",
        "",
        "## 商品与上游版本",
        "",
        f"- 商品：{md(manifest.get('brand'))} {md(manifest.get('product'))}",
        f"- 品类：{md(manifest.get('category'))}",
        f"- 当前 SKU/版本：{md(manifest.get('sku'))}",
        f"- 商品价值底座版本：{md(manifest.get('upstream_output_version'))}",
        f"- 补充商品素材：{md(manifest.get('source_materials'), '未提供')}",
        f"- 当前状态：{ANALYSIS_LABELS.get(manifest.get('analysis_status'), md(manifest.get('analysis_status')))}",
        f"- 调用状态：{DELIVERY_LABELS.get(manifest.get('delivery_status'), md(manifest.get('delivery_status')))}",
        "",
        "本次卖点呈现继承上游商品、SKU、价值分层、核心价值状态与表达边界，没有重新选择核心价值。",
        "",
        "## 页面已有呈现盘点",
        "",
        "| 页面已经怎么说 | 页面已经怎么拍 | 用户当前能感知到什么 | 可直接复用点 | 沟通缺口 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for item in data["existing"]:
        lines.append(
            f"| {md(item.get('page_says'))} | {md(item.get('page_shows'))} | {md(item.get('current_perception'))} | {md(item.get('reusable'))} | {md(item.get('gap'))} | {md(item.get('status'))} |"
        )
    if not data["existing"]:
        lines.append("| 当前上游未登记页面原话 | 未盘点 | 未判断 | 无 | 需要补充可读页面或商品素材 | 待补输入 |")

    lines.extend([
        "",
        "## 六条翻译路径扫描",
        "",
        "每个准备沟通的商品价值都必须扫描六条路径；没有选中的路径也保留本轮不优先或不适用的理由。",
        "",
        "| 商品价值 | 路径 | 当前角色 | 具体翻译 | 选择理由与边界 |",
        "|---|---|---|---|---|",
    ])
    for value_id, rows in scans_by_value.items():
        value = values.get(value_id, {})
        for item in rows:
            lines.append(
                f"| {md(value_label(value))}｜{md(value.get('value_statement'))} | {md(item.get('route'))} | {ROLE_LABELS.get(item.get('role'), md(item.get('role')))} | {md(item.get('translation'))} | {md(item.get('reason'))}；{md(item.get('boundary'))} |"
            )

    lines.extend([
        "",
        "## 十二类感知原子完整性扫描",
        "",
        "| 槽位 | 资产职责 | 当前判断 | 已形成的感知方式 | 判断理由 |",
        "|---|---|---|---|---|",
    ])
    for item in sorted(data["slots"], key=lambda row: str(row.get("slot_number", ""))):
        perceptions = [vis_map[vis_id].get("human_language", "") for vis_id in item.get("vis_ids", []) if vis_id in vis_map]
        lines.append(
            f"| {md(item.get('slot_number'))} {md(item.get('slot_name'))} | {md(item.get('asset_group'))} | {SLOT_STATUS_LABELS.get(item.get('status'), md(item.get('status')))} | {md(perceptions, '无')} | {md(item.get('reason'))} |"
        )

    lines.extend([
        "",
        "## 当前可以做",
        "",
        "- 继承当前有效商品价值，把每个价值翻译成职责单一、五轨完整的感知原子。",
        "- 将公开详情页中与当前商品和SKU明确对应的表达直接用于沟通设计，并保留边界。",
        "- 为种草、直播引流、挂车短视频、直播间和商品页提供条件式调用接口。",
        "- 提出最多3个单变量验证任务，但不伪造样本量、阈值和效果结论。",
        "",
        "## 当前不能做",
        "",
        "- 不能重新选择或改变商品价值底座中的核心价值、购买支撑和信任信息。",
        "- 不能把好拍、显眼、包装漂亮或已有画面多写成核心价值。",
        "- 不能把页面已有表达自动标成有效资产，也不能把建议方案标成真实效果。",
        "- 不能在业务目标、人群、账号／载体和交易承接不完整时生成完整内容方向、钩子、脚本、达人原话或动态CTA。",
        "",
        "## 资料缺口及影响",
        "",
        "| 类别 | 缺少什么 | 影响 | 最低补充 | 优先级 | 状态 |",
        "|---|---|---|---|---|---|",
    ])
    for item in data["gaps"]:
        lines.append(
            f"| {md(item.get('category'))} | {md(item.get('missing'))} | {md(item.get('impact'))} | {md(item.get('minimum_needed'))} | {md(item.get('priority'))} | {md(item.get('state'))} |"
        )
    if not data["gaps"]:
        lines.append("| 暂无 | 暂无新增缺口 | 按现有边界调用 | 如上游或业务输入变化再补充 | 低 | 关闭 |")

    lines.extend([
        "",
        "## 版本与失效规则",
        "",
        f"- 当前商品价值底座更新时间：{md(upstream.get('upstream_updated_at'))}",
        f"- 当前卖点呈现更新时间：{md(manifest.get('updated_at'))}",
        "- 商品、SKU、标准成交单元、事实版本或核心价值变化时，本版自动停止调用并重新生成。",
        "- 页面新增表达先回到上游登记事实或页面表达，再更新六路扫描和受影响的感知资产；无关资产不重写。",
        "- 真实内容、页面版本或直播数据回来后，应进入资产回写流程，区分已验证、候选、待补强和不建议误用。",
    ])
    return "\n".join(lines)


def build_delivery(delivery: Path, write: bool) -> dict[str, Any]:
    delivery = delivery.resolve()
    data = load_delivery(delivery)
    report_01 = build_report_01(data)
    report_02 = build_report_02(data)
    if write:
        write_text(data["paths"]["report_01"], report_01)
        write_text(data["paths"]["report_02"], report_02)
    return {
        "status": "built" if write else "dry_run",
        "delivery": str(delivery),
        "counts": {
            "existing_expressions": len(data["existing"]),
            "six_path_rows": len(data["scans"]),
            "slot_rows": len(data["slots"]),
            "vis": len(data["vis"]),
            "validation_tasks": len(data["validations"]),
            "gaps": len(data["gaps"]),
        },
        "reports": [str(data["paths"]["report_01"]), str(data["paths"]["report_02"])],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_delivery(args.delivery, write=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
