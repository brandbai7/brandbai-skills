"""Build the two human-readable reports from the structured product-value ledgers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from product_value_common import delivery_paths, md, read_json, read_jsonl, write_text


STATUS_ZH = {
    "draft": "工作中",
    "complete": "已完成",
    "partial": "部分完成",
    "insufficient": "资料不足",
    "stale": "已失效",
    "ready": "可正式调用",
    "conditional": "有条件调用",
    "blocked": "禁止下游调用",
    "P0-CANDIDATE": "候选中",
    "P0-HYPOTHESIS": "优先验证假设",
    "P0-SELECTED": "当前业务选择",
    "P0-VALIDATING": "验证中",
    "P0-BOUNDARY-VALIDATED": "边界内已验证",
    "P0-REOPEN": "重新评估",
    "P0-REPLACED": "已替代",
    "P0-STOPPED": "已停止",
    "main": "主识别锚",
    "supporting": "辅助识别锚",
    "active": "当前有效",
    "candidate": "候选",
    "confirmed": "当前有效",
    "unverified": "未核验",
    "conflict": "存在冲突",
    "superseded": "已替代",
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
    "open": "待补充",
    "resolved": "已解决",
    "deferred": "暂缓",
    "P0": "核心价值 P0",
    "P1": "购买支撑 P1",
    "P2": "信任与买前确认 P2",
    "page_supported": "页面直接支持",
    "reasoned": "合理推导",
    "to_validate": "待验证",
    "document": "文档/PDF",
    "image": "详情页图片",
    "page": "商品页面",
    "mixed": "混合资料",
    "link": "网页链接",
    "packaging": "商品包装",
    "brief": "商品或品牌资料",
    "evidence": "证据资料",
    "feedback": "用户反馈",
    "spreadsheet": "表格资料",
    "incremental": "增量资料",
    "product_page_images": "商品详情页图片组",
    "product_page_image": "商品详情页图片",
    "product_info_area": "商品信息区",
    "dynamic_promotion_graphic": "动态活动信息图",
    "time_bound": "时点有效",
    "product_page_pdf": "商品详情页 PDF",
    "promotion_banner": "活动信息图",
    "detail_page_image": "商品详情页图片",
    "embedded_evidence_image": "内嵌证据图片",
    "certification_claim_graphic": "认证宣称图片",
    "current": "当前有效",
    "page_embedded": "页面内嵌",
    "inferred_from_page": "页面推断",
    "current_expression": "当前表达",
    "F-PAGE": "页面事实",
    "F-EVIDENCE": "证据资料",
    "STRAT": "品牌战略",
    "DYN": "动态交易",
    "U": "用户原声",
    "EX": "页面表达",
    "H": "分析推导",
    "FC0": "商品事实不足",
    "FC1": "商品事实初步可用",
    "FC2": "商品事实较完整",
    "FC3": "商品事实完整且有多源核对",
    "SC0": "暂无战略信息",
    "SC1": "有初步方向",
    "SC2": "战略信息较完整",
    "SC3": "战略信息完整且已验证",
    "PKG-L0": "当前不可用",
    "PKG-L1": "仅可补资料",
    "PKG-L2": "可形成初步底座",
    "PKG-L3": "可形成有条件底座",
    "PKG-L4": "可正式调用",
}

INTERNAL_ID = r"(?:PV-[0-9a-f]{12}|(?:SF|SRC|ID|ANCHOR|FABE|CLM|STRAT|DYN|EX|GAP|P0D|F|U|H|V)-\d{3,})"
INTERNAL_ID_RE = re.compile(rf"(?<![A-Za-z0-9]){INTERNAL_ID}(?![A-Za-z0-9])")
INTERNAL_ID_GROUP_RE = re.compile(rf"\(\s*{INTERNAL_ID}(?:\s*[,/;+、，]\s*{INTERNAL_ID})*\s*\)")
SHARED_ID_SERIES = r"(?:SF|SRC|ID|ANCHOR|FABE|CLM|STRAT|DYN|EX|GAP|P0D|F|U|H|V)-\d{3,}(?:\s*/\s*\d{3,})+"
SHARED_ID_SERIES_RE = re.compile(rf"(?<![A-Za-z0-9]){SHARED_ID_SERIES}(?![A-Za-z0-9])")


def public_text(value: Any, empty: str = "未提供") -> str:
    """Hide internal IDs without leaving punctuation fragments in human reports."""

    text = md(value, empty)
    text = re.sub(rf"{SHARED_ID_SERIES}\s*的\s*A\s*层", "相关价值的 A 层", text, flags=re.IGNORECASE)
    text = re.sub(rf"{SHARED_ID_SERIES}\s*的\s*reference_frame", "相关价值的参照系", text, flags=re.IGNORECASE)
    text = re.sub(
        rf"对应的?回答已登记为\s*{INTERNAL_ID}(?![A-Za-z0-9])",
        "对应回答已在相关事实中登记",
        text,
    )
    text = re.sub(rf"(?:参见|见)\s*{INTERNAL_ID}(?![A-Za-z0-9])", "", text)
    text = re.sub(rf"相比\s*{INTERNAL_ID}(?![A-Za-z0-9])", "与其他候选相比", text)
    text = re.sub(rf"(?<![A-Za-z0-9]){INTERNAL_ID}(?![A-Za-z0-9])的", "", text)
    text = INTERNAL_ID_GROUP_RE.sub("", text)
    text = SHARED_ID_SERIES_RE.sub("", text)
    text = INTERNAL_ID_RE.sub("", text)
    text = re.sub(r"[（(]\s*[,/;+、，;；:：\s]*[)）]", "", text)
    text = re.sub(r"([（(])\s*[,/;+、，;；:：]+\s*", r"\1", text)
    text = re.sub(r"\s*[,/;+、，;；:：]+\s*([)）])", r"\1", text)
    text = re.sub(r"基于\s*[,/;+、，;；:：]*\s*推导", "综合资料推导", text)
    text = re.sub(r"^[,/;+、，;；:：\s]+", "", text)
    text = re.sub(r"^\s*>\s*", "", text)
    text = re.sub(r"([；;])\s*>\s*", r"\1", text)
    confidence_labels = {"high": "原件级", "medium": "页面截图级", "low": "低可信度"}
    text = re.sub(
        r"证据细节可信度\s*=\s*(high|medium|low)",
        lambda match: f"证据细节可信度：{confidence_labels[match.group(1).lower()]}",
        text,
        flags=re.IGNORECASE,
    )
    sku_labels = {"confirmed": "已确认", "partial": "部分确认", "unverified": "待确认"}
    text = re.sub(
        r"sku_status\s*=\s*(confirmed|partial|unverified)",
        lambda match: f"SKU状态：{sku_labels[match.group(1).lower()]}",
        text,
        flags=re.IGNORECASE,
    )
    replacements = {
        "HYPOTHESIS": "优先验证假设",
        "SELECTED": "当前业务选择",
        "VALIDATING": "验证中",
        "evidence_detail_confidence": "证据细节可信度",
        "exact_fields_verified": "精确字段已核验",
        "source_inventory.jsonl": "来源文件清单",
        "source_claim_ledger.jsonl": "原文主张账本",
        "sku_status=partial": "SKU 状态为部分确认",
        "high confidence": "原件级证据",
        "medium confidence": "页面截图级证据",
        "medium置信度": "页面截图可确认",
        "high置信度": "原件级证据",
        "low置信度": "低可信度证据",
        "low confidence": "低可信度证据",
        "exact fields unverified": "精确字段未核验",
        "dietary": "饮食",
        "snapshot_only": "仅代表当前时点",
        "current_listing": "当前公开商品页",
        "reference_frame": "参照系",
        "P0-BOUNDARY-VALIDATED": "边界内已验证",
        "P0-REOPEN": "重新评估",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    status_words = {
        "verified": "已核验",
        "unverified": "未核验",
        "active": "当前有效",
        "expired": "已过期",
        "template": "模板状态",
        "deferred": "暂缓",
        "blocked": "禁止调用",
        "conditional": "有条件调用",
        "ready": "可正式调用",
        "stale": "已失效",
    }
    for source, target in status_words.items():
        text = re.sub(rf"(?<![A-Za-z0-9_]){source}(?![A-Za-z0-9_])", target, text, flags=re.IGNORECASE)
    text = re.sub(r"[（(]\s*(?:→\s*)+[)）]", "", text)
    text = re.sub(r"→\s*→+", "→", text)
    text = re.sub(r"/{2,}\s*(?:reference_frame|参照系)", "参照系", text, flags=re.IGNORECASE)
    text = re.sub(r"对应的?回答已登记为\s*[。.]", "对应回答尚未形成可公开结论。", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def public_bullet_lines(values: Any, empty: str = "暂无") -> str:
    items: list[str] = []
    for value in values:
        item = public_text(value, "").strip()
        if item:
            items.append(item)
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def gap_priority_label(value: Any) -> str:
    return {
        "P0": "最高 P0",
        "P1": "高 P1",
        "P2": "中 P2",
        "P3": "低 P3",
    }.get(str(value), label(value))


def sku_status_label(value: Any) -> str:
    return {
        "confirmed": "已确认",
        "partial": "部分确认",
        "unverified": "待确认",
    }.get(str(value), label(value))


def label(value: Any) -> str:
    return STATUS_ZH.get(str(value), md(value))


def table(headers: list[str], rows: list[list[Any]], empty: str = "暂无记录") -> str:
    if not rows:
        return f"_{empty}_"
    header = "| " + " | ".join(headers) + " |"
    divider = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(public_text(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def load_delivery(delivery: Path) -> dict[str, Any]:
    paths = delivery_paths(delivery)
    return {
        "paths": paths,
        "manifest": read_json(paths["manifest"]),
        "source_inventory": read_jsonl(paths["source_inventory"]),
        "audit_card_ledger": read_jsonl(paths["audit_card_ledger"]),
        "source_observations": read_jsonl(paths["source_observations"]),
        "source_claims": read_jsonl(paths["source_claims"]),
        "sources": read_jsonl(paths["sources"]),
        "facts": read_jsonl(paths["facts"]),
        "fabe": read_jsonl(paths["fabe"]),
        "anchors": read_jsonl(paths["anchors"]),
        "values": read_jsonl(paths["values"]),
        "decision": read_json(paths["decision"]),
        "gaps": read_jsonl(paths["gaps"]),
    }


def build_report_01(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    facts = data["facts"]
    fabe = data["fabe"]
    values = data["values"]
    decision = data["decision"]
    facts_by_id = {item.get("fact_id"): item for item in facts}
    values_by_id = {item.get("value_id"): item for item in values}
    fabe_by_value: dict[str, list[dict[str, Any]]] = {}
    for item in fabe:
        fabe_by_value.setdefault(str(item.get("value_id")), []).append(item)
    recommended = values_by_id.get(decision.get("recommended_value_id"), {})

    p0_statement = recommended.get("value_statement") or "尚未形成可交付的核心价值"
    p0_heading = "优先验证的核心价值" if decision.get("status") in {
        "P0-CANDIDATE",
        "P0-HYPOTHESIS",
        "P0-VALIDATING",
        "P0-REOPEN",
    } else "当前核心价值"
    p0_note = decision.get("public_rationale") or "当前资料尚不足以形成明确判断。"
    limitations = list(dict.fromkeys(list(manifest.get("limitations") or [])))
    cannot_prove = list(dict.fromkeys(list(decision.get("cannot_prove") or [])))

    def visible_value(item: dict[str, Any]) -> bool:
        return item.get("layer") != "deferred" and item.get("downstream_readiness") != "blocked"

    anchors_rows = [
        [label(item.get("anchor_type")), item.get("statement"), label(item.get("status")), item.get("boundary")]
        for item in data["anchors"]
    ]
    task_rows = []
    for item in values:
        if not visible_value(item):
            continue
        chain = (fabe_by_value.get(str(item.get("value_id"))) or [{}])[0]
        task_rows.append(
            [
                label(item.get("layer")),
                item.get("user_task"),
                chain.get("reference_frame"),
                chain.get("user_language"),
                item.get("scope"),
            ]
        )

    fabe_rows = []
    for item in values:
        if not visible_value(item):
            continue
        for chain in fabe_by_value.get(str(item.get("value_id"))) or []:
            fabe_rows.append(
                [
                    label(item.get("layer")),
                    chain.get("feature"),
                    chain.get("advantage"),
                    chain.get("benefit"),
                    chain.get("evidence"),
                    chain.get("user_language"),
                    f"{chain.get('reference_frame')}；{label(chain.get('derivation_status'))}；{chain.get('boundary')}",
                ]
            )
    value_rows = [
        [
            label(item.get("layer")),
            item.get("value_statement"),
            item.get("user_task"),
            label(item.get("strategic_potential")),
            label(item.get("execution_maturity")),
            label(item.get("downstream_readiness")),
        ]
        for item in values
        if visible_value(item)
    ]
    candidate_rows = []
    for value_id in decision.get("candidate_value_ids") or []:
        item = values_by_id.get(value_id, {})
        not_selected_reasons = [public_text(reason, "") for reason in (item.get("cannot_prove") or [])]
        not_selected_reasons = [reason for reason in not_selected_reasons if reason]
        current_role = "当前推荐" if value_id == decision.get("recommended_value_id") else f"候选｜当前{label(item.get('layer'))}"
        selection_note = (
            public_text(p0_note)
            if value_id == decision.get("recommended_value_id")
            else "当前未选为核心价值：" + ("；".join(not_selected_reasons) or "仍需补充比较依据")
        )
        candidate_rows.append(
            [
                item.get("value_statement"),
                label(item.get("strategic_potential")),
                label(item.get("execution_maturity")),
                current_role,
                selection_note,
            ]
        )

    p1_values = [item for item in values if item.get("layer") == "P1" and visible_value(item)]
    p2_values = [item for item in values if item.get("layer") == "P2" and visible_value(item)]
    dyn_facts = [item for item in facts if item.get("fact_type") == "DYN"]
    anchor_summary = "；".join(str(item.get("statement")) for item in data["anchors"]) or "尚未形成识别锚"
    p1_summary = "；".join(str(item.get("value_statement")) for item in p1_values) or "暂无购买支撑"
    p2_summary = "；".join(str(item.get("value_statement")) for item in p2_values) or "暂无信任与买前确认价值"
    dyn_summary = "；".join(str(item.get("statement")) for item in dyn_facts) or "当前未登记动态交易信息"
    role_rows = [
        ["核心价值", p0_statement, "最值得优先验证、最可能影响选择；当前仍继承P0状态与资料边界"],
        ["商品识别锚", anchor_summary, "负责让用户认出商品，不自动成为购买理由"],
        ["购买支撑", p1_summary, "负责解释适配、使用、性能或便利，不与核心价值抢同一角色"],
        ["信任与买前确认", p2_summary, "负责降低顾虑、选对商品和理解证据，不把检测或参数直接当P0"],
        ["当前交易信息", dyn_summary, "只回答当前怎么买、到手什么；绑定时点，不固化为长期价值"],
    ]

    application_rows = [
        ["种草", "让用户觉得核心利益与自己有关", "核心价值 + 真实场景", "取决于目标人群、账号和场景输入"],
        ["直播引流短视频", "给用户一个进房继续了解的理由", "用户问题 + 核心价值", "取决于直播承接与进房目标"],
        ["挂车成交短视频", "让用户看懂为什么选、值不值", "核心价值 + P1购买支撑 + 当前交易信息", "取决于SKU、落地页和交易条件"],
        ["直播间", "演示核心体验并处理购买顾虑", "核心价值演示 + P2信任与买前确认", "取决于商品卡、货盘和话术输入"],
        ["商品页", "认出商品、理解价值并选对SKU", "识别锚 + 核心价值 + P2信任与买前确认", "可先用于页面诊断；具体呈现交后续Skill"],
    ]
    next_steps = [
        f"{item.get('missing')}；最低需要：{item.get('minimum_needed')}"
        for item in data["gaps"]
        if item.get("priority") in {"P0", "P1"} and item.get("state") == "open"
    ][:5]

    return f"""# 商品价值底座｜{md(manifest.get('brand'))} {md(manifest.get('product'))}

