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
    RECOMMENDATION_LABELS,
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
LEGACY_PROFESSIONAL_REPORTS = (
    "02_主图与详情页执行页.md",
    "03_资料缺口与证据边界.md",
)
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
    "product_value": "补充商品核心资料",
    "value_expression": "补充已验证卖点资产",
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
DETAIL_HANDLING_LABELS = {
    "继续使用": "继续使用",
    "集中到一个章节": "集中到一个章节",
    "分别放入不同章节": "分别放入不同章节",
    "提前说明": "提前说明",
    "放到后面": "放到后面",
    "本轮不使用": "本轮不再使用",
    "确认后再安排": "确认后再安排",
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
DECISION_QUESTIONS = {
    "认对": "我买的到底是哪一款、多少、到手是什么",
    "看懂": "它为什么值得买",
    "相信": "我凭什么相信",
    "选对": "这么多规格，我该选哪一个",
    "放心买": "价格权益、用法、风险和售后是否清楚",
}
ANALYSIS_TARGET_BASIS_LABELS = {
    "detail_page_and_visible_option": "详情页主讲内容与可见SKU选项共同确认",
    "user_confirmed": "由业务负责人确认",
    "page_visible_target": "依据页面主讲内容确认",
    "unknown": "尚未确认",
}
VISIBLE_OPTION_MATCH_LABELS = {
    "matched": "已在可见SKU选项中找到并唯一匹配",
    "not_found": "未在可见SKU选项中找到",
    "ambiguous": "可见选项中存在多个可能匹配项",
    "not_provided": "本轮未提供可见SKU选项",
}
DYNAMIC_SNAPSHOT_LABELS = {
    "applicable_to_analysis_sku": "可以用于本次分析SKU",
    "not_applicable_to_analysis_sku": "不适用于本次分析SKU",
    "unknown": "是否适用于本次分析SKU尚未确认",
    "not_provided": "本轮未提供动态价格权益",
}
CURRENT_ROUTE_ROLE_LABELS = {
    "identity": "商品与当前规格",
    "problem_education": "需求与问题",
    "value_claim": "核心购买理由",
    "mechanism": "结构与原理",
    "evidence": "证明与信任",
    "experience_demo": "体验演示",
    "sku_selection": "规格选择与实际到手",
    "campaign_benefit": "活动与权益",
    "fulfilment_service": "履约与服务",
    "usage_boundary": "用法、适用与边界",
    "brand_trust": "品牌与信任",
    "other": "其他补充内容",
}

BRAND_LANGUAGE_REPLACEMENTS = (
    ("当前SKU的有效商品价值底座", "品牌确认的核心购买理由及支持资料"),
    ("SKU专属主图最低配置", "为每个商品选项补齐专属主图"),
    ("当前SKU准确到手", "当前所选商品会收到什么"),
    ("当前SKU技术与证据", "当前商品的技术与证明资料"),
    ("当前SKU配方", "当前商品配方"),
    ("SKU证据一致性", "商品与证明资料一致"),
    ("跨SKU一致性", "不同商品选项之间保持一致"),
    ("商品价值底座", "商品核心价值资料"),
    ("静态信息与动态权益分区", "把长期商品信息与当前优惠分开"),
    ("动态权益", "当前优惠"),
    ("动态优惠边界", "当前优惠说明"),
    ("静态信息", "长期商品信息"),
    ("SKU", "商品选项"),
    ("事实型购买理由", "具体购买理由"),
    ("事实型价值", "具体价值"),
    ("事实型", "具体"),
    ("结果型利益", "结果承诺"),
    ("结果型语言", "结果说法"),
    ("结果型词语", "结果说法"),
    ("结果型文案", "结果说法"),
    ("结果型表达", "结果说法"),
    ("结果型主图", "结果承诺主图"),
    ("结果主张", "结果说法"),
    ("强主张", "重点说法"),
    ("主张依据", "说法依据"),
    ("新增主张", "新增说法"),
    ("事实资产", "商品信息与画面"),
    ("商品事实和饮用判断", "商品本身和饮用方法"),
    ("交代商品事实", "交代商品基础信息"),
    ("基础商品事实", "商品基础信息"),
    ("商品事实先行", "商品基础信息先讲"),
    ("完整商品事实", "完整商品信息"),
    ("实时交易", "下单前确认"),
    ("静态页面改版方向", "当前页面的改版方向"),
    ("调用可核验补充资料", "使用可核验的补充资料"),
    ("支持对象与边界", "证明什么、适用于谁"),
    ("页面现有说法升级为独立确认事实", "把页面上的说法当作已经单独验证的结论"),
    ("独立确认事实", "单独验证的结论"),
    ("已确认事实", "已经验证的结论"),
    ("证据边界", "证明范围"),
    ("适用边界", "适用范围"),
    ("实时交易收口", "下单前确认"),
    ("交易收口", "下单前确认"),
    ("页面主张", "页面现有说法"),
    ("当前成交单元", "当前商品"),
    ("静态诊断", "当前页面诊断"),
    ("条件式诊断", "在当前资料范围内诊断"),
    ("条件式建议", "在当前资料范围内提出建议"),
)


def brand_language(text: str) -> str:
    for old, new in BRAND_LANGUAGE_REPLACEMENTS:
        text = text.replace(old, new)
    return text


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
        "matches",
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
        "matches": read_jsonl(paths["matches"]),
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
        return f"可以直接开始优化；建议只推进下方{action_count}个改版项目，改完后再验证。"
    if status == "partial":
        return f"可以先做有把握的部分；建议只推进下方{action_count}项，待确认内容不写成确定结论。"
    if status == "degraded_no_product_value":
        return f"只用现有页面也可以提出优化；建议只推进下方{action_count}个有依据的项目，不新增页面之外的卖点。"
    return "暂时不要改页面；先补齐商品、规格或页面材料。"


def decision_rows(decisions: list[dict[str, Any]]) -> str:
    by_name = {str(row.get("decision_name", "")): row for row in decisions}
    sections: list[str] = []
    for name in DECISION_NAMES:
        row = by_name.get(name, {})
        sections.extend(
            [
                f"### {name}｜{DECISION_QUESTIONS[name]}｜{md(row.get('status'), '资料不足')}",
                "",
                f"- 已经讲清：{md(row.get('explained'), '当前资料不足，暂时无法确认')}",
                f"- 还没讲清：{md(row.get('not_explained'), '当前关键缺口尚未拆清')}",
                f"- 为什么影响购买：{md(row.get('purchase_impact'), '影响尚未确认')}",
                f"- 具体怎么补：{md(row.get('recommended_fix'), '先补齐最低资料再决定')}",
                "",
            ]
        )
    return "\n".join(sections).rstrip()


def analysis_target_summary(manifest: dict[str, Any], chain: dict[str, Any]) -> str:
    target = chain.get("analysis_target", {}) if isinstance(chain, dict) else {}
    if not isinstance(target, dict):
        target = {}
    page_primary = str(target.get("page_primary_sku_or_variant", "")).strip()
    return "\n".join(
        [
            f"- **分析商品：** {md(target.get('analysis_sku'), manifest.get('sku'))}",
            f"- **页面主要销售的规格：** {md(page_primary, '尚未确认')}",
            f"- **商品与页面是否对应：** {ANALYSIS_TARGET_BASIS_LABELS.get(str(target.get('target_basis')), '尚未确认')}；{VISIBLE_OPTION_MATCH_LABELS.get(str(target.get('visible_option_match_status')), '尚未确认')}",
            f"- **价格、赠品等是否适用于这个规格：** {DYNAMIC_SNAPSHOT_LABELS.get(str(target.get('dynamic_snapshot_applicability')), '尚未确认')}",
            f"- **本次分析范围：** {md(target.get('boundary'), '尚未确认')}",
        ]
    )


def brand_scope_summary(manifest: dict[str, Any], chain: dict[str, Any]) -> str:
    """Explain the reviewed product in client language, without exposing workflow jargon."""
    target = chain.get("analysis_target", {}) if isinstance(chain, dict) else {}
    if not isinstance(target, dict):
        target = {}
    match_status = str(target.get("visible_option_match_status", ""))
    match_text = {
        "matched": "页面主要内容与当前可购买选项能够对应，本次可以继续提出优化方案。",
        "not_found": "页面主要内容暂时无法与当前可购买选项对应，先核实商品后再改。",
        "ambiguous": "页面主要内容可能对应多个可购买选项，先由品牌确认主推款。",
        "not_provided": "本次未看到可购买选项，只对已提供页面内容提出条件式建议。",
    }.get(match_status, "当前商品与页面的对应关系仍需品牌确认。")
    dynamic_status = str(target.get("dynamic_snapshot_applicability", ""))
    dynamic_text = {
        "applicable_to_analysis_sku": "页面当时显示的价格和优惠可作为本次商品的时点参考，发布前仍需复核。",
        "not_applicable_to_analysis_sku": "页面价格或优惠不能明确归到本次商品，本报告不把它写进改版方案。",
        "unknown": "价格和优惠是否适用于本次商品尚未确认，本报告不作确定表达。",
        "not_provided": "本次没有使用价格、赠品或库存信息。",
    }.get(dynamic_status, "价格和优惠按页面时点处理，发布前需复核。")
    return "\n".join(
        [
            f"- **分析商品：** {md(target.get('analysis_sku'), manifest.get('sku'))}",
            f"- **页面主要销售的规格：** {md(target.get('page_primary_sku_or_variant'), '尚未确认')}",
            f"- **商品与页面是否对应：** {match_text}",
            f"- **价格和优惠：** {dynamic_text}",
            f"- **本次分析范围：** {md(target.get('boundary'), '未提供或尚未确认的商品与动态交易信息')}",
        ]
    )


def overall_diagnosis_section(chain: dict[str, Any]) -> str:
    diagnosis = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    if not isinstance(diagnosis, dict):
        diagnosis = {}
    strengths = diagnosis.get("strengths_to_preserve", [])
    roots = diagnosis.get("root_problems", [])
    lines = [
        f"- **页面现在怎样推动购买：** {md(diagnosis.get('current_page_strategy'), '尚未完成整体判断')}",
        f"- **用户目前怎样完成选择：** {md(diagnosis.get('current_conversion_logic'), '尚未完成整体判断')}",
        f"- **页面最想让用户记住的购买理由：** {md(diagnosis.get('current_core_purchase_reason'), '尚未确认')}",
        f"- **整体判断：** {md(diagnosis.get('professional_judgement'), '尚未完成整体判断')}",
        "",
        "### 现有页面中建议继续保留",
        "",
        bullet_lines(strengths, "当前还没有确认可保留优势"),
        "",
        "### 最值得先解决的问题",
        "",
    ]
    if not roots:
        lines.append("当前没有确认需要进入改版的整体根因；不为凑数制造问题。")
    else:
        for index, item in enumerate(roots, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"#### 问题 {index}｜{md(item.get('title'), '尚未命名')}",
                    "",
                    f"- 具体表现：{md(item.get('diagnosis'))}",
                    f"- 页面依据：{md(item.get('supporting_observations'))}",
                    f"- 购买影响：{md(item.get('purchase_consequence'))}",
                    f"- 影响哪些买前问题：{md(item.get('affected_decisions'))}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip()


def detail_page_assessment_section(chain: dict[str, Any]) -> str:
    assessment = chain.get("detail_page_assessment", {}) if isinstance(chain, dict) else {}
    if not isinstance(assessment, dict):
        assessment = {}
    status = str(assessment.get("status", ""))
    if status != "assessed":
        return "\n".join(
            [
                f"- **本次评估：** {md(assessment.get('assessment_basis'), '当前没有足够的可读详情页资料。')}",
                f"- **边界：** {md(assessment.get('boundary'), '资料补齐前不推测详情页优缺点。')}",
            ]
        )
    strengths = [item for item in assessment.get("strengths", []) if isinstance(item, dict)]
    opportunities = [
        item for item in assessment.get("improvement_opportunities", []) if isinstance(item, dict)
    ]
    lines = [
        "> 评估依据：综合看了用户买这类商品时需要确认的问题，以及页面是否帮助用户认对、看懂、相信、选对和放心买。",
        "",
        "#### 已有优势",
        "",
    ]
    if strengths:
        for item in strengths:
            lines.extend(
                [
                    f"- **{md(item.get('title'))}：** {md(item.get('why_it_helps'))}",
                    f"  - 改版时要保留：{md(item.get('preserve_requirement'))}",
                ]
            )
    else:
        lines.append("- 当前没有足够依据确认成熟优势；不为平衡报告强行表扬。")
    lines.extend(["", "#### 还可提升", ""])
    if opportunities:
        for item in opportunities:
            lines.extend(
                [
                    f"- **{md(item.get('title'))}：** {md(item.get('what_is_not_yet_clear'))}",
                    f"  - 对购买的影响：{md(item.get('purchase_impact'))}",
                    f"  - 建议方向：{md(item.get('improvement_direction'))}",
                    f"  - 改到什么程度：{md(item.get('acceptance_check'))}",
                ]
            )
    else:
        lines.append("- 当前没有确认需要进入优化的详情页问题；不为凑数制造改版。")
    return "\n".join(lines)


def rebuild_strategy_section(chain: dict[str, Any]) -> str:
    strategy = chain.get("rebuild_strategy", {}) if isinstance(chain, dict) else {}
    if not isinstance(strategy, dict):
        strategy = {}
    roles = strategy.get("surface_roles", {})
    if not isinstance(roles, dict):
        roles = {}
    route = strategy.get("narrative_route", [])
    route_text = " → ".join(str(item) for item in route if str(item).strip()) or "尚未形成新版叙事路线"
    return "\n".join(
        [
            f"- **这次优化目标：** {md(strategy.get('strategic_objective'), '尚未确认')}",
            f"- **优化后建议这样讲：** {md(strategy.get('proposed_purchase_logic'), '尚未确认')}",
            f"- **建议页面顺序：** {route_text}",
            "",
            "### 主图、交易区与详情页怎样分工",
            "",
            f"- 主图：{md(roles.get('main_images'), '尚未确认')}",
            f"- 交易区：{md(roles.get('transaction_panel'), '尚未确认')}",
            f"- 详情页：{md(roles.get('detail_page'), '尚未确认')}",
            f"- 页面最后确认：{md(roles.get('decision_close'), '尚未确认')}",
            "",
            "### 哪些内容继续使用，哪些内容需要调整",
            "",
            "#### 继续保留",
            "",
            bullet_lines(strategy.get("preserve", []), "尚未确认"),
            "",
            "#### 调整层级、集中呈现或不再使用",
            "",
            bullet_lines(strategy.get("deprioritize_or_remove", []), "尚未确认"),
            "",
            f"- 改完的标准：{md(strategy.get('success_definition'), '尚未确认')}",
        ]
    )


def root_title_lookup(chain: dict[str, Any]) -> dict[str, str]:
    overall = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    roots = overall.get("root_problems", []) if isinstance(overall, dict) else []
    return {
        str(item.get("root_problem_id", "")): str(item.get("title", "")).strip()
        for item in roots if isinstance(item, dict) and item.get("root_problem_id")
    }


def action_root_titles(item: dict[str, Any], root_lookup: dict[str, str]) -> str:
    titles = [root_lookup.get(str(root_id), "") for root_id in item.get("root_problem_ids", [])]
    return "、".join(title for title in titles if title) or "整体问题待核对"


def recommendation_label(item: dict[str, Any]) -> str:
    """Keep drafts readable; formal validation still rejects a missing or invalid label."""
    label = str(item.get("recommendation_label", "")).strip()
    if label in RECOMMENDATION_LABELS:
        return label
    if item.get("action_type") == "人工核实":
        return "补充资料后优化"
    return "可直接优化"


def brand_priority_table(
    actions: list[dict[str, Any]], root_lookup: dict[str, str], limit: int = 3
) -> str:
    ordered = [
        item for item in sorted(actions, key=lambda item: safe_order(item.get("priority")))
        if item.get("action_type") != "保留"
    ][:limit]
    if not ordered:
        return "当前没有足够依据形成可执行动作；先按资料缺口补齐最低信息。"
    rows = [
        "| 顺序 | 改版项目 | 为什么做 | 想达到什么 | 主要改哪里 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(ordered, start=1):
        rows.append(
            f"| {index} | {md(item.get('project_name'), item.get('page_location'))} | "
            f"{md(action_root_titles(item, root_lookup))} | {md(item.get('strategic_goal'), item.get('action_detail'))} | "
            f"{md(item.get('page_location'))} |"
        )
    return "\n".join(rows)


def brand_top_root_problem(chain: dict[str, Any]) -> str:
    """Keep only the most important root problem in the executive summary."""
    overall = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    roots = overall.get("root_problems", []) if isinstance(overall, dict) else []
    first = next((item for item in roots if isinstance(item, dict)), None)
    if not first:
        return "当前没有需要为了凑数而新增的问题，以保留成熟内容为主。"
    title = md(first.get("title"), "待确认的问题")
    impact = md(first.get("purchase_consequence"), first.get("diagnosis"))
    return f"{title}：{impact}"


def current_page_route(chain: dict[str, Any], components: list[dict[str, Any]]) -> str:
    """Build the current route only from observed page components, never from the rebuild route."""
    by_id = {
        str(item.get("component_id", "")): item
        for item in components
        if isinstance(item, dict) and str(item.get("component_id", "")).strip()
    }
    ordered_ids = [str(item) for item in chain.get("ordered_component_ids", [])]
    ordered = [by_id[item] for item in ordered_ids if item in by_id]
    if not ordered:
        ordered = sorted(
            [item for item in components if isinstance(item, dict)],
            key=lambda item: safe_order(item.get("sequence")),
        )
    labels: list[str] = []
    for item in ordered:
        role = str(item.get("module_role", "other"))
        label = CURRENT_ROUTE_ROLE_LABELS.get(role, "其他补充内容")
        if not labels or labels[-1] != label:
            labels.append(label)
    return " → ".join(labels) or "尚未看清页面现在的讲述顺序"


def match_is_gap(match: dict[str, Any]) -> bool:
    return not (
        str(match.get("coverage_status")) == "matched"
        and str(match.get("position_status")) == "right_position"
        and str(match.get("evidence_connection_status")) in {"connected", "not_required"}
        and str(match.get("redundancy_status"))
        in {"focused", "necessary_repetition", "not_applicable"}
    )


def dual_chain_section(
    chain: dict[str, Any],
    matches: list[dict[str, Any]],
    components: list[dict[str, Any]],
    limit: int = 3,
) -> str:
    """Show the key purchase gaps in brand language; keep audit enums in data/."""
    category_chain = chain.get("category_decision_chain", {}) if isinstance(chain, dict) else {}
    if not isinstance(category_chain, dict):
        category_chain = {}
    tasks = [item for item in category_chain.get("tasks", []) if isinstance(item, dict)]
    tasks.sort(key=lambda item: safe_order(item.get("sequence")))
    task_route = " → ".join(str(item.get("task_name", "")).strip() for item in tasks if str(item.get("task_name", "")).strip())
    page_route = current_page_route(chain, components)
    by_task = {
        str(item.get("category_task_id", "")): item
        for item in matches
        if isinstance(item, dict) and str(item.get("category_task_id", "")).strip()
    }
    basis_text = {
        "working_hypothesis": "以下问题根据当前商品和页面整理，后续可结合品牌经验和用户反馈调整。",
        "evidence_strengthened": "以下问题同时参考了当前页面和已提供资料，后续可结合用户反馈调整。",
        "brand_confirmed": "以下问题顺序已经品牌业务负责人确认。",
        "user_validated": "以下问题顺序已有可回溯的用户研究或行为验证支持。",
        "unknown": "当前资料不足，以下只列已经能够确认的买前问题。",
    }.get(str(category_chain.get("maturity", "unknown")), "当前资料不足，以下只列已经能够确认的买前问题。")
    lines = [
        f"- **用户下单前，需要依次确认：** {task_route or '尚未整理出完整的买前问题'}",
        f"- **页面现在的讲述顺序：** {page_route}",
        "",
        f"> {basis_text}",
        "",
        "| 买前要弄清楚 | 页面目前怎么讲 | 不讲清会怎样 |",
        "| --- | --- | --- |",
    ]
    importance_rank = {"critical": 0, "important": 1, "supporting": 2}
    coverage_rank = {"conflict": 0, "missing": 1, "weak": 2, "unknown": 3, "matched": 4}
    gaps: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for task in tasks:
        match = by_task.get(str(task.get("task_id", "")), {})
        if match_is_gap(match):
            gaps.append((task, match))
    gaps.sort(
        key=lambda pair: (
            importance_rank.get(str(pair[0].get("importance")), 9),
            coverage_rank.get(str(pair[1].get("coverage_status")), 9),
            safe_order(pair[0].get("sequence")),
        )
    )
    for task, match in gaps[:limit]:
        lines.append(
            f"| {md(task.get('user_question'), task.get('task_name'))} | "
            f"{md(match.get('current_content_summary'), '暂未找到清楚承接')} | "
            f"{md(match.get('user_consequence'), '用户仍需自己寻找或拼接信息')} |"
        )
    if not gaps:
        lines.append("| 关键买前问题 | 页面已经在合适位置讲清 | 保留现有表达即可 |")
    return brand_language("\n".join(lines))


def brand_decision_table(
    decisions: list[dict[str, Any]], actions: list[dict[str, Any]], chain: dict[str, Any]
) -> str:
    """Keep the five-decision audit visible, but make it optional and compact."""
    by_name = {str(row.get("decision_name", "")): row for row in decisions}
    overall = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    roots = overall.get("root_problems", []) if isinstance(overall, dict) else []
    root_decisions = {
        str(item.get("root_problem_id", "")): {
            str(name) for name in item.get("affected_decisions", []) if str(name).strip()
        }
        for item in roots if isinstance(item, dict)
    }
    project_by_decision: dict[str, list[str]] = {}
    for item in sorted(actions, key=lambda row: safe_order(row.get("priority"))):
        names = {str(item.get("decision_name", "")).strip()}
        for root_id in item.get("root_problem_ids", []):
            names.update(root_decisions.get(str(root_id), set()))
        project = str(item.get("project_name") or item.get("page_location") or "本轮改版项目")
        for name in names:
            if name:
                project_by_decision.setdefault(name, []).append(project)
    rows = [
        "| 用户买前会问 | 页面已经讲清 | 还需要补什么 | 本轮怎样安排 |",
        "| --- | --- | --- | --- |",
    ]
    for name in DECISION_NAMES:
        row = by_name.get(name, {})
        projects = project_by_decision.get(name, [])
        handling = "、".join(dict.fromkeys(projects)) if projects else "保持现状，不单独改"
        rows.append(
            f"| {DECISION_QUESTIONS[name]} | {md(row.get('explained'), '暂时无法确认')} | "
            f"{md(row.get('not_explained'), '暂无关键缺口')} | {handling} |"
        )
    return "\n".join(rows)


def brand_action_rows(
    actions: list[dict[str, Any]], root_lookup: dict[str, str]
) -> str:
    """Render compact project cards; the full execution ledger stays in data/."""
    ordered = sorted(actions, key=lambda item: safe_order(item.get("priority")))
    if not ordered:
        return "当前没有足够依据形成改版项目；先补齐商品、页面或必要确认信息。"
    sections: list[str] = []
    for item in ordered:
        needed = "；".join(
            value.rstrip("。；; ")
            for value in (
                str(item.get("material_needed", "")).strip(),
                str(item.get("human_confirmation", "")).strip(),
            )
            if value
        )
        sections.extend(
            [
                f"### {md(item.get('priority'))}｜{md(item.get('project_name'), item.get('page_location'))}",
                "",
                f"> **要解决：** {md(item.get('gap_or_risk'), action_root_titles(item, root_lookup))}",
                "",
                f"- **怎么改：** {md(item.get('action_detail'))}",
                f"- **改哪里：** {md(item.get('page_location'))}",
                f"- **需要准备：** {md(needed, '现有页面素材即可开始')}",
                f"- **完成标准：** {md(item.get('acceptance_check'))}",
                f"- **保留内容：** {md(item.get('must_preserve'))}",
                "",
            ]
        )
    return "\n".join(sections).rstrip()


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


def action_rows(
    actions: list[dict[str, Any]], course: bool, root_lookup: dict[str, str]
) -> str:
    ordered = sorted(actions, key=lambda item: safe_order(item.get("priority")))
    if not ordered:
        return "当前依据不足或没有高优先动作，本轮不强行凑数。"
    if course:
        sections: list[str] = []
        for item in ordered:
            label = recommendation_label(item)
            needed = "；".join(
                value.rstrip("。；; ") for value in (
                    str(item.get("material_needed", "")).strip(),
                    str(item.get("human_confirmation", "")).strip(),
                ) if value
            )
            sections.extend(
                [
                    f"### 优先 {md(item.get('priority'))}｜{md(item.get('project_name'), item.get('page_location'))}",
                    "",
                    f"- 建议标签：{md(label)}",
                    f"- 对应整体问题：{md(action_root_titles(item, root_lookup))}",
                    f"- 改版目标：{md(item.get('strategic_goal'))}",
                    f"- 主要落点：{md(item.get('page_location'))}（{md(item.get('decision_name'))}）",
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
        label = recommendation_label(item)
        sections.extend(
            [
                f"### 改版项目 {md(item.get('priority'))}｜{md(item.get('project_name'), item.get('page_location'))}",
                "",
                f"- 对应整体问题：{md(action_root_titles(item, root_lookup))}",
                f"- 改版目标：{md(item.get('strategic_goal'))}",
                f"- 主要落点：{md(item.get('page_location'))}",
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
            lines.extend(
                [
                    f"- **要补：** {md(item.get('missing'))}",
                    f"  - 为什么要补：{md(item.get('impact'))}",
                    f"  - 最少提供：{md(item.get('minimum_needed'))}",
                ]
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


def diagnosis_summary(manifest: dict[str, Any], chain: dict[str, Any]) -> str:
    """Return a client-readable summary for both combined and single-surface runs."""
    overall = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    judgement = str(overall.get("professional_judgement", "")).strip()
    if judgement:
        return judgement
    cross_surface = str(manifest.get("cross_surface_summary", "")).strip()
    if cross_surface and cross_surface != "not_applicable":
        return cross_surface
    return "当前页面最需要先讲清商品、规格与购买理由。"


def build_course(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    actions = data["actions"]
    first = sorted(actions, key=lambda item: safe_order(item.get("priority")))[0] if actions else None
    lines = [
        "# 商品页整体诊断与重构方案",
        "",
        "> 方法：by 布兰德老白 BrandBAI",
        "",
        f"> **现在能不能改：** {run_decision_summary(manifest, actions)}",
        "",
        "## 一、品牌先看这一页",
        "",
        f"> **一句话诊断：** {md(diagnosis_summary(manifest, data['chain']))}",
        "",
        analysis_target_summary(manifest, data["chain"]),
        "",
        "### 页面整体诊断",
        "",
        overall_diagnosis_section(data["chain"]),
        "",
        "### 用户买前要弄清楚什么",
        "",
        dual_chain_section(data["chain"], data["matches"], data["components"]),
        "",
        "### 整体重构思路",
        "",
        rebuild_strategy_section(data["chain"]),
        "",
        "### 最优先的改版项目（最多三个）",
        "",
        brand_priority_table(actions, root_title_lookup(data["chain"])),
        "",
        "## 二、这次看了什么",
        "",
        course_header(data),
        "",
        "> 本行动单不要求经营数据，不根据缺失数据判断页面效果，也不承诺修改后的点击、转化或销售结果。",
        "",
        "## 三、五个买前问题还有哪些没讲清",
        "",
        decision_rows(data["decisions"]),
        "",
        "## 四、这一轮的改版项目",
        "",
        action_rows(actions, course=True, root_lookup=root_title_lookup(data["chain"])),
        "",
        "> 依据不足时不凑满五项。只有现有页面时可以调整结构、顺序和清晰度，但不得新增资料外主张。",
        "",
        "## 五、还需要补什么资料",
        "",
        gap_sections(data["gaps"], course=True),
        "",
        "## 六、建议先做",
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
            "## 七、限制说明",
            "",
            bullet_lines(manifest.get("limitations", []), "未发现额外限制"),
            "- 动态价格、库存、赠品、物流与权益只按页面时点记录，仍需人工确认当前有效性。",
            "- 所有动作都是待验证建议，不代表页面组件已经有效。",
        ]
    )
    return brand_language("\n".join(lines))


def build_professional_01(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    upstream = data["upstream"]
    pv = upstream.get("product_value", {})
    ve = upstream.get("value_expression", {})
    chain = data["chain"]
    diagnosis = chain.get("overall_diagnosis", {}) if isinstance(chain, dict) else {}
    if not isinstance(diagnosis, dict):
        diagnosis = {}
    strategy = chain.get("rebuild_strategy", {}) if isinstance(chain, dict) else {}
    if not isinstance(strategy, dict):
        strategy = {}
    roles = strategy.get("surface_roles", {})
    if not isinstance(roles, dict):
        roles = {}
    route = strategy.get("narrative_route", [])
    route_text = " → ".join(str(item) for item in route if str(item).strip()) or "尚未形成建议顺序"
    strengths = diagnosis.get("strengths_to_preserve", [])
    claims = data.get("claims", [])
    supporting = data.get("supporting_sources", [])
    usable_claims = [item for item in claims if item.get("evidence_status") == "usable"]
    pending_claims = [item for item in claims if item.get("evidence_status") != "usable"]
    cannot_prove = list(
        dict.fromkeys(
            str(item.get("cannot_prove", "")).strip()
            for item in claims
            if str(item.get("cannot_prove", "")).strip()
        )
    )
    if supporting and (usable_claims or pending_claims):
        proof_summary = (
            f"- 补充资料已纳入判断：{len(usable_claims)} 条内容可用于当前页面，"
            f"{len(pending_claims)} 条仍需确认或只能作为参考。"
        )
    elif supporting:
        proof_summary = "- 补充资料已纳入判断；本轮未据此新增商品说法，仍按现有页面与已确认事实优化结构。"
    else:
        proof_summary = "- 本次建议主要依据当前页面；不新增页面之外的商品说法。"
    first = sorted(data["actions"], key=lambda item: safe_order(item.get("priority")))[0] if data["actions"] else None
    lines = [
        "# 商品页诊断与优化方案",
        "",
        "> 方法：by 布兰德老白 BrandBAI",
        "",
        "## 先看结论",
        "",
        f"> **一句话判断：** {md(diagnosis_summary(manifest, chain))}",
        "",
        f"- **本轮建议：** {run_decision_summary(manifest, data['actions'])}",
        f"- **页面现在主要靠什么卖：** {md(diagnosis.get('current_core_purchase_reason'), diagnosis.get('current_page_strategy'))}",
        f"- **建议先做：** {md(first.get('project_name'), first.get('page_location')) if first else '先补齐最低资料，不急着改页面'}",
        f"- **最影响下单的问题：** {brand_top_root_problem(chain)}",
        "",
        "### 现有页面中建议继续保留",
        "",
        bullet_lines(strengths, "当前还没有确认可直接保留的成熟内容"),
        "",
        "### 详情页已有优势与提升空间",
        "",
        detail_page_assessment_section(chain),
        "",
        "## 1｜哪些信息还需要讲清",
        "",
        dual_chain_section(chain, data["matches"], data["components"]),
        "",
        "## 2｜改版后怎么讲",
        "",
        f"- **这次改版目标：** {md(strategy.get('strategic_objective'), '尚未确认')}",
        f"- **建议的新购买顺序：** {route_text if route_text != '尚未形成建议顺序' else md(strategy.get('proposed_purchase_logic'), '尚未确认')}",
        "",
        "### 主图、交易区和详情页怎样配合",
        "",
        f"- 主图先完成：{md(roles.get('main_images'), '尚未确认')}",
        f"- 交易区负责：{md(roles.get('transaction_panel'), '尚未确认')}",
        f"- 详情页继续讲清：{md(roles.get('detail_page'), '尚未确认')}",
        f"- 页面最后让用户确认：{md(roles.get('decision_close'), '尚未确认')}",
        "",
        "### 继续使用与重点调整",
        "",
        "**继续保留**",
        "",
        bullet_lines(strategy.get("preserve", []), "尚未确认"),
        "",
        "**调整层级、集中呈现或不再使用**",
        "",
        bullet_lines(strategy.get("deprioritize_or_remove", []), "尚未确认"),
        "",
        f"- **改完的标准：** {md(strategy.get('success_definition'), '尚未确认')}",
        "",
        "## 3｜本轮改版项目",
        "",
        brand_action_rows(data["actions"], root_title_lookup(chain)),
        "",
        "## 4｜五个买前问题（需要时再看）",
        "",
        "> 如果只推进本轮改版，前面三部分已经够用；这里用于复核是否还有遗漏。",
        "",
        brand_decision_table(data["decisions"], data["actions"], chain),
        "",
        "## 5｜本次分析范围",
        "",
        brand_scope_summary(manifest, chain),
        "",
        f"- **已查看材料：** {readable_scope_summary(data['sources'])}",
        f"- **页面时间：** {md(manifest.get('page_snapshot_time'), '时间未知')}",
        (
            "- **品牌内部商品资料：** 本次已提供并完成适用范围核对，可用于当前页面建议。"
            if pv.get("usable")
            else "- **品牌内部商品资料：** 本次未补充；报告只优化页面当前表达，不新增资料之外的卖点。"
        ),
        (
            "- **可直接使用的卖点资料：** 本次已提供，并已核对与当前商品及商品页场景一致。"
            if ve.get("usable")
            else "- **可直接使用的卖点资料：** 本次未补充；不影响现有页面诊断，但不新增页面资料之外的卖点。"
        ),
        "",
        *( ["## 页面共用与分版建议", "", routing_section(data["routing"]), ""]
           if manifest.get("task") == "route" else [] ),
        "## 6｜还需补什么与下一步",
        "",
        gap_sections(data["gaps"]),
        "",
        "## 7｜使用边界",
        "",
        "### 补充资料与证明范围",
        "",
        proof_summary,
        "- **当前资料不能证明：**",
        bullet_lines(cannot_prove, "没有补充证据时，不把页面宣传语升级为已经独立验证的事实"),
        "",
        "### 长期边界",
        "",
        "- 页面公开内容可以用于调整顺序和表达；不能因此把宣传语写成已经独立验证的事实。",
        "- 评论只作为用户语言、顾虑和场景信号，不裁定商品功效。",
        "- 竞品页面只支持结构与表达比较，不证明本商品优势。",
        "- 其他商品选项、变体、套组单品和品牌共性不能自动证明当前商品。",
        "- 价格、赠品、库存和物流以发布时页面为准。",
        "- 本报告给出静态页面改版方向，不承诺点击、转化、GMV或ROI结果。",
    ]
    return brand_language("\n".join(lines))


def component_table(components: list[dict[str, Any]], scope: str) -> str:
    selected = [item for item in components if item.get("scope") == scope]
    selected.sort(key=lambda item: safe_order(item.get("sequence")))
    if not selected:
        return "当前没有可用的该范围组件执行项。"
    rows = [
        "| 顺序 | 页面位置 | 内容类型 | 适用于 | 现在在讲什么 | 调整后负责什么 | 新版怎么安排 | 执行要求 | 需要什么素材 | 怎么验收 |",
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


def detail_page_content_map(chain: dict[str, Any]) -> str:
    """Render the future detail page by decision modules, never by old image order."""
    plan = chain.get("detail_page_plan", {}) if isinstance(chain, dict) else {}
    if not isinstance(plan, dict):
        plan = {}
    status = str(plan.get("status", "unknown"))
    if status in {"not_in_scope", "insufficient_material", "stopped"}:
        return "\n".join(
            [
                f"- **本次处理：** {md(plan.get('strategy_summary'), '当前不建立详情页改版方案。')}",
                f"- **原因或边界：** {md(plan.get('boundary'), '需要先补齐可读详情页资料。')}",
            ]
        )

    modules = [item for item in plan.get("modules", []) if isinstance(item, dict)]
    modules.sort(key=lambda item: safe_order(item.get("sequence")))
    route = " → ".join(
        str(item).strip() for item in plan.get("narrative_route", []) if str(item).strip()
    )
    lines = [
        f"- **详情页整体任务：** {md(plan.get('strategy_summary'), '尚未形成详情页整体方案')}",
        f"- **新版讲述路线：** {route or '尚未形成新版讲述路线'}",
        "",
        "> 下表按用户购买问题组织内容章节，不代表一章只能做成一张长图。设计可根据阅读节奏做成连续多个画面，但每章要完成的判断必须保持完整。",
        "",
        "| 顺序 | 新版内容章节 | 用户此时要确认什么 | 页面必须给出的答案 | 必须包含 | 可调用现有内容 | 呈现方向 | 还需准备 | 完成标准 |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in modules:
        lines.append(
            "| {sequence} | {name} | {question} | {answer} | {required} | {assets} | {direction} | {material} | {acceptance} |".format(
                sequence=md(item.get("sequence")),
                name=md(item.get("module_name")),
                question=md(item.get("user_question")),
                answer=md(item.get("page_answer")),
                required=md(item.get("required_content")),
                assets=md(item.get("source_asset_summary"), "暂无可直接调用内容"),
                direction=md(item.get("presentation_direction")),
                material=md(item.get("material_needed")),
                acceptance=md(item.get("acceptance_check")),
            )
        )
    if not modules:
        lines.append("| — | 暂未形成内容章节 | — | — | — | — | — | 先补齐详情页资料 | 暂不启动详情页改版 |")
    return "\n".join(lines)


def detail_asset_migration_table(chain: dict[str, Any]) -> str:
    """Show how current detail content is reused without turning it into per-image advice."""
    plan = chain.get("detail_page_plan", {}) if isinstance(chain, dict) else {}
    if not isinstance(plan, dict):
        return "当前没有可迁移的详情页内容。"
    migrations = [item for item in plan.get("asset_migration", []) if isinstance(item, dict)]
    if not migrations:
        return "当前没有可迁移的详情页内容；补齐可读详情页后再建立素材去向。"
    modules = {
        str(item.get("module_id", "")): str(item.get("module_name", ""))
        for item in plan.get("modules", [])
        if isinstance(item, dict)
    }
    rows = [
        "| 现有内容 | 新版怎么安排 | 放到新版哪里 | 执行说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in migrations:
        destinations = [
            modules.get(str(module_id), str(module_id))
            for module_id in item.get("destination_module_ids", [])
            if str(module_id).strip()
        ]
        rows.append(
            f"| {md(item.get('current_content'))} | {DETAIL_HANDLING_LABELS.get(str(item.get('handling')), md(item.get('handling')))} | "
            f"{md(destinations, '不进入新版页面')} | {md(item.get('execution_note'))} |"
        )
    return "\n".join(rows)


def validation_sections(validations: list[dict[str, Any]]) -> str:
    if not validations:
        return "当前不强行建立版本实验；先完成页面动作并保留版本。"
    lines: list[str] = []
    for index, item in enumerate(validations, start=1):
        lines.extend(
            [
                f"### 观察问题 {index}",
                "",
                f"- 要比较：{md(item.get('version_a'))} 与 {md(item.get('version_b'))}",
                f"- 其他条件保持不变：{md(item.get('must_keep'))}",
                f"- 只改变：{md(item.get('single_variable'))}",
                f"- 重点观察：{md(item.get('observation_needed'))}",
                f"- 怎样保证结果可比：{md(item.get('comparability'))}",
                f"- 不能据此证明：{md(item.get('boundary'))}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def build_professional_02(data: dict[str, Any]) -> str:
    status = str(data["manifest"].get("run_status", ""))
    title = "# 商品页改版执行方案"
    notice = "> 下面把整体方案拆成可以直接分工的主图、交易区和详情页改版项目。"
    if status == "degraded_no_product_value":
        notice = "> 本轮只使用现有页面依据：可以重排、删减、澄清和核实，但不得新增资料外卖点。"
    elif status == "stopped":
        title = "# 商品页改版执行方案（暂不启动页面修改）"
        notice = "> 当前资料不足以继续页面工作。本页只保留停止边界和补资料方向。"
    return brand_language("\n".join(
        [
            title,
            "",
            "> 方法：by 布兰德老白 BrandBAI",
            "",
            notice,
            "",
            "## 先看这次怎么改",
            "",
            brand_scope_summary(data["manifest"], data["chain"]),
            "",
            rebuild_strategy_section(data["chain"]),
            "",
            "## 改版项目先做什么",
            "",
            brand_priority_table(data["actions"], root_title_lookup(data["chain"])),
            "",
            "## 1｜主图怎么改",
            "",
            component_table(data["components"], "main_images"),
            "",
            "## 2｜交易区是否需要调整",
            "",
            transaction_section(data["chain"]),
            "",
            "## 3｜详情页整体怎么改",
            "",
            detail_page_content_map(data["chain"]),
            "",
            "### 现有详情内容在新版中的安排",
            "",
            detail_asset_migration_table(data["chain"]),
            "",
            "## 4｜上线后怎么判断是否有效",
            "",
            validation_sections(data["validation"]),
            "",
            "## 5｜执行边界",
            "",
            "- 页面已有结构优化可以使用页面可见依据；新增主张必须调用可核验补充资料。",
            "- 动态交易信息发布前必须人工复核当前有效性。",
            "- 视觉创作不得扩大功效、跨SKU或把待验证建议写成效果事实。",
        ]
    ))


def transaction_section(chain: dict[str, Any]) -> str:
    plan = chain.get("transaction_panel_plan", {}) if isinstance(chain, dict) else {}
    if not isinstance(plan, dict):
        plan = {}
    status = str(plan.get("status", "unknown"))
    if status in {"insufficient_material", "not_in_scope", "stopped"}:
        return "\n".join(
            [
                f"- **本次安排：** {md(plan.get('strategy_summary'), '当前不建立交易区改版方案。')}",
                f"- **原因或边界：** {md(plan.get('boundary'), '需要先补齐可读交易区资料。')}",
            ]
        )

    if status == "preserve_only":
        return "\n".join(
            [
                "### 本轮保持现状",
                "",
                "- **判断：** 当前交易区能够支持用户完成选择，本轮不单独立项修改。",
                f"- **建议保留：** {md(plan.get('strategy_summary'), '保持现有规格选择与到手信息结构。')}",
                f"- **页面结构：** {md(plan.get('capability_summary'), '保持当前可实施结构。')}",
                "",
                "### 长期商品信息与当前优惠分开呈现",
                "",
                f"- **长期保持稳定：** {md(plan.get('fixed_information'), '尚未确认')}",
                f"- **发布前更新：** {md(plan.get('dynamic_information'), '尚未确认')}",
                f"- **执行边界：** {md(plan.get('boundary'), '价格、赠品和库存发布前复核。')}",
            ]
        )

    route = " → ".join(
        str(item).strip() for item in plan.get("selection_route", []) if str(item).strip()
    )
    groups = [item for item in plan.get("field_groups", []) if isinstance(item, dict)]
    groups.sort(key=lambda item: safe_order(item.get("sequence")))
    lines = [
        f"- **交易区要完成：** {md(plan.get('strategy_summary'), '尚未形成交易区整体方案')}",
        f"- **页面结构：** {md(plan.get('capability_summary'), '尚未确认交易区结构')}",
        f"- **用户在同一组选项里这样判断：** {route or '尚未形成阅读顺序'}",
        "",
    ]
    for item in groups:
        lines.extend(
            [
                f"### 一个主要规格选择区｜{md(item.get('group_name'))}",
                "",
                f"- **用户要决定：** {md(item.get('user_question'))}",
                f"- **当前页面：** {md(item.get('current_expression'))}",
                f"- **同一组选项怎么写：** {md(item.get('recommended_structure'))}",
                f"- **选中以后怎么显示：** {md(item.get('current_selection_display'))}",
                f"- **到手与优惠：** {md(item.get('actual_receipt_and_offer'))}",
                f"- **页面怎么落地：** {md(item.get('implementation_path'))}",
                f"- **还需准备：** {md(item.get('material_needed'))}",
                f"- **完成标准：** {md(item.get('acceptance_check'))}",
                "",
            ]
        )
    if not groups:
        lines.append("暂未形成选择方案；先补齐交易区资料，再启动交易区改版。")
    lines.extend(
        [
            "",
            "### 长期商品信息与当前优惠分开呈现",
            "",
            f"- **长期保持稳定：** {md(plan.get('fixed_information'), '尚未确认')}",
            f"- **发布前更新：** {md(plan.get('dynamic_information'), '尚未确认')}",
            f"- **执行边界：** {md(plan.get('boundary'), '价格、赠品和库存发布前复核。')}",
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
        }
    else:
        raise ValueError("delivery_mode 必须是 course 或 professional")
    if write:
        for name, content in outputs.items():
            write_text(delivery / name, content)
        if mode == "professional":
            for name in LEGACY_PROFESSIONAL_REPORTS:
                legacy = delivery / name
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
