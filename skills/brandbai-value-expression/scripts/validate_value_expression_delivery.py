"""Validate a BrandBAI Value Expression delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from build_value_expression_report import build_report_01, build_report_02
from value_expression_common import (
    ACTIVE_VALUE_LAYERS,
    ANALYSIS_STATUSES,
    ASSET_GROUPS,
    CONTENT_OBJECTS,
    DECISION_TASKS,
    DELIVERY_STATUSES,
    EXPRESSION_ORIGINS,
    EXPRESSION_SOURCE_FORMS,
    EXPRESSION_STATUSES,
    ROUTES,
    ROUTE_ROLES,
    SCHEMA_VERSION,
    SKILL_VERSION,
    SLOT_STATUSES,
    TEST_STATUSES,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    VIS_STATUSES,
    delivery_paths,
    read_json,
    read_jsonl,
    value_expression_id,
)


MANIFEST_FIELDS = {
    "schema_version", "skill_version", "value_expression_id", "product_value_id",
    "brand", "product", "category", "sku", "upstream_output_version",
    "output_version", "source_materials", "analysis_status", "delivery_status",
    "limitations", "created_at", "updated_at",
}
UPSTREAM_FIELDS = {
    "product_value_id", "upstream_output_version", "upstream_updated_at",
    "upstream_analysis_status", "upstream_delivery_status", "decision_id",
    "p0_status", "recommended_value_id", "source_delivery_name",
    "source_materials_name", "values", "fact_ids", "facts", "expression_ids",
    "anchor_ids", "file_hashes", "captured_at",
}
EXISTING_FIELDS = {
    "expression_id", "expression_origin", "source_form", "value_ids", "fact_ids",
    "source_statement", "source_id", "locator", "page_says", "page_shows",
    "current_perception", "reusable", "gap", "status", "boundary",
}
PATH_FIELDS = {
    "scan_id", "value_id", "route", "role", "translation", "reason",
    "fact_ids", "expression_ids", "boundary",
}
SLOT_FIELDS = {
    "slot_id", "slot_number", "asset_group", "slot_name", "status",
    "reason", "vis_ids",
}
VIS_FIELDS = {
    "vis_id", "value_id", "secondary_value_ids", "asset_group", "slot_number",
    "user_question", "target_perception", "decision_task", "primary_route",
    "supporting_routes", "fact_ids", "expression_ids", "human_language",
    "visual_track", "action_track", "sound_track", "subtitle_track",
    "prop_track", "scene_track", "effect_bgm_track", "commerce_handoff_track",
    "must_keep", "variable_parts", "misuse", "applicable_objects",
    "must_preserve_tracks", "adaptable_tracks", "validation_status", "boundary",
    "external_priority",
}
VALIDATION_FIELDS = {
    "test_id", "vis_ids", "validation_task", "must_keep", "single_variable",
    "control_version", "test_version", "primary_metrics", "measurement_method",
    "decision_rule", "writeback", "status", "requirements", "boundary",
}
GAP_FIELDS = {"gap_id", "category", "missing", "impact", "minimum_needed", "priority", "state"}
TRACK_FIELDS = (
    "visual_track", "action_track", "sound_track", "subtitle_track", "prop_track",
    "scene_track", "effect_bgm_track", "commerce_handoff_track",
)
SLOT_GROUPS = {
    "01": "欲望建立", "02": "欲望建立", "03": "欲望建立", "04": "欲望建立",
    "05": "欲望建立", "06": "欲望建立", "07": "欲望建立", "08": "欲望建立",
    "09": "阻力解除", "10": "阻力解除", "11": "阻力解除", "12": "氛围连接",
}

EXACT_FIELD_PATTERNS = (
    re.compile(r"(?:GB\s*/\s*T|GB|ISO|FSSC)\s*-?\s*\d[0-9A-Za-z./-]*", re.IGNORECASE),
    re.compile(r"CNAS(?:[0-9A-Za-z./-]+)?", re.IGNORECASE),
    re.compile(r"(?:单位|限值|报告编号|签发日期|检测方法(?:标准)?)[：:\s]*[0-9A-Za-z.μµ/%°℃_-]+", re.IGNORECASE),
)
ORIGINAL_ASSET_RE = re.compile(r"(?:报告|证书|检测单|文件)原件|原始报告|原件报告")
SINGLE_PACK_CLAIM_RE = re.compile(
    r"(?:(?:一包|单包|一袋|单袋).{0,24}(?:全部|同时|五味|多种|内容物)|"
    r"(?:全部|同时|五味|多种|内容物).{0,24}(?:一包|单包|一袋|单袋))"
)
SUBTITLE_QUOTE_RE = re.compile(
    r"字幕(?:仅)?(?:写|为|保持)?[：:\s]*[\"'“‘]([^\"'”’]+)[\"'”’]"
)
VISUAL_EVIDENCE_VARIABLE_RE = re.compile(r"截图|证据画面|报告画面|证明画面")
PREARRANGED_RE = re.compile(r"预先?摆盘|预摆|提前摆盘")
SIGNIFICANCE_RE = re.compile(r"显著性?|p\s*值|p-value", re.IGNORECASE)
STATISTICAL_DESIGN_RE = re.compile(r"样本量|统计检验|显著性检验|置信区间|p\s*值|p-value", re.IGNORECASE)
NONEXISTENT_VISUAL_RE = re.compile(r"不得虚构([^。；\n]+?)(?:等)?实际不存在")
USAGE_SUPPORT_GROUPS = (
    (
        "使用周期或频次",
        re.compile(
            r"(?:使用)?周期|(?:使用)?频次|每日|每天|每周|每月|每隔\s*\d+\s*天|"
            r"连续\s*\d+\s*(?:天|周|个月|月)|\d+\s*(?:天|周|个月|月)(?:装|量|用量)?|"
            r"一周|整周|一个月|整月"
        ),
    ),
    (
        "补货或一次买够",
        re.compile(r"补货|囤货|一次买够|够(?:吃|喝|用)[^。；，,]{0,8}(?:一阵|一段时间|几天|一周|一个月)"),
    ),
)
SKU_BUNDLE_CONFLICT_RE = re.compile(
    r"(?:套组|装箱|清单|到手|内容|正装|件数).{0,48}(?:不一致|冲突|不完全一致|无法确认|待核对|待确认)|"
    r"(?:不一致|冲突|不完全一致|无法确认|待核对|待确认).{0,48}(?:套组|装箱|清单|到手|内容|正装|件数)"
)
HIGH_RISK_CONCEPT_PATTERNS = {
    "禁忌/孕哺": re.compile(r"孕妇|孕哺|哺乳期|禁忌|请勿使用|禁止使用|不适用人群"),
    "刺激/耐受": re.compile(r"刺激性?|不耐受|耐受性|过敏|致敏"),
    "稳定性/失活": re.compile(r"失活|稳定(?:性|度)?|活性保持|锁鲜"),
}
ACTUAL_SMELL_RE = re.compile(r"闻得到|闻得见|能闻到|闻起来|嗅得到|香气扑鼻")
SMELL_SUPPORT_RE = re.compile(r"闻|嗅|气味|香气|香味|飘香|扑鼻")
SMELL_DENIAL_PREFIX_RE = re.compile(
    r"(?:不|未|禁止|不得|不能|不可|避免|不要|不写|不使用|不声称|不扩写|不得写|不能写)"
    r"[^，。；;]{0,16}$"
)
GENERAL_DENIAL_PREFIX_RE = re.compile(
    r"(?:不|未|无|没有|禁止|不得|不能|不可|避免|不要|不写|不使用|不声称|不扩写|"
    r"不得写|不能写|不据此|不自行|不得自行)"
    r"[^，。；;\n]{0,24}$"
)
SIGNIFICANCE_DENIAL_PREFIX_RE = re.compile(
    r"(?:不写|不得写|不能写|不使用|不得使用|不声称|不宣称|不判断|不作|不做)"
    r"[^，。；;\n]{0,12}$"
)
SUFFICIENCY_SHORTCUT_RE = re.compile(
    r"(?:一瓶|这瓶|本品).{0,16}(?:就能|可以|能)?(?:全|都)?(?:搞定|解决)|"
    r"(?:一瓶|这瓶|本品)(?:全|都)?搞定"
)
SUFFICIENCY_SUPPORT_RE = re.compile(r"搞定|解决|满足|覆盖|全能|一瓶多用|多用途")
EXTERNAL_COMPARISON_RE = re.compile(
    r"(?:与|和|同).{0,28}(?:竞品|同类|普通|传统|其他品牌?|别家|市面(?:上的)?|行业(?:常见)?).{0,28}"
    r"(?:同框|对照|对比|相比|区别)|"
    r"(?:竞品|同类|普通|传统|其他品牌?|别家|市面(?:上的)?|行业(?:常见)?).{0,28}"
    r"(?:同框|对照|对比|相比|区别|而非|不是)"
)
EXTERNAL_COMPARISON_SUPPORT_RE = re.compile(
    r"竞品|同类|普通|传统|其他品牌?|别家|市面(?:上的)?|行业(?:常见)?|"
    r"对照|对比|相比|优于|区别于|不同于|而非|不是普通"
)
DISJUNCTIVE_VARIABLE_RE = re.compile(r"或|二选一|任选|任一|(?:A|B)之一", re.IGNORECASE)
VARIABLE_DIMENSION_PATTERNS = {
    "文字样式": re.compile(r"字号|字体|字重|文字大小|字幕大小|颜色|描边"),
    "出现节奏": re.compile(r"节奏|逐项出现|出现顺序|停留时长|切换时长|快慢"),
    "画面证据": re.compile(r"截图|标识|证据画面|报告画面|证明画面|包装画面|画面是否"),
    "动作": re.compile(r"动作|倒出|展开|按压|冲泡|搅拌|连续展示|一镜到底"),
    "声音": re.compile(r"声音|音效|旁白|口播|BGM|音乐", re.IGNORECASE),
    "场景": re.compile(r"场景|背景|地点|人物"),
    "信息结构": re.compile(r"分题|分屏|分段|时间轴|信息卡|排版结构"),
}
MANDATORY_GUARDRAIL_REMOVAL_RE = re.compile(
    r"不区分症状|不含(?:指导)?说明|"
    r"(?:不含|不保留|删除|删去|去掉|移除|不出现|省略).{0,18}"
    r"(?:说明书|医务人员指导|禁忌|注意事项|警示|不适宜人群|症状标签|适用边界)|"
    r"(?:说明书|医务人员指导|禁忌|注意事项|警示|不适宜人群|症状标签|适用边界).{0,18}"
    r"(?:不含|不保留|删除|删去|去掉|移除|不出现|省略)"
)
MANDATORY_CLAIM_QUALIFIER_REMOVAL_RE = re.compile(
    r"(?:无|不含|省略|删除|删去|去掉|移除|不出现|是否含).{0,18}"
    r"(?:实验条件下|仅限|限定语|适用条件|脚注)|"
    r"(?:实验条件下|仅限|限定语|适用条件|脚注).{0,18}"
    r"(?:无|不含|省略|删除|删去|去掉|移除|不出现|作为变量)"
)
ATOMIC_EXPRESSION_LABEL_RE = re.compile(
    r"(商品标题|产品名称|商品名称|品牌|品名|系列|厂名|生产企业|产地|"
    r"当前选择SKU\s*ID|当前选中规格|规格组|型号|净含量|单件净含量|包装规格|"
    r"配料表|配料|成分|营养成分表|能量|蛋白质|脂肪|碳水化合物|钠|钙|"
    r"保质期|贮存条件|储存条件|储存方法|生产许可证编号|生产许可证|"
    r"执行标准|标准编号|注册证号|备案编号|适用人群|不适宜人群|禁忌|"
    r"注意事项|警示语|使用方法|食用方法|饮用方法)\s*[:：]",
    re.IGNORECASE,
)
FOOTNOTE_DEFINITION_RE = re.compile(
    r"(?:^|[；;。\n])\s*(?P<marker>\*\d*|※\d*|注\s*\d*)\s*(?:数据来源|来源|注|说明|"
    r"检测|实验|测试|统计|依据|截至|结果|本页|页面)",
    re.IGNORECASE,
)
NUMBERED_FOOTNOTE_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\*\d+|※\d+|注\s*\d+)(?=$|[；;。,.，\s])",
    re.IGNORECASE,
)
PLAIN_FOOTNOTE_REFERENCE_RE = re.compile(r"(?<=[\u4e00-\u9fff\d%])\*(?=$|[；;。,.，\s])")
FOOTNOTE_BOUNDARY_RE = re.compile(r"脚注|限定语|限定条件|数据来源|页面原文")


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s:：,，;；()（）]+", "", text)


def normalized_footnote_marker(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def expression_footnote_references(value: Any) -> set[str]:
    text = str(value or "")
    definition_spans = [match.span() for match in FOOTNOTE_DEFINITION_RE.finditer(text)]
    markers = set()
    for match in NUMBERED_FOOTNOTE_REFERENCE_RE.finditer(text):
        if not any(start <= match.start() < end for start, end in definition_spans):
            markers.add(normalized_footnote_marker(match.group(0)))
    if PLAIN_FOOTNOTE_REFERENCE_RE.search(text):
        markers.add("*")
    return markers


def expression_footnote_definitions(value: Any) -> set[str]:
    return {
        normalized_footnote_marker(match.group("marker"))
        for match in FOOTNOTE_DEFINITION_RE.finditer(str(value or ""))
    }


def joined_text(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for field in fields:
        value = record.get(field, "")
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return "\n".join(parts)


def exact_field_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for pattern in EXACT_FIELD_PATTERNS:
        tokens.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(tokens))


def unsupported_exact_tokens(
    record: dict[str, Any],
    fields: tuple[str, ...],
    fact_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    linked = [fact_lookup[item] for item in map(str, list_value(record, "fact_ids")) if item in fact_lookup]
    if not any(item.get("exact_fields_verified") is False for item in linked):
        return []
    support_parts: list[str] = []
    for fact in linked:
        support_parts.append(str(fact.get("statement", "")))
        quotes = fact.get("source_quotes", [])
        if isinstance(quotes, list):
            support_parts.extend(str(item) for item in quotes)
    support = normalized(" ".join(support_parts))
    return [token for token in exact_field_tokens(joined_text(record, fields)) if normalized(token) not in support]


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def duplicate_ids(records: list[dict[str, Any]], key: str) -> list[str]:
    values = [str(item.get(key, "")) for item in records]
    return sorted(value for value, count in Counter(values).items() if value and count > 1)


def nonempty_text(record: dict[str, Any], field: str) -> bool:
    return bool(str(record.get(field, "")).strip())


def list_value(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field)
    return value if isinstance(value, list) else []


def unsupported_usage_groups(positive_text: Any, direct_support_text: Any) -> list[str]:
    positive = str(positive_text or "")
    support = str(direct_support_text or "")
    return [
        name
        for name, pattern in USAGE_SUPPORT_GROUPS
        if has_affirmative_match(positive, pattern) and not has_affirmative_match(support, pattern)
    ]


def has_affirmative_match(
    text: Any,
    pattern: re.Pattern[str],
    denial_prefix: re.Pattern[str] = GENERAL_DENIAL_PREFIX_RE,
) -> bool:
    value = str(text or "")
    return any(
        not denial_prefix.search(value[max(0, match.start() - 40):match.start()])
        for match in pattern.finditer(value)
    )


def high_risk_concepts(text: Any) -> set[str]:
    value = str(text or "")
    return {name for name, pattern in HIGH_RISK_CONCEPT_PATTERNS.items() if pattern.search(value)}


def unsupported_semantic_shortcuts(positive_text: Any, direct_support_text: Any) -> list[str]:
    positive = str(positive_text or "")
    support = str(direct_support_text or "")
    issues: list[str] = []
    has_positive_smell_claim = any(
        not SMELL_DENIAL_PREFIX_RE.search(positive[max(0, match.start() - 24):match.start()])
        for match in ACTUAL_SMELL_RE.finditer(positive)
    )
    if has_positive_smell_claim and not SMELL_SUPPORT_RE.search(support):
        issues.append("真实嗅觉体验")
    if SUFFICIENCY_SHORTCUT_RE.search(positive) and not SUFFICIENCY_SUPPORT_RE.search(support):
        issues.append("一瓶搞定/解决的充分性")
    if EXTERNAL_COMPARISON_RE.search(positive) and not EXTERNAL_COMPARISON_SUPPORT_RE.search(support):
        issues.append("外部品类/竞品同框对照")
    return issues


def parse_aware_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def variable_dimensions(text: Any) -> set[str]:
    value = str(text or "")
    return {name for name, pattern in VARIABLE_DIMENSION_PATTERNS.items() if pattern.search(value)}


def has_disjunctive_variable(text: Any) -> bool:
    value = re.sub(r"说明书或医务人员(?:的)?指导", "必要指导说明", str(text or ""))
    return bool(DISJUNCTIVE_VARIABLE_RE.search(value))


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"缺少必需文件 {name}: {path}")
    if errors:
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}

    try:
        manifest = read_json(paths["manifest"])
        upstream = read_json(paths["upstream"])
        existing = read_jsonl(paths["existing"])
        scans = read_jsonl(paths["paths"])
        slots = read_jsonl(paths["slots"])
        vis = read_jsonl(paths["vis"])
        validations = read_jsonl(paths["validation"])
        gaps = read_jsonl(paths["gaps"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}

    counts = {
        "existing_expressions": len(existing), "six_path_rows": len(scans),
        "slot_rows": len(slots), "vis": len(vis), "validation_tasks": len(validations),
        "gaps": len(gaps),
    }

    missing = missing_fields(manifest, MANIFEST_FIELDS)
    if missing:
        errors.append(f"expression_manifest.json 缺少字段: {', '.join(missing)}")
    if not re.fullmatch(r"VE-[0-9a-f]{12}", str(manifest.get("value_expression_id", ""))):
        errors.append("value_expression_id 必须使用 VE- 加 12 位小写十六进制")
    output_version = str(manifest.get("output_version", ""))
    if not re.fullmatch(r"V[1-9]\d*", output_version):
        errors.append("output_version 必须使用 V1、V2、V3 等正整数版本")
    elif manifest.get("product_value_id"):
        expected_id = value_expression_id(str(manifest.get("product_value_id")), output_version)
        if manifest.get("value_expression_id") != expected_id:
            errors.append("value_expression_id 与 product_value_id / output_version 不一致")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}；旧交付需要用当前版本重新初始化")
    if manifest.get("skill_version") != SKILL_VERSION:
        errors.append(f"skill_version 必须为 {SKILL_VERSION}；不得用新校验器给旧Skill交付补签")
    if not re.fullmatch(r"PV-[0-9a-f]{12}", str(manifest.get("product_value_id", ""))):
        errors.append("product_value_id 格式无效")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        errors.append("analysis_status 不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        errors.append("delivery_status 不在允许范围")
    if manifest.get("analysis_status") == "draft":
        errors.append("analysis_status=draft，不得作为正式交付")
    if not isinstance(manifest.get("limitations"), list):
        errors.append("limitations 必须是数组")
    created_at = parse_aware_iso_datetime(manifest.get("created_at"))
    updated_at = parse_aware_iso_datetime(manifest.get("updated_at"))
    if created_at is None:
        errors.append("created_at 必须是带时区的完整 ISO 时间")
    if updated_at is None:
        errors.append("updated_at 必须是带时区的完整 ISO 时间")
    if created_at is not None and updated_at is not None:
        if created_at > updated_at:
            errors.append("created_at 不得晚于 updated_at")
        if updated_at > datetime.now().astimezone() + timedelta(minutes=5):
            errors.append("updated_at 不得晚于当前时间超过 5 分钟")

    upstream_missing = missing_fields(upstream, UPSTREAM_FIELDS)
    if upstream_missing:
        errors.append(f"upstream_snapshot.json 缺少字段: {', '.join(upstream_missing)}")
    if manifest.get("product_value_id") != upstream.get("product_value_id"):
        errors.append("manifest 与 upstream_snapshot 的 product_value_id 不一致")
    if manifest.get("upstream_output_version") != upstream.get("upstream_output_version"):
        errors.append("manifest 与 upstream_snapshot 的上游版本不一致")
    if upstream.get("upstream_analysis_status") not in UPSTREAM_ANALYSIS_STATUSES:
        errors.append("上游 analysis_status 当前不可调用")
    if upstream.get("upstream_delivery_status") not in UPSTREAM_DELIVERY_STATUSES:
        errors.append("上游 delivery_status 当前不可调用")
    if upstream.get("p0_status") in {"P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
        errors.append("上游 P0 已重开、替换或停止，当前卖点呈现必须标记 stale")
    if not isinstance(upstream.get("values"), list):
        errors.append("upstream values 必须是数组")
    if not isinstance(upstream.get("fact_ids"), list):
        errors.append("upstream fact_ids 必须是数组")
    if not isinstance(upstream.get("facts"), list):
        errors.append("upstream facts 必须是数组")
    if not isinstance(upstream.get("file_hashes"), dict):
        errors.append("upstream file_hashes 必须是对象")

    ledger_specs = (
        ("existing_expression_ledger", existing, "expression_id", EXISTING_FIELDS, r"(?:EX|PEX)-\d{3,}"),
        ("six_path_ledger", scans, "scan_id", PATH_FIELDS, r"PATH-\d{3,}"),
        ("slot_scan_ledger", slots, "slot_id", SLOT_FIELDS, r"SLOT-(?:0[1-9]|1[0-2])"),
        ("vis_ledger", vis, "vis_id", VIS_FIELDS, r"VIS-\d{3,}"),
        ("validation_ledger", validations, "test_id", VALIDATION_FIELDS, r"TEST-\d{3,}"),
        ("gap_ledger", gaps, "gap_id", GAP_FIELDS, r"GAP-\d{3,}"),
    )
    for ledger_name, records, key, fields, pattern in ledger_specs:
        for index, record in enumerate(records, start=1):
            item_missing = missing_fields(record, fields)
            if item_missing:
                errors.append(f"{ledger_name} 第 {index} 条缺少字段: {', '.join(item_missing)}")
            if not re.fullmatch(pattern, str(record.get(key, ""))):
                errors.append(f"{ledger_name} 第 {index} 条 {key} 格式无效")
        duplicates = duplicate_ids(records, key)
        if duplicates:
            errors.append(f"{ledger_name} 存在重复 ID: {', '.join(duplicates)}")

    upstream_values = {
        str(item.get("value_id", "")): item
        for item in upstream.get("values", [])
        if isinstance(item, dict) and item.get("value_id")
    }
    active_values = {
        value_id
        for value_id, item in upstream_values.items()
        if item.get("layer") in ACTIVE_VALUE_LAYERS and item.get("downstream_readiness") != "blocked"
    }
    fact_ids = {str(item) for item in upstream.get("fact_ids", [])}
    fact_lookup = {
        str(item.get("fact_id", "")): item
        for item in upstream.get("facts", [])
        if isinstance(item, dict) and item.get("fact_id")
    }
    blocked_upstream_fact_ids = {
        fact_id
        for fact_id, item in fact_lookup.items()
        if SKU_BUNDLE_CONFLICT_RE.search(str(item.get("boundary", "")))
    }
    for fact_id in sorted(blocked_upstream_fact_ids):
        if str(fact_lookup[fact_id].get("status", "")).lower() in {"confirmed", "active", "current", "ready"}:
            errors.append(
                f"上游 {fact_id} 已声明套组/装箱清单冲突却仍标记为可用；"
                "必须先返回商品价值 Skill 降级并重建上游"
            )
    blocked_upstream_value_ids = {
        value_id
        for value_id, item in upstream_values.items()
        if blocked_upstream_fact_ids.intersection(map(str, list_value(item, "supporting_fact_ids")))
    }
    for value_id in sorted(active_values.intersection(blocked_upstream_value_ids)):
        errors.append(f"上游价值 {value_id} 仍引用冲突套组/装箱事实，不得进入卖点呈现")
    upstream_expression_ids = {str(item) for item in upstream.get("expression_ids", [])}
    existing_ids = {str(item.get("expression_id", "")) for item in existing}
    source_expression_count = 0
    footnote_expression_ids: set[str] = set()
    for record in existing:
        expression_id = str(record.get("expression_id", ""))
        origin = str(record.get("expression_origin", ""))
        source_form = str(record.get("source_form", ""))
        if origin not in EXPRESSION_ORIGINS:
            errors.append(f"{expression_id} expression_origin 不在允许范围")
        if source_form not in EXPRESSION_SOURCE_FORMS:
            errors.append(f"{expression_id} source_form 不在允许范围")
        if record.get("status") not in EXPRESSION_STATUSES:
            errors.append(f"{expression_id} status 不在允许范围")
        if origin == "upstream":
            if expression_id not in upstream_expression_ids or not expression_id.startswith("EX-"):
                errors.append(f"{expression_id} 标为上游表达时必须继承有效 EX 资产")
            if source_form != "upstream_registered":
                errors.append(f"{expression_id} 上游表达的 source_form 必须为 upstream_registered")
        if origin == "source_material":
            source_expression_count += 1
            if not expression_id.startswith("PEX-") or expression_id in upstream_expression_ids:
                errors.append(f"{expression_id} 补充素材表达必须使用独立 PEX- 编号")
            if source_form == "upstream_registered":
                errors.append(f"{expression_id} 补充素材表达不得标为 upstream_registered")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{expression_id} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        if origin == "source_material" and not list_value(record, "fact_ids"):
            errors.append(f"{expression_id} 补充素材表达至少回指一个上游事实")
        unknown_values = set(map(str, list_value(record, "value_ids"))) - set(upstream_values)
        if unknown_values:
            errors.append(f"{expression_id} 引用了未知价值: {', '.join(sorted(unknown_values))}")
        if manifest.get("analysis_status") in {"complete", "partial"}:
            for field in ("source_statement", "source_id", "locator", "current_perception", "boundary"):
                if not nonempty_text(record, field):
                    errors.append(f"{expression_id} 正式盘点缺少 {field}")
            if not nonempty_text(record, "page_says") and not nonempty_text(record, "page_shows"):
                errors.append(f"{expression_id} 必须填写 page_says 或 page_shows")
            if not nonempty_text(record, "reusable") and not nonempty_text(record, "gap"):
                errors.append(f"{expression_id} 必须填写 reusable 或 gap")
            if record.get("status") == "inventory_pending":
                errors.append(f"{expression_id} 仍为 inventory_pending，不得正式交付")
        expression_text = joined_text(record, ("source_statement", "page_says"))
        field_labels = [match.group(1) for match in ATOMIC_EXPRESSION_LABEL_RE.finditer(expression_text)]
        if len(field_labels) > 1:
            errors.append(
                f"{expression_id} 合并了多个应独立承接的高密度字段（{'、'.join(field_labels)}）；"
                "页面表达必须按主张单位拆分"
            )
        footnote_references = expression_footnote_references(expression_text)
        footnote_definitions = expression_footnote_definitions(expression_text)
        missing_footnotes = footnote_references - footnote_definitions
        if missing_footnotes:
            errors.append(
                f"{expression_id} 含脚注标记但未同时保留对应脚注原文："
                f"{', '.join(sorted(missing_footnotes))}"
            )
        if footnote_references or footnote_definitions:
            footnote_expression_ids.add(expression_id)
            if not FOOTNOTE_BOUNDARY_RE.search(str(record.get("boundary", ""))):
                errors.append(f"{expression_id} 使用页面脚注时必须在 boundary 明确保留脚注或限定语边界")

    source_materials = str(manifest.get("source_materials", "")).strip()
    if (
        manifest.get("analysis_status") in {"complete", "partial"}
        and source_materials not in {"", "not_provided", "未提供"}
        and source_expression_count == 0
    ):
        errors.append("已提供补充商品素材，但 existing_expression_ledger 没有 source_material / PEX 页面表达盘点")

    visible_page_text = normalized("\n".join(str(item.get("page_shows", "")) for item in existing))
    boundary_text = "\n".join(
        [joined_text(item, ("translation", "reason", "boundary")) for item in scans]
        + [
            joined_text(item, ("human_language", "visual_track", "prop_track", "misuse", "boundary"))
            for item in vis
        ]
        + [
            joined_text(item, ("validation_task", "control_version", "test_version", "boundary"))
            for item in validations
        ]
    )
    for match in NONEXISTENT_VISUAL_RE.finditer(boundary_text):
        for item in re.split(r"[、,/和及]", match.group(1)):
            token = normalized(item.removesuffix("等"))
            if len(token) >= 2 and token in visible_page_text:
                errors.append(f"页面盘点已登记可见元素“{item.strip()}”，不得同时把它写成实际不存在")

    scans_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scan_role_lookup: dict[tuple[str, str], str] = {}
    for record in scans:
        value_id = str(record.get("value_id", ""))
        route = str(record.get("route", ""))
        role = str(record.get("role", ""))
        scans_by_value[value_id].append(record)
        scan_role_lookup[(value_id, route)] = role
        if value_id not in active_values:
            errors.append(f"{record.get('scan_id')} 引用了不可调用或未知价值 {value_id}")
        if route not in ROUTES:
            errors.append(f"{record.get('scan_id')} route 不在六条路径范围")
        if role not in ROUTE_ROLES:
            errors.append(f"{record.get('scan_id')} role 不在允许范围")
        if not all(nonempty_text(record, field) for field in ("translation", "reason", "boundary")):
            errors.append(f"{record.get('scan_id')} 必须填写 translation、reason 和 boundary")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{record.get('scan_id')} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        blocked_facts = set(map(str, list_value(record, "fact_ids"))).intersection(blocked_upstream_fact_ids)
        if blocked_facts:
            errors.append(f"{record.get('scan_id')} 使用了冲突套组/装箱事实: {', '.join(sorted(blocked_facts))}")
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - existing_ids
        if unknown_ex:
            errors.append(f"{record.get('scan_id')} 引用了未知页面表达: {', '.join(sorted(unknown_ex))}")
        unsupported = unsupported_exact_tokens(record, ("translation",), fact_lookup)
        if unsupported:
            errors.append(f"{record.get('scan_id')} 使用了上游未核验的精确字段: {', '.join(unsupported)}")
        if role in {"primary", "supporting"}:
            linked_fact_text = "\n".join(
                joined_text(fact_lookup[fact_id], ("statement", "source_quotes"))
                for fact_id in map(str, list_value(record, "fact_ids"))
                if fact_id in fact_lookup
            )
            usage_issues = unsupported_usage_groups(record.get("translation", ""), linked_fact_text)
            if usage_issues:
                errors.append(
                    f"{record.get('scan_id')} 由包装量或规格推导了{'、'.join(usage_issues)}，但关联上游事实没有直接支持"
                )
            semantic_issues = unsupported_semantic_shortcuts(record.get("translation", ""), linked_fact_text)
            if semantic_issues:
                errors.append(
                    f"{record.get('scan_id')} 使用了{'、'.join(semantic_issues)}，但关联上游事实没有直接支持"
                )

    if manifest.get("analysis_status") in {"complete", "partial"}:
        if not active_values:
            errors.append("上游没有可进入沟通的 P0/P1/P2 价值")
        for value_id in sorted(active_values):
            rows = scans_by_value.get(value_id, [])
            route_counts = Counter(str(item.get("route", "")) for item in rows)
            if set(route_counts) != ROUTES or any(count != 1 for count in route_counts.values()):
                errors.append(f"{value_id} 必须逐项且仅一次扫描六条翻译路径")
            roles = Counter(str(item.get("role", "")) for item in rows)
            if roles["primary"] != 1:
                errors.append(f"{value_id} 必须选择且只选择 1 条主路径")
            if roles["supporting"] not in {1, 2}:
                errors.append(f"{value_id} 必须选择 1—2 条辅助路径")

    slot_numbers = [str(item.get("slot_number", "")) for item in slots]
    if manifest.get("analysis_status") in {"complete", "partial"}:
        if set(slot_numbers) != set(SLOT_GROUPS) or len(slot_numbers) != 12:
            errors.append("slot_scan_ledger 必须完整扫描 01—12 十二类槽位")
    slot_map = {str(item.get("slot_number", "")): item for item in slots}
    for record in slots:
        number = str(record.get("slot_number", ""))
        status = str(record.get("status", ""))
        if str(record.get("slot_id", "")) != f"SLOT-{number}":
            errors.append(f"槽位 {number} 的 slot_id 必须为 SLOT-{number}")
        if record.get("asset_group") not in ASSET_GROUPS or record.get("asset_group") != SLOT_GROUPS.get(number):
            errors.append(f"SLOT-{number} 的资产组不正确")
        if status not in SLOT_STATUSES:
            errors.append(f"SLOT-{number} status 不在允许范围")
        if not nonempty_text(record, "slot_name") or not nonempty_text(record, "reason"):
            errors.append(f"SLOT-{number} 必须填写槽位名称和判断理由")
        if status == "applicable" and not list_value(record, "vis_ids"):
            errors.append(f"SLOT-{number} 标为适用时至少关联一个 VIS")
        if status == "not_applicable" and list_value(record, "vis_ids"):
            errors.append(f"SLOT-{number} 标为不适用时不得关联 VIS")

    vis_ids = {str(item.get("vis_id", "")) for item in vis}
    existing_map = {str(item.get("expression_id", "")): item for item in existing}
    vis_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    priorities: list[int] = []
    for record in vis:
        vis_id = str(record.get("vis_id", ""))
        value_id = str(record.get("value_id", ""))
        vis_by_value[value_id].append(record)
        if value_id not in active_values:
            errors.append(f"{vis_id} 主价值不可调用或不存在: {value_id}")
        secondary = set(map(str, list_value(record, "secondary_value_ids")))
        if value_id in secondary:
            errors.append(f"{vis_id} 辅助价值不得重复主价值")
        unknown_secondary = secondary - set(upstream_values)
        if unknown_secondary:
            errors.append(f"{vis_id} 引用了未知辅助价值: {', '.join(sorted(unknown_secondary))}")
        number = str(record.get("slot_number", ""))
        slot = slot_map.get(number)
        if not slot or slot.get("status") != "applicable":
            errors.append(f"{vis_id} 关联的 SLOT-{number} 不存在或不适用")
        elif record.get("asset_group") != slot.get("asset_group"):
            errors.append(f"{vis_id} 的资产组与 SLOT-{number} 不一致")
        if record.get("asset_group") not in ASSET_GROUPS:
            errors.append(f"{vis_id} asset_group 不在允许范围")
        if record.get("decision_task") not in DECISION_TASKS:
            errors.append(f"{vis_id} decision_task 不在允许范围")
        primary_route = str(record.get("primary_route", ""))
        supporting_routes = list(map(str, list_value(record, "supporting_routes")))
        if primary_route not in ROUTES or scan_role_lookup.get((value_id, primary_route)) != "primary":
            errors.append(f"{vis_id} 主路径与 {value_id} 六路扫描不一致")
        if not 1 <= len(supporting_routes) <= 2:
            errors.append(f"{vis_id} 必须引用 1—2 条辅助路径")
        for route in supporting_routes:
            if route not in ROUTES or scan_role_lookup.get((value_id, route)) != "supporting":
                errors.append(f"{vis_id} 辅助路径 {route} 与六路扫描不一致")
        unknown_facts = set(map(str, list_value(record, "fact_ids"))) - fact_ids
        if unknown_facts:
            errors.append(f"{vis_id} 引用了未知事实: {', '.join(sorted(unknown_facts))}")
        blocked_facts = set(map(str, list_value(record, "fact_ids"))).intersection(blocked_upstream_fact_ids)
        if blocked_facts:
            errors.append(f"{vis_id} 使用了冲突套组/装箱事实: {', '.join(sorted(blocked_facts))}")
        unknown_ex = set(map(str, list_value(record, "expression_ids"))) - existing_ids
        if unknown_ex:
            errors.append(f"{vis_id} 引用了未知页面表达: {', '.join(sorted(unknown_ex))}")
        if not list_value(record, "fact_ids"):
            errors.append(f"{vis_id} 至少引用一个上游商品事实")
        if set(map(str, list_value(record, "expression_ids"))).intersection(footnote_expression_ids):
            footnote_guard = joined_text(record, ("must_keep", "misuse", "boundary"))
            if not FOOTNOTE_BOUNDARY_RE.search(footnote_guard):
                errors.append(f"{vis_id} 调用带脚注页面表达时必须在 must_keep、misuse 或 boundary 保留脚注边界")
        for field in ("user_question", "target_perception", "human_language", "must_keep", "variable_parts", "misuse", "boundary", *TRACK_FIELDS):
            if not nonempty_text(record, field):
                errors.append(f"{vis_id} 缺少必填内容 {field}")
        objects = set(map(str, list_value(record, "applicable_objects")))
        if not objects or not objects <= CONTENT_OBJECTS:
            errors.append(f"{vis_id} applicable_objects 必须是五大作业对象的非空子集")
        if record.get("validation_status") not in VIS_STATUSES:
            errors.append(f"{vis_id} validation_status 不在允许范围")
        positive_fields = (
            "user_question", "target_perception", "human_language", "visual_track",
            "action_track", "sound_track", "subtitle_track", "prop_track", "scene_track",
            "effect_bgm_track", "commerce_handoff_track", "must_keep", "variable_parts",
        )
        unsupported = unsupported_exact_tokens(record, positive_fields, fact_lookup)
        if unsupported:
            errors.append(f"{vis_id} 使用了上游未核验的精确字段: {', '.join(unsupported)}")
        positive_text = joined_text(record, positive_fields)
        linked_fact_text = normalized("\n".join(
            joined_text(fact_lookup[fact_id], ("statement", "source_quotes", "boundary"))
            for fact_id in map(str, list_value(record, "fact_ids"))
            if fact_id in fact_lookup
        ))
        usage_issues = unsupported_usage_groups(positive_text, linked_fact_text)
        if usage_issues:
            errors.append(f"{vis_id} 的{'、'.join(usage_issues)}缺少上游事实支持")
        semantic_issues = unsupported_semantic_shortcuts(positive_text, linked_fact_text)
        if semantic_issues:
            errors.append(f"{vis_id} 的{'、'.join(semantic_issues)}缺少上游事实支持")
        if ORIGINAL_ASSET_RE.search(positive_text):
            has_original = any(
                existing_map.get(expression_id, {}).get("source_form") == "original_document"
                for expression_id in map(str, list_value(record, "expression_ids"))
            )
            if not has_original:
                errors.append(f"{vis_id} 把截图或页面素材称为原件，但没有 original_document 页面表达依据")
        proof_claim = joined_text(record, ("user_question", "target_perception", "human_language"))
        if SINGLE_PACK_CLAIM_RE.search(proof_claim):
            proof_method = joined_text(record, ("action_track", "must_keep"))
            has_continuity = bool(re.search(r"连续|一镜到底|不中断|不剪辑", proof_method))
            has_no_supplement = bool(re.search(r"未拆封|不补料|不换包|不拼接|单包全部", proof_method))
            if not has_continuity or not has_no_supplement:
                errors.append(f"{vis_id} 声称单包内容物时必须保留未拆封单包、连续展示和不补料/不换包证明")
        priority = record.get("external_priority")
        if priority is not None:
            if type(priority) is not int or not 1 <= priority <= 5:
                errors.append(f"{vis_id} external_priority 必须为空或 1—5 整数")
            else:
                priorities.append(priority)
    if len(priorities) != len(set(priorities)):
        errors.append("external_priority 1—5 不能重复")
    if len(priorities) > 5:
        errors.append("普通版最多选择 5 个核心呈现资产")
    if priorities and set(priorities) != set(range(1, len(priorities) + 1)):
        errors.append("external_priority 必须从 1 开始连续编号")
    core_vis = [item for item in vis if type(item.get("external_priority")) is int]
    for item in core_vis:
        if str(item.get("slot_number", "")) == "02":
            errors.append(f"{item.get('vis_id')} 是一级识别锚，不得进入普通版核心呈现卡")
    if manifest.get("analysis_status") in {"complete", "partial"}:
        for value_id in sorted(active_values):
            if not vis_by_value.get(value_id):
                errors.append(f"{value_id} 是可沟通价值，但没有可调用 VIS")
        recommended = str(upstream.get("recommended_value_id", ""))
        if not any(item.get("external_priority") for item in vis_by_value.get(recommended, [])):
            errors.append("普通版核心呈现资产必须至少包含上游推荐 P0 的一个 VIS")
        required_core_values = {
            value_id
            for value_id, value in upstream_values.items()
            if value_id in active_values and value.get("layer") in {"P0", "P1"}
        }
        if len(required_core_values) <= 5:
            core_primary_values = {str(item.get("value_id", "")) for item in core_vis}
            missing_core_values = required_core_values - core_primary_values
            if missing_core_values:
                errors.append(
                    "普通版核心呈现卡必须优先覆盖全部可调用 P0/P1 主价值；缺少: "
                    + ", ".join(sorted(missing_core_values))
                )

    for record in slots:
        number = str(record.get("slot_number", ""))
        for linked in map(str, list_value(record, "vis_ids")):
            if linked not in vis_ids:
                errors.append(f"SLOT-{number} 引用了未知 VIS: {linked}")
            else:
                linked_record = next(item for item in vis if item.get("vis_id") == linked)
                if str(linked_record.get("slot_number", "")) != number:
                    errors.append(f"SLOT-{number} 与 {linked} 的 slot_number 不一致")

    if len(validations) > 3:
        errors.append("第一轮内容验证最多保留 3 个任务")
    vis_map = {str(item.get("vis_id", "")): item for item in vis}
    for record in validations:
        test_id = str(record.get("test_id", ""))
        unknown_vis = set(map(str, list_value(record, "vis_ids"))) - vis_ids
        if unknown_vis:
            errors.append(f"{test_id} 引用了未知 VIS: {', '.join(sorted(unknown_vis))}")
        if not list_value(record, "vis_ids"):
            errors.append(f"{test_id} 至少关联一个 VIS")
        if not list_value(record, "primary_metrics"):
            errors.append(f"{test_id} 必须给出与任务匹配的观察指标")
        for field in (
            "validation_task", "must_keep", "single_variable", "control_version",
            "test_version", "measurement_method", "decision_rule", "writeback",
            "requirements", "boundary",
        ):
            if not nonempty_text(record, field):
                errors.append(f"{test_id} 缺少必填内容 {field}")
        if record.get("status") not in TEST_STATUSES:
            errors.append(f"{test_id} status 不在允许范围")
        if normalized(record.get("control_version")) == normalized(record.get("test_version")):
            errors.append(f"{test_id} 对照版与测试版不得相同")
        task_text = str(record.get("validation_task", ""))
        variable_text = str(record.get("single_variable", ""))
        dimensions = variable_dimensions(variable_text)
        if len(dimensions) > 1:
            errors.append(
                f"{test_id} single_variable 同时改变多个呈现维度: {'、'.join(sorted(dimensions))}"
            )
        if has_disjunctive_variable(variable_text):
            errors.append(f"{test_id} single_variable 含二选一/备选项，必须锁定一个具体变量")
        if ("上下" in task_text and "左右" in variable_text) or ("左右" in task_text and "上下" in variable_text):
            errors.append(f"{test_id} 验证任务与 single_variable 的方向描述不一致")
        control_text = str(record.get("control_version", ""))
        test_text = str(record.get("test_version", ""))
        if MANDATORY_GUARDRAIL_REMOVAL_RE.search(control_text) or MANDATORY_GUARDRAIL_REMOVAL_RE.search(test_text):
            errors.append(
                f"{test_id} 把症状分层、说明书/医务人员指导、禁忌或警示等必要边界作为可移除变量；"
                "所有版本都必须保留安全与适用边界"
            )
        qualifier_test_text = joined_text(
            record,
            ("validation_task", "single_variable", "control_version", "test_version"),
        )
        if MANDATORY_CLAIM_QUALIFIER_REMOVAL_RE.search(qualifier_test_text):
            errors.append(
                f"{test_id} 把实验条件、适用条件、脚注或限定语作为可删除变量；"
                "所有版本都必须保留主张成立所需的事实限定"
            )
        shared_risk_concepts = high_risk_concepts(control_text).intersection(high_risk_concepts(test_text))
        objective_risk_concepts = high_risk_concepts(
            " ".join(
                [
                    task_text,
                    " ".join(map(str, list_value(record, "primary_metrics"))),
                    str(record.get("measurement_method", "")),
                    str(record.get("decision_rule", "")),
                    str(record.get("writeback", "")),
                ]
            )
        )
        if shared_risk_concepts and objective_risk_concepts and shared_risk_concepts.isdisjoint(objective_risk_concepts):
            errors.append(
                f"{test_id} 的固定高风险字幕/说明是{'、'.join(sorted(shared_risk_concepts))}，"
                f"但验证任务与指标衡量的是{'、'.join(sorted(objective_risk_concepts))}；"
                "证据、主张与指标必须语义同题，安全证据不得抵消禁忌"
            )
        if VISUAL_EVIDENCE_VARIABLE_RE.search(variable_text):
            control_subtitle = SUBTITLE_QUOTE_RE.search(control_text)
            test_subtitle = SUBTITLE_QUOTE_RE.search(test_text)
            if (
                control_subtitle
                and test_subtitle
                and normalized(control_subtitle.group(1)) != normalized(test_subtitle.group(1))
            ):
                errors.append(f"{test_id} 把证据画面设为唯一变量时，不得同时改变字幕")
        pack_test_text = joined_text(
            record,
            ("validation_task", "single_variable", "control_version", "test_version", "measurement_method", "writeback"),
        ) + "\n" + "\n".join(map(str, list_value(record, "primary_metrics")))
        if SINGLE_PACK_CLAIM_RE.search(pack_test_text) and PREARRANGED_RE.search(control_text):
            errors.append(f"{test_id} 衡量单包构成时，对照版也必须来自当前 SKU 的真实单包，不得使用预摆盘")
        significance_text = joined_text(record, ("decision_rule", "measurement_method", "requirements"))
        if has_affirmative_match(
            significance_text,
            SIGNIFICANCE_RE,
            SIGNIFICANCE_DENIAL_PREFIX_RE,
        ):
            design_text = joined_text(record, ("measurement_method", "requirements"))
            if not STATISTICAL_DESIGN_RE.search(design_text):
                errors.append(f"{test_id} 使用显著性判断但没有登记样本量或统计检验方法")
        for metric in map(str, list_value(record, "primary_metrics")):
            if re.search(r"(?:留存|完播|点击).{0,16}(?:评论|复述)|(?:评论|复述).{0,16}(?:留存|完播|点击)", metric):
                errors.append(f"{test_id} 把平台行为指标与评论语义混成不可直接观测的单一指标: {metric}")
        validation_positive_text = joined_text(
            record,
            ("validation_task", "must_keep", "single_variable", "control_version", "test_version"),
        )
        linked_vis = [vis_map[item] for item in map(str, list_value(record, "vis_ids")) if item in vis_map]
        linked_vis_boundaries = "\n".join(
            joined_text(item, ("must_keep", "misuse", "boundary")) for item in linked_vis
        )
        if re.search(r"不(?:得)?跨.{0,6}(?:除螨|螨虫)", linked_vis_boundaries) and re.search(
            r"除螨|螨虫", validation_positive_text
        ):
            errors.append(
                f"{test_id} 混入了关联呈现明确禁止跨用的除螨对象；"
                "验证画面、字幕和指标必须与当前除菌主张同题"
            )
        proxy = dict(record)
        proxy["fact_ids"] = sorted({
            str(fact_id)
            for item in linked_vis
            for fact_id in list_value(item, "fact_ids")
        })
        unsupported = unsupported_exact_tokens(
            proxy,
            ("validation_task", "must_keep", "single_variable", "control_version", "test_version"),
            fact_lookup,
        )
        if unsupported:
            errors.append(f"{test_id} 使用了上游未核验的精确字段: {', '.join(unsupported)}")
        linked_fact_text = "\n".join(
            joined_text(fact_lookup[fact_id], ("statement", "source_quotes"))
            for fact_id in map(str, list_value(proxy, "fact_ids"))
            if fact_id in fact_lookup
        )
        comparison_issues = unsupported_semantic_shortcuts(validation_positive_text, linked_fact_text)
        if "外部品类/竞品同框对照" in comparison_issues:
            errors.append(
                f"{test_id} 引入外部品类/竞品同框对照，但关联上游事实没有直接比较证据；"
                "不得用自身身份事实替代外部比较证据"
            )
        if ORIGINAL_ASSET_RE.search(validation_positive_text):
            linked_expression_ids = {
                str(expression_id)
                for item in linked_vis
                for expression_id in list_value(item, "expression_ids")
            }
            if not any(existing_map.get(item, {}).get("source_form") == "original_document" for item in linked_expression_ids):
                errors.append(f"{test_id} 把截图或页面素材称为原件，但关联 VIS 没有 original_document 依据")

    if manifest.get("analysis_status") == "insufficient" and not gaps:
        errors.append("analysis_status=insufficient 时至少需要一条资料缺口")
    for report_key in ("report_01", "report_02"):
        text = paths[report_key].read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"{paths[report_key].name} 为空")
        if re.search(r"\{\{[^}]+\}\}|\[TODO|TODO:|待填写", text):
            errors.append(f"{paths[report_key].name} 仍有模板占位符")
        if re.search(r"(?:PV|VE|SRC|ANCHOR|FABE|VIS|PATH|SLOT|TEST|GAP|V|F|H|EX|U|DYN|STRAT)-\d", text):
            errors.append(f"{paths[report_key].name} 暴露内部资产 ID")
        if re.search(r"[A-Za-z]:\\(?:Users|Documents|Desktop|Downloads|会稽山|喜纯)", text):
            errors.append(f"{paths[report_key].name} 暴露本地绝对路径")
    report_01 = paths["report_01"].read_text(encoding="utf-8")
    for heading in (
        "## 1｜卖点感知化总览", "## 2｜品牌语言翻译为用户语言",
        "## 3｜核心卖点感知化呈现卡", "## 4｜内容功能位置怎么调用",
        "## 5｜五大作业对象调用地图", "## 6｜第一轮内容验证",
        "## 7｜资产回写闭环",
    ):
        if heading not in report_01:
            errors.append(f"01_卖点可视化呈现.md 缺少章节: {heading}")
    if report_01.count("### 呈现卡") > 5:
        errors.append("普通版核心呈现卡超过 5 张")

    report_data = {
        "manifest": manifest,
        "upstream": upstream,
        "existing": existing,
        "scans": scans,
        "slots": slots,
        "vis": vis,
        "validations": validations,
        "gaps": gaps,
    }
    expected_reports = {
        "report_01": build_report_01(report_data).rstrip() + "\n",
        "report_02": build_report_02(report_data).rstrip() + "\n",
    }
    for report_key, expected in expected_reports.items():
        actual = paths[report_key].read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"{paths[report_key].name} 与 data 账本不同步，请重新运行报告构建器")

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "analysis_status": manifest.get("analysis_status"),
        "delivery_status": manifest.get("delivery_status"),
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_delivery(args.delivery)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