> 这是什么、为什么值得选、凭什么信

## 1｜一页结论

- 当前商品：{public_text(manifest.get('brand'))} {public_text(manifest.get('product'))}
- 当前 SKU/版本：{public_text(manifest.get('sku'))}
- SKU 确认状态：{sku_status_label(manifest.get('sku_status'))}
- SKU 确认依据：{public_text(manifest.get('sku_basis'))}
- 品类：{public_text(manifest.get('category'))}
- 分析状态：{label(manifest.get('analysis_status'))}
- 下游状态：{label(manifest.get('delivery_status'))}
- {p0_heading}：{public_text(p0_statement)}
- 当前 P0 状态：{label(decision.get('status'))}
- 决策说明：{public_text(p0_note)}
- 当前执行主轴：{public_text(decision.get('current_execution_axis'), '尚未确定')}

> “完成”只表示已对本次输入完成商品价值建模，不表示功效、竞争优势、用户心智或成交效果已获得独立验证。

## 2｜商品身份与识别锚

{table(['类型', '识别锚', '状态', '边界'], anchors_rows, '尚未形成识别锚')}

识别锚只负责让用户下次认出商品，不自动等于核心购买理由。

## 3｜用户问题与购买决策

没有真实用户资料时，本节是基于商品资料形成的待验证用户问题，不写成已经获得用户共识。

