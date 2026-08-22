"""Build human-readable Product Page reports from the structured delivery ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_page_common import (
    COURSE_REPORT,
    DECISION_NAMES,
    PROFESSIONAL_REPORTS,
    bullet_lines,
    delivery_paths,
    md,
    read_json,
    read_jsonl,
    write_text,
)


RUN_STATUS_LABELS = {
    "ready": "可以正式优化",
    "partial": "部分可优化",
    "degraded_no_product_value": "现有页面诊断",
    "stopped": "暂时无法分析",
}
LEGACY_PROFESSIONAL_REPORT = "02_主图与详情页执行页.md"
SCOPE_LABELS = {
    "main_images": "只看主图",
    "detail_page": "只看详情页",
    "combined": "主图与详情页一起看",
}
TASK_LABELS = {
    "diagnose": "页面诊断",
    "design": "页面设计",
    "route": "页面路由",
    "version_review": "版本对照",
}
RETURN_LABELS = {
    "product_value": "返回商品价值",
    "value_expression": "返回卖点呈现",
    "page_material": "补页面资料",
    "human_confirmation": "需要人工确认",
    "supporting_material": "补充资料后再优化",
}
COURSE_RETURN_LABELS = {
    "product_value": "先回去确认商品本身",
    "value_expression": "先补卖点怎么被看见",
    "page_material": "先补页面资料",
    "human_confirmation": "需要品牌内部确认",
    "supporting_material": "可选补充资料",
}
READABILITY_LABELS = {
    "unreadable": "本轮未读取或不可读",
    "unsupported_archive": "压缩包尚未解压",
    "not_reviewed": "尚未核对",
}
ROUTE_LABELS = {
    "shared_master": "先用一套共用母版",
    "entry_adaptation": "共用一套母版，只改入口首屏",
    "dynamic_sku_adaptation": "共用母版，按已确认条件替换局部模块",
    "standalone_page": "建立独立精细页",
}
COVERAGE_LABELS = {
    "complete_observed": "本次提供范围已逐张看完",
    "partial_observed": "只看完一部分",
    "unknown": "还不能确认是否看全",
    "not_applicable": "本次不看这一部分",
}
CONTENT_LAYER_LABELS = {
    "evergreen_product": "长期商品信息",
    "current_campaign": "当前活动信息",
    "transaction_support": "交易承接信息",
    "trust_and_compliance": "信任与合规信息",
}
COMPONENT_APPLICABILITY_LABELS = {
    "current_sku": "适用于当前SKU",
    "current_bundle_component": "只适用于当前套组中的这个单品",
    "current_product": "当前商品共用信息",
    "selectable_variant": "其他可选规格或变体",
    "entry_specific": "只适用于当前专属入口",
    "related_product": "关联商品",
    "brand_general": "品牌通用信息",
    "unknown": "适用对象不明确",
}
PAGE_ROLE_LABELS = {
    "single_product_page": "单品价值页",
    "selection_hub_page": "多SKU／套组选择页",
    "entry_landing_page": "专属入口承接页",
    "mixed": "多种任务混合页",
    "unknown": "页面角色尚未确认",
}
ENTRY_CONTEXT_BASIS_LABELS = {
    "provided_evidence": "有可靠入口资料",
    "page_visible_inference": "仅依据页面可见信息推断",
    "unknown": "入口依据未知",
}
VARIANT_TYPE_LABELS = {
    "capacity": "容量",
    "quantity": "数量",
    "color_shade": "色号／颜色",
    "flavor": "口味",
    "formula": "配方",
    "life_stage": "阶段／月龄",
    "breed": "适用类型",
    "size": "尺码",
    "bundle": "套组",
    "usage": "使用任务",
    "product_form": "产品形态",
    "package_version": "包装／版本",
    "other": "其他",
}
TRANSACTION_ROLE_LABELS = {
    "standard": "正装主销",
    "trial": "试用装",
    "new_customer": "新客装",
    "refill": "补充装",
    "stock_up": "囤货装",
    "gift": "礼赠装",
    "unknown": "交易角色尚未确认",
}
DECISION_CLOSURE_LABELS = {
    "closed": "当前商品的主要购买判断已经闭合",
    "partially_closed": "已经讲清一部分，但还有关键问题没有闭合",
    "not_closed": "当前商品的主要购买判断还没有闭合",
    "unknown": "资料不足，暂时不能判断是否闭合",
}
ELIGIBILITY_LABELS = {
    "resolved": "页面已经讲清适用对象和使用条件",
    "partially_resolved": "适用对象只讲清一部分",
    "unresolved": "适用对象或使用条件还没有讲清",
    "not_applicable": "本商品不需要单独设置适用对象闸门",
    "unknown": "资料不足，暂时不能判断适用对象",
}


def safe_order(value: Any) -> int:
    if isinstance(value, bool):
        return 10**9
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 10**9


def load_delivery(delivery: Path) -> dict[str, Any]:
    paths = delivery_paths(delivery)
    required = (
        "manifest",
        "upstream",
        "sources",
        "supporting_sources",
        "claims",
        "coverage",
        "components",
        "chain",
        "decisions",
        "actions",
        "validation",
        "gaps",
    )
    missing = [str(paths[name]) for name in required if not paths[name].is_file()]
    if missing:
        raise FileNotFoundError(f"缺少结构化交付文件: {', '.join(missing)}")
    return {
        "manifest": read_json(paths["manifest"]),
        "upstream": read_json(paths["upstream"]),
        "sources": read_jsonl(paths["sources"]),
        "supporting_sources": read_jsonl(paths["supporting_sources"]),
        "claims": read_jsonl(paths["claims"]),
        "coverage": read_jsonl(paths["coverage"]),
        "components": read_jsonl(paths["components"]),
        "chain": read_json(paths["chain"]),
        "decisions": read_jsonl(paths["decisions"]),
        "actions": read_jsonl(paths["actions"]),
        "validation": read_jsonl(paths["validation"]),
        "gaps": read_jsonl(paths["gaps"]),
        "routing": read_json(paths["routing"]) if paths["routing"].is_file() else None,
    }


def readable_scope(sources: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    readable: list[str] = []
    limited: list[str] = []
    for row in sources:
        label = str(row.get("page_location") or row.get("file_name") or "未命名页面")
        status = row.get("readability_status")
        if status == "readable":
            readable.append(label)
        elif status == "partially_readable":
            readable.append(f"{label}（部分可读）")
            limited.append(f"{label} 仅部分可读")
        elif status in {"unreadable", "unsupported_archive", "not_reviewed"}:
            limited.append(f"{label}：{READABILITY_LABELS.get(str(status), '本轮不可用')}")
    return readable, limited


def readable_scope_summary(sources: list[dict[str, Any]]) -> str:
    """Summarize reviewed materials without flooding the human report with every filename."""
    counts = {
        "shelf_entry": 0,
        "main_images": 0,
        "detail_page": 0,
        "other": 0,
    }
    for row in sources:
        if row.get("readability_status") not in {"readable", "partially_readable"}:
            continue
        scope = str(row.get("page_scope", ""))
        key = scope if scope in {"shelf_entry", "main_images", "detail_page"} else "other"
        counts[key] += 1
    labels = (
        ("shelf_entry", "商品资料"),
        ("main_images", "主图"),
        ("detail_page", "详情页"),
        ("other", "其他可读资料"),
    )
    parts = [f"{label}{counts[key]}项" for key, label in labels if counts[key]]
    return "；".join(parts) if parts else "没有确认可读的页面"


def run_decision_summary(manifest: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    status = str(manifest.get("run_status", ""))
    action_count = len(actions)
    if status == "ready":
        return f"本轮可以正式优化；只执行下方{action_count}项优先动作，改完仍需验证。"
    if status == "partial":
        return f"本轮只能有条件优化；只处理下方{action_count}项，不把待验证判断写成已证实结论。"
    if status == "degraded_no_product_value":
        return f"本轮可基于现有页面完成诊断；只执行下方{action_count}项有页面依据的动作，不新增资料外卖点。"
    return "本轮暂停页面优化；先补齐停止原因所对应的最低资料。"


def decision_rows(decisions: list[dict[str, Any]]) -> str:
    by_name = {str(row.get("decision_name", "")): row for row in decisions}
    rows = ["| 用户判断 | 当前状态 | 一句话说明 |", "| --- | --- | --- |"]
    for name in DECISION_NAMES:
        row = by_name.get(name, {})
        rows.append(
            f"| {name} | {md(row.get('status'), '资料不足')} | {md(row.get('summary'), '当前资料不足')} |"
        )
    return "\n".join(rows)


def coverage_rows(coverage: list[dict[str, Any]]) -> str:
    if not coverage:
        return "- 页面覆盖情况尚未登记。"
    scope_labels = {"main_images": "主图", "detail_page": "详情页"}
    version_labels = {"current": "当前版", "comparison": "对照版"}
    lines: list[str] = []
    for item in coverage:
        label = f"{version_labels.get(str(item.get('source_version')), md(item.get('source_version')))}{scope_labels.get(str(item.get('scope')), md(item.get('scope')))}"
        count = item.get("page_declared_count")
        declared = "页面总数未知" if count == "unknown" else f"页面标明或资料包应有 {md(count)} 项"
        lines.append(
            f"- {label}：{COVERAGE_LABELS.get(str(item.get('coverage_status')), md(item.get('coverage_status')))}；"
            f"已登记 {md(item.get('observed_source_count'), '0')} 项，{declared}；"
            f"说明：{md(item.get('basis'))}"
        )
    return "\n".join(lines)


def action_rows(actions: list[dict[str, Any]], course: bool) -> str:
    ordered = sorted(actions, key=lambda item: safe_order(item.get("priority")))
    if not ordered:
        return "当前依据不足或没有高优先动作，本轮不强行凑数。"
    if course:
        sections: list[str] = []
        for item in ordered:
            label = str(item.get("recommendation_label", "")).strip() or (
                "补充资料后优化" if item.get("action_type") == "人工核实" else "可直接优化"
            )
            needed = "；".join(
                value.rstrip("。；; ") for value in (
                    str(item.get("material_needed", "")).strip(),
                    str(item.get("human_confirmation", "")).strip(),
                ) if value
            )
            sections.extend(
                [
                    f"### 优先 {md(item.get('priority'))}｜{md(item.get('page_location'))}（{md(item.get('decision_name'))}）",
                    "",
                    f"- 建议标签：{md(label)}",
                    f"- 现在的问题：{md(item.get('gap_or_risk'))}",
                    f"- 为什么这样判断：{md(item.get('basis_summary'))}",
                    f"- 这一轮怎么改：{md(item.get('action_type'))}——{md(item.get('action_detail'))}",
                    f"- 必须保留：{md(item.get('must_preserve'))}",
                    f"- 还要补充或确认：{md(needed, '暂无')}",
                    f"- 改完怎么检查：{md(item.get('acceptance_check'))}",
                    "",
                ]
            )
        return "\n".join(sections).rstrip()
    sections: list[str] = []
    for item in ordered:
        label = str(item.get("recommendation_label", "")).strip() or (
            "补充资料后优化" if item.get("action_type") == "人工核实" else "可直接优化"
        )
        sections.extend(
            [
                f"### 优先动作 {md(item.get('priority'))}｜{md(item.get('page_location'))}",
                "",
                f"- 用户判断：{md(item.get('decision_name'))}",
                f"- 建议标签：{md(label)}",
                f"- 当前观察：{md(item.get('current_observation'))}",
                f"- 缺口或风险：{md(item.get('gap_or_risk'))}",
                f"- 调用依据：{md(item.get('basis_summary'))}",
                f"- 动作：{md(item.get('action_type'))}——{md(item.get('action_detail'))}",
                f"- 必须保留：{md(item.get('must_preserve'))}",
                f"- 所需素材：{md(item.get('material_needed'))}",
                f"- 人工确认：{md(item.get('human_confirmation'))}",
                f"- 验收问题：{md(item.get('acceptance_check'))}",
                f"- 下一轮验证：{md(item.get('validation_question'))}",
                "- 当前状态：待验证建议",
                "",
            ]
        )
    return "\n".join(sections).rstrip()


def gap_sections(gaps: list[dict[str, Any]], course: bool = False) -> str:
    open_gaps = [item for item in gaps if item.get("state") != "closed"]
    if not open_gaps:
        return "- 当前没有新增的开放缺口。"
    lines: list[str] = []
    labels = COURSE_RETURN_LABELS if course else RETURN_LABELS
    for target in (
        "product_value", "value_expression", "page_material",
        "supporting_material", "human_confirmation",
    ):
        items = [item for item in open_gaps if item.get("return_to") == target]
        if not items:
            continue
        lines.append(f"### {labels[target]}")
        lines.append("")
        for item in items:
            lines.append(
                f"- {md(item.get('missing'))}；影响：{md(item.get('impact'))}；最低需要：{md(item.get('minimum_needed'))}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def base_header(
    manifest: dict[str, Any],
    sources: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> str:
    readable, limited = readable_scope(sources)
    cross_surface = manifest.get("cross_surface_summary")
    if cross_surface == "not_applicable":
        cross_surface = "不适用（本次只看单一页面范围）"
    snapshot_time = str(manifest.get("page_snapshot_time", "")).strip()
    if snapshot_time in {"", "unknown"}:
        snapshot_time = "时间未知"
    return "\n".join(
        [
            f"- 商品：{md(manifest.get('brand'))} {md(manifest.get('product'))}",
            f"- SKU／规格：{md(manifest.get('sku'))}",
            f"- 页面范围：{SCOPE_LABELS.get(str(manifest.get('scope')), md(manifest.get('scope')))}",
            f"- 本次任务：{TASK_LABELS.get(str(manifest.get('task')), md(manifest.get('task')))}",
            f"- 页面版本或截图时间：{md(snapshot_time)}",
            f"- 分析状态：{RUN_STATUS_LABELS.get(str(manifest.get('run_status')), md(manifest.get('run_status')))}",
            f"- 跨触点一致性：{md(cross_surface, '尚未完成')}",
            f"- 已读范围：{readable_scope_summary(sources)}（逐项来源与哈希保留在内部底稿）",
            f"- 已提供文件中的未读或受限：{md(limited, '暂无（不代表整页资料完整）')}",
            "- 页面是否看全：见下方覆盖说明；没有确认看全时，只能判断已读范围。",
            coverage_rows(coverage),
        ]
    )


def course_header(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    chain = data["chain"]
    closure = chain.get("decision_closure", {})
    eligibility = chain.get("eligibility_gate", {})
    transaction = chain.get("current_transaction", {})
    precompleted = chain.get("precompleted_decisions", [])
    remaining = chain.get("remaining_decision_tasks", [])
    selection_order = transaction.get("selection_dimension_order", [])
    raw_spec_groups = transaction.get("raw_spec_groups", [])
    bundle_contents = transaction.get("bundle_contents", [])
    bundle_text = "；".join(
        f"{md(item.get('item_name'))} {md(item.get('variant_or_version'))} {md(item.get('quantity_or_size'))}"
        for item in bundle_contents
        if isinstance(item, dict)
    ) or ("套组构成尚未确认" if "bundle" in transaction.get("variant_dimensions", []) else "非套组")
    raw_spec_text = "；".join(
        f"{md(item.get('group_name'))}：{md(item.get('current_value'))}（实际包含"
        f"{'、'.join(VARIANT_TYPE_LABELS.get(str(value), str(value)) for value in item.get('normalized_dimensions', [])) or '尚未拆清'}）"
        for item in raw_spec_groups
        if isinstance(item, dict)
    ) or "没有多规格，或平台原始规格组尚未核对"
    cross_surface = manifest.get("cross_surface_summary")
    if cross_surface == "not_applicable":
        cross_surface = "本次只看一个页面范围，不做跨位置比较。"
    snapshot_time = str(manifest.get("page_snapshot_time", "")).strip()
    if snapshot_time in {"", "unknown"}:
        snapshot_time = "时间未知"
    return "\n".join(
        [
            f"- 当前商品：{md(manifest.get('brand'))} {md(manifest.get('product'))}",
            f"- 当前成交规格（SKU）：{md(manifest.get('sku'))}",
            f"- 当前套组／实际到手：{bundle_text}",
            f"- 这张页面主要负责：{PAGE_ROLE_LABELS.get(str(chain.get('page_role')), '页面角色尚未确认')}",
            f"- 页面角色依据：{ENTRY_CONTEXT_BASIS_LABELS.get(str(chain.get('page_role_basis')), '依据未知')}",
            f"- 用户进页前已可靠完成：{'、'.join(map(str, precompleted)) if precompleted else '没有可靠证据表明某项已经完成'}",
            f"- 页面还必须补齐：{'、'.join(map(str, remaining)) if remaining else '尚未确认'}",
            f"- 规格选择顺序：{' → '.join(VARIANT_TYPE_LABELS.get(str(item), str(item)) for item in selection_order) if selection_order else '无多维选择，或顺序尚未确认'}",
            f"- 平台原始规格组：{raw_spec_text}",
            f"- 本次查看：{SCOPE_LABELS.get(str(manifest.get('scope')), md(manifest.get('scope')))}",
            f"- 页面资料时间：{md(snapshot_time)}",
            f"- 已核对：{readable_scope_summary(data['sources'])}",
            coverage_rows(data["coverage"]),
            f"- 当前最大问题：{md(cross_surface, '尚未完成判断')}",
            f"- 页面现在怎么讲：{md(chain.get('dominant_route'), '尚未确认')}",
            f"- 购买判断是否做完：{DECISION_CLOSURE_LABELS.get(str(closure.get('status')), '资料不足')}；{md(closure.get('closure_reason'), '尚未完成判断')}",
            f"- 适用对象是否清楚：{ELIGIBILITY_LABELS.get(str(eligibility.get('status')), '资料不足')}；{md(eligibility.get('target_user_or_object'), '尚未确认')}",
        ]
    )


def chain_summary(chain: dict[str, Any]) -> str:
    transaction = chain.get("current_transaction", {})
    closure = chain.get("decision_closure", {})
    eligibility = chain.get("eligibility_gate", {})
    precompleted = chain.get("precompleted_decisions", [])
    remaining = chain.get("remaining_decision_tasks", [])
    selection_order = transaction.get("selection_dimension_order", [])
    raw_spec_groups = transaction.get("raw_spec_groups", [])
    raw_spec_text = "；".join(
        f"{md(item.get('group_name'))}：{md(item.get('current_value'))}（实际包含"
        f"{'、'.join(VARIANT_TYPE_LABELS.get(str(value), str(value)) for value in item.get('normalized_dimensions', [])) or '尚未拆清'}）"
        for item in raw_spec_groups
        if isinstance(item, dict)
    ) or "没有多规格，或平台原始规格组尚未核对"
    return "\n".join(
        [
            f"- 当前交易角色：{TRANSACTION_ROLE_LABELS.get(str(transaction.get('transaction_role')), md(transaction.get('transaction_role')))}",
            f"- 当前页面角色：{PAGE_ROLE_LABELS.get(str(chain.get('page_role')), '页面角色尚未确认')}（{ENTRY_CONTEXT_BASIS_LABELS.get(str(chain.get('page_role_basis')), '依据未知')}）",
            f"- 用户进页前已可靠完成：{'、'.join(map(str, precompleted)) if precompleted else '没有可靠证据表明某项已经完成'}",
            f"- 页面仍需完成：{'、'.join(map(str, remaining)) if remaining else '尚未确认'}",
            f"- 选择维度顺序：{' → '.join(VARIANT_TYPE_LABELS.get(str(item), str(item)) for item in selection_order) if selection_order else '无多维选择，或顺序尚未确认'}",
            f"- 平台原始规格组与真实选择任务：{raw_spec_text}",
            f"- 页面主导路线：{md(chain.get('dominant_route'), '尚未确认')}",
            f"- 当前商品决策是否闭合：{DECISION_CLOSURE_LABELS.get(str(closure.get('status')), '资料不足')}；{md(closure.get('closure_reason'), '尚未完成判断')}",
            f"- 适用对象与使用条件：{ELIGIBILITY_LABELS.get(str(eligibility.get('status')), '资料不足')}；{md(eligibility.get('target_user_or_object'), '尚未确认')}",
        ]
    )


def routing_section(routing: dict[str, Any] | None) -> str:
    if not routing:
        return "本次任务不是页面共用与分版判断。"
    route = str(routing.get("recommended_route", ""))
    lines = [
        f"- 建议路线：{ROUTE_LABELS.get(route, '资料不足，暂不分版')}",
        f"- 为什么：{md(routing.get('decision_summary'), '尚未完成判断')}",
        f"- 所有版本都要保持：{md(routing.get('shared_invariants'), '尚未确认')}",
        f"- 只允许变化：{md(routing.get('change_scope'), '尚未确认')}",
        f"- 什么时候才切换路线：{md(routing.get('activation_conditions'), '暂不切换')}",
        f"- 发布前需要谁确认：{md(routing.get('human_confirmation'), '页面负责人')}",
        f"- 结论边界：{md(routing.get('boundary'), '这是待确认路由建议')}",
    ]
    if route != "standalone_page":
        lines.append("- 暂不建立独立页：入口差异、业务规模、证据和维护能力尚未同时确认。")
    return "\n".join(lines)


def build_course(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    actions = data["actions"]
    first = sorted(actions, key=lambda item: safe_order(item.get("priority")))[0] if actions else None
    lines = [
        "# 商品页诊断与优化建议",
        "",
        "> 方法：by 布兰德老白 BrandBAI",
        "",
        f"> **现在能不能改：** {run_decision_summary(manifest, actions)}",
        "",
        "## 一、这次看什么",
        "",
        course_header(data),
        "",
        "> 本行动单不要求经营数据，不根据缺失数据判断页面效果，也不承诺修改后的点击、转化或销售结果。",
        "",
        "## 二、用户现在能不能顺利完成五个判断",
        "",
        decision_rows(data["decisions"]),
        "",
        "## 三、这一轮最应该先改什么",
        "",
        action_rows(actions, course=True),
        "",
        "> 依据不足时不凑满五项。只有现有页面时可以调整结构、顺序和清晰度，但不得新增资料外主张。",
        "",
        "## 四、需要返回上一步补什么",
        "",
        gap_sections(data["gaps"], course=True),
        "",
        "## 五、回去以后第一步",
        "",
    ]
    if first:
        lines.extend(
            [
                f"- 我先处理的位置：{md(first.get('page_location'))}",
                f"- 我先完成的动作：{md(first.get('action_type'))}——{md(first.get('action_detail'))}",
                f"- 需要谁确认：{md(first.get('human_confirmation'))}",
            ]
        )
    else:
        lines.extend(
            [
                "- 我先处理的位置：暂不改页面",
                "- 我先完成的动作：补齐停止分析所需的最低资料",
                "- 需要谁确认：商品、SKU或页面资料负责人",
            ]
        )
    lines.extend(
        [
            "- 本轮暂不做：不扩展到最终视觉稿、视频脚本、直播话术或未经验证的经营效果结论。",
            "",
            "## 六、限制说明",
            "",
            bullet_lines(manifest.get("limitations", []), "未发现额外限制"),
            "- 动态价格、库存、赠品、物流与权益只按页面时点记录，仍需人工确认当前有效性。",
            "- 所有动作都是待验证建议，不代表页面组件已经有效。",
        ]
    )
    return "\n".join(lines)


def build_professional_01(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    upstream = data["upstream"]
    pv = upstream.get("product_value", {})
    ve = upstream.get("value_expression", {})
    lines = [
        "# 商品页诊断与优化建议",
        "",
        "> 方法：by 布兰德老白 BrandBAI",
        "",
        "## 先看结论",
        "",
        f"> **现在能不能改：** {run_decision_summary(manifest, data['actions'])}",
        "",
        "## 1｜对象、范围与证据成熟度",
        "",
        base_header(manifest, data["sources"], data["coverage"]),
        chain_summary(data["chain"]),
        (
            "- 商品价值上游：可调用；已继承当前商品价值与边界。"
            if pv.get("usable")
            else "- 商品价值上游：未调用或不可用；本轮仍可诊断页面当前表达，但不把页面主张升级为商品事实。"
        ),
        (
            "- 卖点呈现上游：可调用；已继承与当前商品及商品页场景一致的卖点呈现。"
            if ve.get("usable")
            else "- 卖点呈现上游：未调用或不可用；本轮不强制安装其他 Skill。"
        ),
        "",
        "## 2｜五个用户判断",
        "",
        decision_rows(data["decisions"]),
        "",
        *( ["## 页面共用与分版建议", "", routing_section(data["routing"]), ""]
           if manifest.get("task") == "route" else [] ),
        "## 3｜优先修复",
        "",
        action_rows(data["actions"], course=False),
        "",
        "## 4｜资料冲突、未知与返回上游",
        "",
        gap_sections(data["gaps"]),
        "",
        "## 5｜结论边界",
        "",
        bullet_lines(manifest.get("limitations", []), "未发现额外限制"),
        "- 页面出现只证明页面这样表达，不证明组件有效。",
        "- 评论和问答不能裁定商品事实或改变核心价值。",
        "- 整体经营结果不能自动归因到单张主图或详情模块。",
        "- 所有动作均为待验证建议，不承诺未来点击、转化、GMV或ROI。",
    ]
    return "\n".join(lines)


def component_table(components: list[dict[str, Any]], scope: str) -> str:
    selected = [item for item in components if item.get("scope") == scope]
    selected.sort(key=lambda item: safe_order(item.get("sequence")))
    if not selected:
        return "当前没有可用的该范围组件执行项。"
    rows = [
        "| 顺序 | 页面位置 | 信息层 | SKU适用性 | 当前功能 | 推荐功能 | 动作 | 执行要求 | 所需素材 | 验收问题 |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in selected:
        rows.append(
            "| {sequence} | {location} | {layer} | {sku_fit} | {current} | {recommended} | {change} | {instruction} | {material} | {acceptance} |".format(
                sequence=md(item.get("sequence")),
                location=md(item.get("page_location")),
                layer=CONTENT_LAYER_LABELS.get(str(item.get("content_layer")), md(item.get("content_layer"))),
                sku_fit=COMPONENT_APPLICABILITY_LABELS.get(str(item.get("component_applicability")), md(item.get("component_applicability"))),
                current=md(item.get("current_role")),
                recommended=md(item.get("recommended_role")),
                change=md(item.get("change_type")),
                instruction=md(item.get("execution_instruction")),
                material=md(item.get("required_material")),
                acceptance=md(item.get("acceptance_check")),
            )
        )
    return "\n".join(rows)


def validation_sections(validations: list[dict[str, Any]]) -> str:
    if not validations:
        return "当前不强行建立版本实验；先完成页面动作并保留版本。"
    lines: list[str] = []
    for index, item in enumerate(validations, start=1):
        lines.extend(
            [
                f"### 验证任务 {index}",
                "",
                f"- 比较版本：{md(item.get('version_a'))} 与 {md(item.get('version_b'))}",
                f"- 必须保持：{md(item.get('must_keep'))}",
                f"- 单一变量：{md(item.get('single_variable'))}",
                f"- 需要观察：{md(item.get('observation_needed'))}",
                f"- 可比条件：{md(item.get('comparability'))}",
                f"- 边界：{md(item.get('boundary'))}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def build_professional_02(data: dict[str, Any]) -> str:
    status = str(data["manifest"].get("run_status", ""))
    title = "# 主图交易区详情页优化页纲"
    notice = "> 本页是页面执行 Brief，不是最终视觉稿、完整成品文案或发布审核结论。"
    if status == "degraded_no_product_value":
        notice = "> 本轮只使用现有页面依据：可以重排、删减、澄清和核实，但不得新增资料外卖点。"
    elif status == "stopped":
        title = "# 主图交易区详情页优化页纲（暂停页面动作）"
        notice = "> 当前资料不足以继续页面工作。本页只保留停止边界和补资料方向。"
    return "\n".join(
        [
            title,
            "",
            "> 方法：by 布兰德老白 BrandBAI",
            "",
            notice,
            "",
            "## 1｜主图序列",
            "",
            component_table(data["components"], "main_images"),
            "",
            "## 2｜交易区",
            "",
            transaction_section(data["chain"]),
            "",
            "## 3｜详情页模块",
            "",
            component_table(data["components"], "detail_page"),
            "",
            "## 4｜页面版本与验证",
            "",
            validation_sections(data["validation"]),
            "",
            "## 5｜执行边界",
            "",
            "- 页面已有结构优化可以使用页面可见依据；新增主张必须调用可核验补充资料。",
            "- 动态交易信息发布前必须人工复核当前有效性。",
            "- 视觉创作不得扩大功效、跨SKU或把待验证建议写成效果事实。",
        ]
    )


def transaction_section(chain: dict[str, Any]) -> str:
    current = chain.get("current_transaction", {}) if isinstance(chain, dict) else {}
    raw_groups = current.get("raw_spec_groups", []) if isinstance(current, dict) else []
    bundle = current.get("bundle_contents", []) if isinstance(current, dict) else []
    return "\n".join(
        [
            f"- 当前成交角色：{md(current.get('transaction_role'), 'unknown')}",
            f"- 当前SKU：{md(current.get('current_sku_id'), 'unknown')}",
            f"- 当前规格／数量：{md(current.get('current_quantity_or_size'), 'unknown')}",
            f"- 平台规格组：{md([item.get('group_name', '') for item in raw_groups if isinstance(item, dict)], '未整理')}",
            f"- 套组实际到手：{md([item.get('item_name', '') for item in bundle if isinstance(item, dict)], '未整理')}",
            "- 页纲要求：平台字段名不直接等于用户选择任务；先讲清真实SKU、选择顺序与实际到手。",
        ]
    )


def build_professional_03(data: dict[str, Any]) -> str:
    claims = data.get("claims", [])
    supporting = data.get("supporting_sources", [])
    usable = [item for item in claims if item.get("evidence_status") == "usable"]
    pending = [item for item in claims if item.get("evidence_status") != "usable"]
    lines = [
        "# 资料缺口与证据边界",
        "",
        "> 方法：by 布兰德老白 BrandBAI",
        "",
        "## 1｜本次补充资料",
        "",
        f"- 已登记补充资料：{len(supporting)} 份。",
        f"- 可直接调用主张：{len(usable)} 条；待核实或仅作信号：{len(pending)} 条。",
        "",
        "## 2｜当前开放缺口",
        "",
        gap_sections(data["gaps"]),
        "",
        "## 3｜当前资料不能证明什么",
        "",
    ]
    cannot_prove = [str(item.get("cannot_prove", "")).strip() for item in claims]
    lines.append(bullet_lines(cannot_prove, "没有新增可调用主张；继续继承页面主张不等于商品事实的边界"))
    lines.extend(
        [
            "",
            "## 4｜永久边界",
            "",
            "- 评论只作为用户语言、顾虑和场景信号，不裁定商品功效。",
            "- 竞品页面只支持结构与表达比较，不证明本商品优势。",
            "- 价格、赠品、库存、物流和权益必须带页面时间，发布前复核。",
            "- 其他SKU、变体、套组单品和品牌共性不能自动证明当前成交单元。",
            "- 静态诊断与改版建议不等于转化归因或经营结果保证。",
        ]
    )
    return "\n".join(lines)


def build_delivery(delivery: Path, write: bool = True) -> dict[str, Any]:
    delivery = delivery.expanduser().resolve()
    data = load_delivery(delivery)
    mode = data["manifest"].get("delivery_mode")
    if mode == "course":
        outputs = {COURSE_REPORT: build_course(data)}
    elif mode == "professional":
        outputs = {
            PROFESSIONAL_REPORTS[0]: build_professional_01(data),
            PROFESSIONAL_REPORTS[1]: build_professional_02(data),
            PROFESSIONAL_REPORTS[2]: build_professional_03(data),
        }
    else:
        raise ValueError("delivery_mode 必须是 course 或 professional")
    if write:
        for name, content in outputs.items():
            write_text(delivery / name, content)
        if mode == "professional":
            legacy = delivery / LEGACY_PROFESSIONAL_REPORT
            if legacy.is_file() and legacy.name not in outputs:
                legacy.unlink()
    return {
        "status": "written" if write else "dry_run",
        "delivery_mode": mode,
        "reports": list(outputs),
        "action_count": len(data["actions"]),
        "component_count": len(data["components"]),
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