{table(['价值角色', '用户问题/任务', '当前替代或参照', '用户语言', '适用范围'], task_rows, '尚未形成可用用户任务')}

## 4｜FABE价值证据链

FABE 用来把“商品有什么”翻译成“为什么对用户有意义”。参数、成分、工艺和检测不能跳过中间推导直接冒充用户利益。

{table(['价值角色', 'Feature 商品事实', 'Advantage 带来的优势', 'Benefit 用户利益', 'Evidence 当前依据', '用户怎么理解', '参照、状态与边界'], fabe_rows, '尚未形成完整FABE推导')}

## 5｜商品价值分层

P0 是优先记住和选择的核心价值，P1 帮助理解与完成选择，P2 负责提供信任与解除顾虑；`暂缓` 表示当前证据不足，不得进入正式表达。

{table(['价值角色', '用户价值', '主要用户任务', '战略潜力', '执行成熟度', '下游准备度'], value_rows, '资料不足，尚未形成可靠价值')}

## 6｜为什么选这个核心价值

### 核心价值候选比较

{table(['候选价值', '战略潜力', '执行成熟度', '当前角色', '分层说明'], candidate_rows, '尚未建立 P0 候选池')}

### 身份、识别、价值、信任与交易为什么不能混在一层

{table(['角色', '当前内容', '为什么这样分层'], role_rows)}

## 7｜条件式下游应用地图

{table(['经营任务', '内容先完成什么', '优先调用的商品价值', '当前能否正式执行'], application_rows)}

- 输出版本：{public_text(manifest.get('output_version'))}
- 交付状态：{label(manifest.get('delivery_status'))}
- 下游只能继承本底座中的事实、价值、P0 状态、适用范围和限制。
- 下游不得把“优先验证假设”改写成“消费者已经认可”，也不得扩大功效、比较和适用范围。
- 具体卖点如何被看见、听见和感受到，由后续“BrandBAI 卖点呈现”Skill 完成。

## 8｜当前状态与下一步

### 仍需验证的问题

{public_bullet_lines(decision.get('validation_questions') or [], '暂无；若尚未形成P0，应先补齐资料')}

### 当前边界

{public_bullet_lines(limitations, '暂无额外限制；仍须遵守原始证据范围')}

### 当前资料不能证明

{public_bullet_lines(cannot_prove, '暂无额外未证事项；仍不得超出已登记事实')}

### 优先补充资料

{public_bullet_lines(next_steps, '暂无高优先级补充项')}
"""


def build_report_02(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    source_rows = [
        [
            label(item.get("source_type")),
            item.get("title"),
            item.get("locator"),
            item.get("sku_scope"),
            label(item.get("status")),
        ]
        for item in data["sources"]
    ]
    fact_rows = [
        [
            label(item.get("fact_type")),
            item.get("statement"),
            label(item.get("status")),
            item.get("boundary"),
        ]
        for item in data["facts"]
    ]
    gap_rows = [
        [
            item.get("category"),
            item.get("missing"),
            item.get("impact"),
            item.get("minimum_needed"),
            gap_priority_label(item.get("priority")),
            label(item.get("state")),
        ]
        for item in data["gaps"]
    ]
    can_do = []
    if data["facts"]:
        can_do.append("引用本次已登记且状态有效的商品事实，并保留 SKU、时间和来源边界。")
        can_do.append("将与当前商品和 SKU 明确对应的公开详情页内容，直接作为商品价值和当前公开卖点的有效依据。")
    if data["values"]:
        can_do.append("在原层级和准备度范围内调用已登记价值。")
    if manifest.get("delivery_status") == "ready":
        can_do.append("将当前版本作为后续卖点呈现或商品匹配的正式上游输入。")
    elif manifest.get("delivery_status") == "conditional":
        can_do.append("在继承全部缺口和限制的前提下，进行有限的下游调用。")

    cannot_do = [
        "公开商品页可以直接支撑当前商品价值，但不能把它改写成第三方独立验证结论。",
        "不能把 STRAT、U 或 H 自动写成已证实的商品事实或用户共识。",
        "不能混用其他 SKU、历史版本或过期交易权益。",
        "不能在本阶段生成画面、脚本、Brief 或达人匹配结论。",
        *(manifest.get("limitations") or []),
    ]
    return f"""# {md(manifest.get('brand'))}｜{md(manifest.get('product'))} 资料说明与缺口

## 商品与版本

- 商品：{public_text(manifest.get('brand'))} {public_text(manifest.get('product'))}
- 品类：{public_text(manifest.get('category'))}
- 当前 SKU/版本：{public_text(manifest.get('sku'))}
- SKU 确认状态：{sku_status_label(manifest.get('sku_status'))}
- SKU 确认依据：{public_text(manifest.get('sku_basis'))}
- 输入形态：{label(manifest.get('input_mode'))}
- 资料包版本：{md(manifest.get('package_version'))}
- 输出版本：{md(manifest.get('output_version'))}
- 分析状态：{label(manifest.get('analysis_status'))}
- 下游状态：{label(manifest.get('delivery_status'))}

## 输入成熟度

- 商品事实完整度：{label(manifest.get('fc'))}
- 战略信息完整度：{label(manifest.get('sc'))}
- 综合可用程度：{label(manifest.get('pkg_level'))}

成熟度只描述本次输入的可用程度，不表示商品真实效果、竞争优势或市场表现。

## 已读取来源

{table(['来源类型', '标题', '定位', '适用 SKU', '状态'], source_rows, '尚未登记可回溯来源')}

## 已确认事实、冲突与待复核

{table(['类型', '内容', '状态', '表达边界'], fact_rows, '尚未登记可回溯事实')}

## 资料缺口及影响

{table(['类别', '缺少什么', '影响', '最低补充', '优先级', '状态'], gap_rows, '当前未登记资料缺口')}

## 当前可以做

{public_bullet_lines(can_do, '资料不足，仅可补充和核对输入')}

## 当前不能做

{public_bullet_lines(cannot_do)}

## 增量资料与版本说明

- 新增商品页、SKU、证据、战略输入或用户资料时，应先更新结构化底稿，再重新生成两份普通版。
- 如果新增资料挑战当前核心价值，应将旧版本标记为已失效，并重新评估核心价值，不得静默覆盖。
- 当前更新时间：{md(manifest.get('updated_at'))}
"""


def build_delivery(delivery: Path, write: bool = True) -> dict[str, Any]:
    data = load_delivery(delivery)
    report_01 = build_report_01(data)
    report_02 = build_report_02(data)
    result = {
        "status": "built" if write else "dry_run",
        "delivery": str(delivery.resolve()),
        "counts": {
            "source_files": len(data["source_inventory"]),
            "audit_cards": sum(1 for item in data["audit_card_ledger"] if item.get("status") == "ready"),
            "source_observations": len(data["source_observations"]),
            "source_claims": len(data["source_claims"]),
            "sources": len(data["sources"]),
            "facts": len(data["facts"]),
            "fabe": len(data["fabe"]),
            "anchors": len(data["anchors"]),
            "values": len(data["values"]),
            "gaps": len(data["gaps"]),
        },
        "reports": [str(data["paths"]["report_01"]), str(data["paths"]["report_02"])],
    }
    if write:
        write_text(data["paths"]["report_01"], report_01)
        write_text(data["paths"]["report_02"], report_02)
    return result


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
