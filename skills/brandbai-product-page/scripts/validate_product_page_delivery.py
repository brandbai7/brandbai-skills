"""Validate a BrandBAI Product Page delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from product_page_common import (
    ANALYSIS_MODES,
    ANALYSIS_TARGET_BASES,
    ANALYSIS_TARGET_DECISIONS,
    ACTION_SCOPES,
    ACTION_STATUSES,
    ACTION_TYPES,
    RECOMMENDATION_LABELS,
    ANALYSIS_STATUSES,
    BASIS_TYPES,
    BUNDLE_COMPONENT_ROLES,
    COMPONENT_SCOPES,
    COMPONENT_APPLICABILITY,
    ENTRY_CONTEXT_BASES,
    INFORMATION_NODE_TYPES,
    MATCH_STATUSES,
    CATEGORY_DECISION_BASIS_TYPES,
    CATEGORY_DECISION_MATURITIES,
    CATEGORY_TASK_REQUIREMENTS,
    CATEGORY_TASK_IMPORTANCE,
    CONTENT_COVERAGE_STATUSES,
    CONTENT_POSITION_STATUSES,
    EVIDENCE_CONNECTION_STATUSES,
    CONTENT_REDUNDANCY_STATUSES,
    PACKAGE_VERSION_STATUSES,
    PAGE_ROLES,
    ADJACENCY_STATUSES,
    CLAIM_LEVELS,
    CLAIM_SCOPES,
    SURFACES,
    SURFACE_COVERAGE_STATUSES,
    DECISION_CLOSURE_STATUSES,
    HANDOFF_TYPES,
    PRESENTATION_RELATIONSHIPS,
    ELIGIBILITY_STATUSES,
    RAW_SPEC_GROUP_STATUSES,
    VARIANT_TYPES,
    VARIANT_OPTION_TYPES,
    TRANSACTION_ROLES,
    REGULATED_PRODUCT_TYPES,
    HIGH_RISK_PRODUCT_TYPES,
    CLAIM_TYPES,
    CLAIM_SOURCE_READABILITY,
    PAGE_SUPPORT_STATUSES,
    SURFACE_RELATIONSHIPS,
    CROSS_SURFACE_CONSISTENCY_STATUSES,
    POST_PURCHASE_STATUSES,
    UPGRADE_COMPARISON_STATUSES,
    CHAIN_FINDING_TYPES,
    CONTENT_LAYERS,
    COVERAGE_STATUSES,
    DECISION_NAMES,
    DECISION_STATUSES,
    DELIVERY_MODES,
    DELIVERY_STATUSES,
    DYNAMIC_STATUSES,
    DYNAMIC_SNAPSHOT_APPLICABILITY,
    GAP_RETURN_TARGETS,
    PAGE_SCOPES,
    READABILITY_STATUSES,
    ROUTE_GATE_STATUSES,
    ROUTE_OPTIONS,
    ROUTE_STATUSES,
    RUN_STATUSES,
    SCHEMA_VERSION,
    SCOPES,
    SEQUENCE_STATUSES,
    SKILL_VERSION,
    TASKS,
    UPSTREAM_ANALYSIS_STATUSES,
    UPSTREAM_DELIVERY_STATUSES,
    VISIBLE_OPTION_MATCH_STATUSES,
    MODULE_ROLES,
    delivery_paths,
    product_page_id,
    read_json,
    read_jsonl,
    required_report_paths,
)


MANIFEST_FIELDS = {
    "schema_version", "skill_version", "product_page_id", "brand", "product",
    "category", "sku", "scope", "task", "analysis_mode", "delivery_mode", "run_status",
    "analysis_status", "delivery_status", "page_snapshot_time", "entry_context",
    "cross_surface_summary", "output_version", "source_count", "limitations",
    "created_at", "updated_at",
}
SUPPORTING_SOURCE_FIELDS = {
    "supporting_source_id", "relative_path", "file_name", "extension", "media_type",
    "size_bytes", "sha256", "source_role", "readability_status", "capture_time",
    "duplicate_of", "notes",
}
CLAIM_FIELDS = {
    "claim_id", "statement", "claim_type", "supporting_source_ids",
    "applicable_sku", "support_scope", "evidence_status", "can_support",
    "cannot_prove", "dynamic_status", "human_confirmation", "boundary",
}
SUPPORTING_SOURCE_ROLES = {
    "product_document", "evidence_document", "user_signal", "business_context",
    "competitor_page", "optional_upstream", "unknown",
}
SUPPORT_CLAIM_TYPES = {
    "confirmed_fact", "page_claim", "user_signal", "dynamic_snapshot",
    "competitor_observation", "unverified_claim",
}
CLAIM_EVIDENCE_STATUSES = {"usable", "conditional", "unverified", "blocked"}
SOURCE_FIELDS = {
    "source_file_id", "source_version", "relative_path", "file_name", "extension",
    "media_type", "size_bytes", "sha256", "page_scope", "page_location",
    "sequence", "sequence_status", "readability_status", "capture_time",
    "quality_excluded", "quality_exclusion_reason", "duplicate_of", "notes",
}
COVERAGE_FIELDS = {
    "coverage_id", "source_version", "scope", "page_declared_count",
    "observed_source_count", "quality_excluded_count", "readable_source_count",
    "sequence_gap", "coverage_status", "basis", "boundary",
}
COMPONENT_FIELDS = {
    "component_id", "scope", "page_location", "sequence", "source_file_ids",
    "readability_status", "current_observation", "page_says", "page_shows",
    "decision_names", "category_task_ids", "fact_ids", "value_ids", "vis_ids", "dynamic_status",
    "content_layer", "module_role", "support_target",
    "information_node_type", "primary_decision_name", "match_status",
    "predecessor_requirement", "next_node_or_touchpoint", "comparison_dimension",
    "package_version_status", "component_applicability", "target_user_or_object",
    "variant_id", "claim_scope", "adjacency_status", "valid_time_or_unknown",
    "claim_level",
    "current_role", "recommended_role", "change_type", "execution_instruction",
    "required_material", "acceptance_check", "status", "boundary",
}
CHAIN_FIELDS = {
    "schema_version", "page_role", "page_role_basis", "entry_context_basis",
    "analysis_target",
    "precompleted_decisions", "remaining_decision_tasks", "dominant_route",
    "parallel_routes", "category_decision_chain",
    "surface_coverage", "ordered_component_ids", "decision_closure",
    "continuation_handoffs", "chain_findings", "aggregate_implications",
    "overall_diagnosis", "rebuild_strategy", "transaction_panel_plan",
    "detail_page_assessment", "detail_page_plan",
    "cross_surface_consistency", "presentation_actuality_checks", "eligibility_gate",
    "variant_routes", "quantified_claim_checks", "current_transaction",
    "cross_surface_sku_consistency", "post_purchase_handoff", "limitations",
}
DETAIL_PAGE_PLAN_FIELDS = {
    "status", "strategy_summary", "narrative_route", "modules",
    "asset_migration", "boundary",
}
DETAIL_PAGE_MODULE_FIELDS = {
    "module_id", "sequence", "module_name", "user_question", "page_answer",
    "required_content", "category_task_ids", "source_component_ids",
    "source_asset_summary", "presentation_direction", "material_needed",
    "acceptance_check", "boundary",
}
DETAIL_ASSET_MIGRATION_FIELDS = {
    "migration_id", "source_component_ids", "current_content", "handling",
    "destination_module_ids", "execution_note", "boundary",
}
TRANSACTION_PANEL_PLAN_FIELDS = {
    "status", "selection_area_mode", "platform_capability_status", "capability_summary",
    "strategy_summary", "selection_route", "field_groups",
    "fixed_information", "dynamic_information", "boundary",
}
TRANSACTION_FIELD_GROUP_FIELDS = {
    "group_id", "sequence", "group_name", "user_question", "current_expression",
    "recommended_structure", "current_selection_display", "actual_receipt_and_offer",
    "implementation_status", "implementation_path", "fallback_path", "confirmation_needed",
    "category_task_ids", "material_needed", "acceptance_check", "boundary",
}
TRANSACTION_IMPLEMENTATION_STATUSES = {
    "confirmed_native", "conditional_native", "content_workaround",
    "requires_platform_confirmation", "unknown",
}
TRANSACTION_PANEL_PLAN_STATUSES = {
    "planned", "preserve_only", "insufficient_material", "not_in_scope", "stopped",
}
TRANSACTION_SELECTION_AREA_MODES = {
    "single_primary_area", "no_choice_needed", "unknown",
}
DETAIL_PAGE_PLAN_STATUSES = {
    "planned", "preserve_only", "insufficient_material", "not_in_scope", "stopped",
}
DETAIL_PAGE_ASSESSMENT_FIELDS = {
    "status", "assessment_basis", "strengths", "improvement_opportunities", "boundary",
}
DETAIL_PAGE_ASSESSMENT_STATUSES = {
    "assessed", "insufficient_material", "not_in_scope", "stopped",
}
DETAIL_PAGE_STRENGTH_FIELDS = {
    "assessment_id", "title", "why_it_helps", "supporting_component_ids",
    "category_task_ids", "decision_names", "preserve_requirement", "boundary",
}
DETAIL_PAGE_OPPORTUNITY_FIELDS = {
    "assessment_id", "title", "what_is_not_yet_clear", "purchase_impact",
    "supporting_component_ids", "category_task_ids", "decision_names",
    "improvement_direction", "acceptance_check", "boundary",
}
DETAIL_ASSET_HANDLINGS = {
    "继续使用", "集中到一个章节", "分别放入不同章节", "提前说明",
    "放到后面", "本轮不使用", "确认后再安排",
}
DECISION_FIELDS = {
    "decision_id", "decision_name", "status", "summary", "explained",
    "not_explained", "purchase_impact", "recommended_fix", "source_file_ids",
    "component_ids", "fact_ids", "value_ids", "vis_ids", "unknowns", "boundary",
}
ACTION_FIELDS = {
    "action_id", "priority", "project_name", "root_problem_ids", "category_task_ids", "strategic_goal",
    "scope", "page_location", "decision_name", "recommendation_label",
    "current_observation", "gap_or_risk", "basis_type", "basis_summary",
    "source_file_ids", "component_ids", "fact_ids", "value_ids", "vis_ids",
    "action_type", "action_detail", "must_preserve", "material_needed",
    "human_confirmation", "acceptance_check", "validation_question", "status",
    "boundary",
}
MATCH_FIELDS = {
    "match_id", "category_task_id", "component_ids", "source_file_ids",
    "coverage_status", "position_status", "evidence_connection_status",
    "redundancy_status", "current_content_summary", "match_reason",
    "user_consequence", "recommended_resolution", "boundary",
}
VALIDATION_FIELDS = {
    "test_id", "scope", "version_a", "version_b", "must_keep", "single_variable",
    "observation_needed", "comparability", "status", "boundary",
}
GAP_FIELDS = {
    "gap_id", "category", "missing", "impact", "minimum_needed", "return_to",
    "source_file_ids", "priority", "state",
}
ROUTE_FIELDS = {
    "routing_decision_id", "recommended_route", "entry_context", "decision_summary",
    "shared_invariants", "change_scope", "activation_conditions", "standalone_gate",
    "source_file_ids", "component_ids", "fact_ids", "value_ids", "vis_ids",
    "human_confirmation", "status", "boundary",
}
ROUTE_GATE_FIELDS = {
    "entry_difference", "business_scale", "evidence_support", "maintenance_capacity",
}
ACTIVE_ACTION_STATUSES = {"suggested_untested", "candidate"}
MEDIA_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"},
    "pdf": {".pdf"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "document": {".html", ".htm", ".md", ".txt", ".json", ".csv", ".xlsx"},
    "video": {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"},
    "other": set(),
}

REPORT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:(?:PP|PAGE-SF|SUP-SF|CLAIM|COV|COMP|CAT|MATCH|ACT|TEST|GAP|ROUTE|PV|VE|VIS|V|F|U|EX|DYN|STRAT)-[0-9a-fA-F]{2,}|DEC-0[1-5])(?![A-Za-z0-9_-])"
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    r"|file://+[^\s|<>()]+"
    r"|//[^/\s|<>]+/[^/\s|<>]+(?:/[^\s|<>]+)*"
    r"|(?:^|(?<=[\s:：=（(【\[]))/(?!/)(?:(?:tmp|var|home|Users|etc|opt|srv|mnt|private|Volumes|usr|root|data)(?:/|$)|[A-Za-z._~][A-Za-z0-9._~-]*/)[^\s|<>()]*"
    r"|\\\\[^\\\s|<>]+\\[^\\\s|<>]+)"
)
REMOTE_URL_PATTERN = re.compile(r"\b(?:https?|ftp)://[^\s|<>()]+", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}|\[TODO|TODO:|待填写|由生成脚本")
P0_MUTATION_PATTERNS = (
    re.compile(r"重选\s*P0", re.IGNORECASE),
    re.compile(r"替换\s*P0", re.IGNORECASE),
    re.compile(r"重新选择核心价值"),
    re.compile(r"新的核心卖点"),
    re.compile(r"改成(?:新的)?核心卖点"),
)
COMMENT_FACT_PATTERNS = (
    re.compile(r"评论(?:已经)?证明"),
    re.compile(r"评价(?:已经)?证明"),
    re.compile(r"根据评论(?:可以)?确认"),
    re.compile(r"根据评价(?:可以)?确认"),
    re.compile(r"用户普遍(?:认为|觉得|反馈)"),
    re.compile(r"消费者都(?:认为|觉得|关注)"),
)
EFFECT_PATTERNS = (
    re.compile(r"(?:一定|必然|肯定|保证).{0,12}(?:提升|增长|爆单|转化)"),
    re.compile(r"(?:会|将|能够|可以).{0,8}提升(?:点击率|转化率|GMV|ROI|销量)"),
    re.compile(r"(?:预计|预估).{0,6}(?:提升|增长)\s*\d+(?:\.\d+)?%"),
    re.compile(r"提升\s*\d+(?:\.\d+)?%"),
)
VERSION_WIN_PATTERNS = (
    re.compile(r"(?:版本|页面).{0,8}(?:胜出|更优|优于|已经有效|已验证有效)"),
    re.compile(r"(?:由|因为).{0,10}(?:页面|主图|详情).{0,8}(?:造成|导致).{0,8}(?:增长|提升|转化)"),
)
P0_USABLE_STATUSES = {
    "P0-HYPOTHESIS",
    "P0-SELECTED",
    "P0-VALIDATING",
    "P0-BOUNDARY-VALIDATED",
}
P0_READY_STATUSES = {"P0-SELECTED", "P0-VALIDATING", "P0-BOUNDARY-VALIDATED"}
VALUE_USABLE_READINESS = {"ready", "conditional"}


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def list_value(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field)
    return value if isinstance(value, list) else []


def nonempty(record: dict[str, Any], field: str) -> bool:
    return bool(str(record.get(field, "")).strip())


def duplicate_ids(records: Iterable[dict[str, Any]], key: str) -> list[str]:
    values = [str(item.get(key, "")) for item in records]
    return sorted(value for value, count in Counter(values).items() if value and count > 1)


def add_error(errors: list[str], code: str, message: str) -> None:
    errors.append(f"{code}: {message}")


def contains_effect_promise(text: str) -> bool:
    for pattern in EFFECT_PATTERNS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 12):match.start()]
            if re.search(r"(?:不能证明|无法证明|不代表|不得|不承诺|尚未证明|未验证)", prefix):
                continue
            return True
    return False


def record_text(record: dict[str, Any]) -> str:
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)
        else:
            values.append(str(value))

    collect(record)
    return " ".join(values)


def upstream_restriction_topics(upstream: dict[str, Any]) -> set[str]:
    """Extract claim topics that upstream explicitly says may not be asserted."""
    texts: list[str] = []
    product_value = upstream.get("product_value")
    if isinstance(product_value, dict):
        for value in product_value.get("values", []):
            if not isinstance(value, dict):
                continue
            cannot_prove = value.get("cannot_prove")
            if isinstance(cannot_prove, list):
                texts.extend(str(item).strip() for item in cannot_prove if str(item).strip())
    value_expression = upstream.get("value_expression")
    if isinstance(value_expression, dict):
        for vis in value_expression.get("vis", []):
            if isinstance(vis, dict) and str(vis.get("misuse", "")).strip():
                texts.append(str(vis["misuse"]).strip())

    topics: set[str] = set()
    for text in texts:
        topics.update(re.findall(r"(?i)SPF\s*\d+\+?|PA\s*\+{1,4}", text))
        if "防晒" in text:
            topics.add("防晒")

        body = re.sub(r"^(?:不能|不要|不得|禁止|不应|无法)\s*", "", text).strip()
        if "把" in body:
            body = body.rsplit("把", 1)[1]
        for trigger in ("加入", "承诺", "纳入", "调用", "使用", "证明"):
            if trigger in body:
                body = body.rsplit(trigger, 1)[1]
                break
        if "作为推荐理由" in body:
            body = body.split("作为推荐理由", 1)[0]
        if "扩大为" in body:
            left, right = body.split("扩大为", 1)
            body = left
            if right.strip():
                topics.add(right.strip())
        if "写成" in body:
            left, right = body.split("写成", 1)
            if left.strip():
                topics.add(left.strip())
            body = right
        for part in re.split(r"(?:或|以及|、|；|;|，|,)", body):
            topic = part.strip(" 。：:\"'‘’“”")
            topic = re.sub(r"^(?:当前资产中|页面中|页面上的|页面标示的)", "", topic)
            topic = re.sub(r"(?:承诺|结论|理由)$", "", topic).strip()
            if 2 <= len(topic) <= 32:
                topics.add(topic)
    return {topic for topic in topics if topic}


def reopened_upstream_topic(text: str, topics: set[str]) -> str:
    """Return the first upstream-restricted topic asserted as an execution claim."""
    for topic in sorted(topics, key=len, reverse=True):
        if topic.lower() not in text.lower():
            continue
        clauses = re.split(r"[。；;！!？?\n|]", text)
        for clause in clauses:
            if topic.lower() not in clause.lower():
                continue
            escaped = re.escape(topic)
            assertive = re.search(
                rf"(?<!不)(?<!勿)(?:突出|强化|主打|强调|放大|前移|优先展示|作为(?:卖点|推荐理由)).{{0,12}}{escaped}",
                clause,
                re.IGNORECASE,
            )
            safe = re.search(
                r"(?:不|未|无|待|禁止|不得|不要|不能|不应|无法|排除|复核|核对|"
                r"确认前|不纳入|不进入|不调用|不加入|不承诺|不证明|只证明页面出现|"
                r"分开|隔离|剔除)",
                clause,
            )
            if assertive or not safe:
                return topic
    return ""


def validate_upstream_boundary(
    errors: list[str], record_id: str, text: str, action_type: Any, topics: set[str]
) -> None:
    if action_type == "人工核实" or not topics:
        return
    topic = reopened_upstream_topic(text, topics)
    if topic:
        add_error(
            errors,
            "E_UPSTREAM_BOUNDARY_REOPENED",
            f"{record_id}重新启用了上游明确限制的主张：{topic}",
        )


def is_zoned_iso(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text == "unknown":
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_reference_list(
    errors: list[str],
    record_name: str,
    record: dict[str, Any],
    field: str,
    allowed: set[str],
    code: str,
) -> None:
    value = record.get(field)
    if not isinstance(value, list):
        add_error(errors, code, f"{record_name}.{field} 必须是数组")
        return
    unknown = set(map(str, value)) - allowed
    if unknown:
        add_error(errors, code, f"{record_name}.{field} 引用了未知ID: {', '.join(sorted(unknown))}")


def validate_upstream(
    upstream: dict[str, Any], manifest: dict[str, Any], errors: list[str]
) -> tuple[set[str], set[str], set[str], bool, bool]:
    if not isinstance(upstream.get("product_value"), dict):
        add_error(errors, "E_UPSTREAM_SCHEMA", "upstream_snapshot.product_value 必须是对象")
        product_value: dict[str, Any] = {}
    else:
        product_value = upstream["product_value"]
    if not isinstance(upstream.get("value_expression"), dict):
        add_error(errors, "E_UPSTREAM_SCHEMA", "upstream_snapshot.value_expression 必须是对象")
        value_expression: dict[str, Any] = {}
    else:
        value_expression = upstream["value_expression"]
    if not nonempty(upstream, "captured_at"):
        add_error(errors, "E_UPSTREAM_SCHEMA", "upstream_snapshot 缺少 captured_at")

    fact_id_rows = product_value.get("fact_ids")
    value_id_rows = product_value.get("value_ids")
    vis_id_rows = value_expression.get("vis_ids")
    if not isinstance(fact_id_rows, list):
        add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照fact_ids必须是数组")
        fact_id_rows = []
    if not isinstance(value_id_rows, list):
        add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照value_ids必须是数组")
        value_id_rows = []
    if not isinstance(vis_id_rows, list):
        add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照vis_ids必须是数组")
        vis_id_rows = []
    fact_ids = set(map(str, fact_id_rows))
    value_ids = set(map(str, value_id_rows))
    vis_ids = set(map(str, vis_id_rows))
    if not isinstance(product_value.get("provided"), bool) or not isinstance(product_value.get("usable"), bool):
        add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照的provided/usable必须是布尔值")
    if not isinstance(value_expression.get("provided"), bool) or not isinstance(value_expression.get("usable"), bool):
        add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照的provided/usable必须是布尔值")
    if product_value.get("provided"):
        if not re.fullmatch(r"PV-[0-9a-f]{12}", str(product_value.get("product_value_id", ""))):
            add_error(errors, "E_UPSTREAM_SCHEMA", "product_value_id 格式无效")
        for field in ("brand", "product", "sku", "analysis_status", "delivery_status", "p0_status"):
            if not nonempty(product_value, field):
                add_error(errors, "E_UPSTREAM_SCHEMA", f"商品价值快照缺少 {field}")
        for field, label in (("brand", "品牌"), ("product", "商品"), ("sku", "SKU")):
            if str(product_value.get(field, "")).strip() != str(manifest.get(field, "")).strip():
                add_error(errors, "E_IDENTITY_MIXED", f"商品价值上游{label}与页面交付不一致")
        if (
            str(product_value.get("category", "")).strip()
            and str(manifest.get("category", "")).strip()
            and str(product_value.get("category", "")).strip()
            != str(manifest.get("category", "")).strip()
        ):
            add_error(errors, "E_IDENTITY_MIXED", "商品价值上游类目与页面交付不一致")
        recommended = str(product_value.get("recommended_value_id", ""))
        if product_value.get("usable") and recommended not in value_ids:
            add_error(errors, "E_P0_CREATED", "推荐核心价值不在上游价值ID中")
        if not isinstance(product_value.get("facts"), list) or not isinstance(product_value.get("values"), list):
            add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照的facts/values必须是数组")
        else:
            embedded_fact_ids = {
                str(item.get("fact_id", ""))
                for item in product_value.get("facts", [])
                if isinstance(item, dict) and item.get("fact_id")
            }
            embedded_value_ids = {
                str(item.get("value_id", ""))
                for item in product_value.get("values", [])
                if isinstance(item, dict) and item.get("value_id")
            }
            if embedded_fact_ids != fact_ids or embedded_value_ids != value_ids:
                add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照ID清单与嵌入记录不一致")
        hashes = product_value.get("file_hashes")
        if not isinstance(hashes, dict) or not hashes:
            add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照缺少文件哈希")
        elif any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in hashes.values()):
            add_error(errors, "E_UPSTREAM_SCHEMA", "商品价值快照存在无效文件哈希")
    if value_expression.get("provided"):
        if not re.fullmatch(r"VE-[0-9a-f]{12}", str(value_expression.get("value_expression_id", ""))):
            add_error(errors, "E_UPSTREAM_SCHEMA", "value_expression_id 格式无效")
        if value_expression.get("product_value_id") != product_value.get("product_value_id"):
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现与商品价值的product_value_id不一致")
        for field, label in (("brand", "品牌"), ("product", "商品"), ("sku", "SKU")):
            if str(value_expression.get(field, "")).strip() != str(manifest.get(field, "")).strip():
                add_error(errors, "E_IDENTITY_MIXED", f"卖点呈现上游{label}与页面交付不一致")
        if (
            str(value_expression.get("category", "")).strip()
            and str(manifest.get("category", "")).strip()
            and str(value_expression.get("category", "")).strip()
            != str(manifest.get("category", "")).strip()
        ):
            add_error(errors, "E_IDENTITY_MIXED", "卖点呈现上游类目与页面交付不一致")
        hashes = value_expression.get("file_hashes")
        if not isinstance(hashes, dict) or not hashes:
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照缺少文件哈希")
        elif any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in hashes.values()):
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照存在无效文件哈希")
        vis_records = value_expression.get("vis")
        if not isinstance(vis_records, list):
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照vis必须是数组")
            vis_records = []
        embedded_vis_ids = {
            str(item.get("vis_id", ""))
            for item in vis_records
            if isinstance(item, dict) and item.get("vis_id")
        }
        if embedded_vis_ids != vis_ids:
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照VIS清单与嵌入记录不一致")
        if len(embedded_vis_ids) != len(vis_records):
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照存在空白或重复VIS ID")
        if value_expression.get("upstream_product_value_id") != product_value.get("product_value_id"):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌商品价值ID与当前底座不一致")
        if str(value_expression.get("upstream_output_version", "")) != str(product_value.get("output_version", "")):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌商品价值版本已过期")
        if str(value_expression.get("upstream_analysis_status", "")) != str(product_value.get("analysis_status", "")):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌商品价值分析状态已变化")
        if str(value_expression.get("upstream_delivery_status", "")) != str(product_value.get("delivery_status", "")):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌商品价值交付状态已变化")
        if str(value_expression.get("p0_status", "")) != str(product_value.get("p0_status", "")):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌P0状态已变化")
        if str(value_expression.get("recommended_value_id", "")) != str(product_value.get("recommended_value_id", "")):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现内嵌推荐价值与当前P0不一致")
        upstream_hashes = value_expression.get("upstream_file_hashes")
        current_hashes = product_value.get("file_hashes")
        if not isinstance(upstream_hashes, dict) or not isinstance(current_hashes, dict):
            add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现缺少商品价值文件哈希快照")
        elif any(upstream_hashes.get(name) != digest for name, digest in current_hashes.items()):
            add_error(errors, "E_UPSTREAM_STALE", "卖点呈现引用的商品价值文件已变化")
        valid_vis_ids: set[str] = set()
        for item in vis_records:
            if not isinstance(item, dict):
                add_error(errors, "E_UPSTREAM_SCHEMA", "卖点呈现快照VIS必须是对象")
                continue
            vis_id = str(item.get("vis_id", "")).strip()
            objects = item.get("applicable_objects")
            if (
                vis_id
                and str(item.get("value_id", "")) in value_ids
                and isinstance(objects, list)
                and "商品页" in objects
                and item.get("validation_status") not in {"", "blocked", "stale"}
                and all(nonempty(item, field) for field in ("human_language", "must_keep", "boundary"))
            ):
                valid_vis_ids.add(vis_id)
            else:
                add_error(errors, "E_UPSTREAM_SCHEMA", f"{vis_id or '未编号VIS'}不满足商品页可调用条件")

    recommended = str(product_value.get("recommended_value_id", ""))
    values_records = product_value.get("values")
    if not isinstance(values_records, list):
        values_records = []
    recommended_values = [
        item for item in values_records
        if isinstance(item, dict) and str(item.get("value_id", "")) == recommended
    ]
    recommended_value_usable = bool(
        len(recommended_values) == 1
        and recommended_values[0].get("downstream_readiness") in VALUE_USABLE_READINESS
    )
    product_value_usable = bool(
        product_value.get("provided")
        and product_value.get("analysis_status") in UPSTREAM_ANALYSIS_STATUSES
        and product_value.get("delivery_status") in UPSTREAM_DELIVERY_STATUSES
        and product_value.get("p0_status") in P0_USABLE_STATUSES
        and recommended
        and recommended in value_ids
        and recommended_value_usable
    )
    value_expression_usable = bool(
        value_expression.get("provided")
        and product_value_usable
        and value_expression.get("analysis_status") in UPSTREAM_ANALYSIS_STATUSES
        and value_expression.get("delivery_status") in UPSTREAM_DELIVERY_STATUSES
        and value_expression.get("product_value_id") == product_value.get("product_value_id")
        and all(
            str(value_expression.get(field, "")).strip() == str(manifest.get(field, "")).strip()
            for field in ("brand", "product", "sku")
        )
        and value_expression.get("upstream_product_value_id") == product_value.get("product_value_id")
        and str(value_expression.get("upstream_output_version", "")) == str(product_value.get("output_version", ""))
        and str(value_expression.get("upstream_analysis_status", "")) == str(product_value.get("analysis_status", ""))
        and str(value_expression.get("upstream_delivery_status", "")) == str(product_value.get("delivery_status", ""))
        and str(value_expression.get("p0_status", "")) == str(product_value.get("p0_status", ""))
        and str(value_expression.get("recommended_value_id", "")) == recommended
        and isinstance(value_expression.get("upstream_file_hashes"), dict)
        and isinstance(product_value.get("file_hashes"), dict)
        and all(
            value_expression.get("upstream_file_hashes", {}).get(name) == digest
            for name, digest in product_value.get("file_hashes", {}).items()
        )
        and vis_ids
        and valid_vis_ids == vis_ids
    )
    if product_value.get("usable") is not product_value_usable:
        add_error(errors, "E_UPSTREAM_STATUS_FORGED", "商品价值usable与快照状态、P0和价值ID不一致")
    if value_expression.get("usable") is not value_expression_usable:
        add_error(errors, "E_UPSTREAM_STATUS_FORGED", "卖点呈现usable与快照状态、SKU和VIS不一致")

    run_status = manifest.get("run_status")
    if run_status == "ready" and not (
        product_value_usable
        and value_expression_usable
        and product_value.get("p0_status") in P0_READY_STATUSES
    ):
        add_error(errors, "E_RUN_STATUS", "ready 必须同时有可用商品价值和卖点呈现")
    if (
        run_status == "partial"
        and not product_value_usable
        and manifest.get("analysis_mode") != "enhance_with_evidence"
    ):
        add_error(errors, "E_RUN_STATUS", "partial 必须有可用商品价值或处于补充资料增强模式")
    if run_status == "degraded_no_product_value" and product_value_usable:
        add_error(errors, "E_RUN_STATUS", "有可用商品价值时不得标为degraded_no_product_value")
    return fact_ids, value_ids, vis_ids, product_value_usable, value_expression_usable


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.expanduser().resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []
    data_paths = {
        name: paths[name]
        for name in (
            "manifest", "upstream", "sources", "supporting_sources", "claims",
            "coverage", "components", "chain", "matches", "decisions", "actions", "validation", "gaps",
        )
    }
    missing = [str(path) for path in data_paths.values() if not path.is_file()]
    if missing:
        add_error(errors, "E_FILE_MISSING", f"缺少必需文件: {', '.join(missing)}")
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}
    try:
        manifest = read_json(paths["manifest"])
        upstream = read_json(paths["upstream"])
        sources = read_jsonl(paths["sources"])
        supporting_sources = read_jsonl(paths["supporting_sources"])
        claims = read_jsonl(paths["claims"])
        coverage = read_jsonl(paths["coverage"])
        components = read_jsonl(paths["components"])
        chain = read_json(paths["chain"])
        matches = read_jsonl(paths["matches"])
        decisions = read_jsonl(paths["decisions"])
        actions = read_jsonl(paths["actions"])
        validations = read_jsonl(paths["validation"])
        gaps = read_jsonl(paths["gaps"])
        routing = read_json(paths["routing"]) if paths["routing"].is_file() else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        add_error(errors, "E_PARSE", str(exc))
        return {"status": "failed", "delivery": str(delivery), "errors": errors, "warnings": warnings, "counts": {}}

    counts = {
        "sources": len(sources),
        "supporting_sources": len(supporting_sources),
        "claims": len(claims),
        "coverage_rows": len(coverage),
        "components": len(components),
        "content_decision_matches": len(matches),
        "chain_findings": len(chain.get("chain_findings", [])) if isinstance(chain, dict) else 0,
        "decisions": len(decisions),
        "priority_actions": len(actions),
        "validation_tasks": len(validations),
        "gaps": len(gaps),
        "routing_decisions": 1 if routing else 0,
    }

    missing_manifest = missing_fields(manifest, MANIFEST_FIELDS)
    if missing_manifest:
        add_error(errors, "E_MANIFEST_SCHEMA", f"page_manifest缺少字段: {', '.join(missing_manifest)}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        add_error(errors, "E_VERSION_DRIFT", "schema_version与脚本不一致")
    if manifest.get("skill_version") != SKILL_VERSION:
        add_error(errors, "E_VERSION_DRIFT", "skill_version与脚本不一致")
    if not re.fullmatch(r"PP-[0-9a-f]{12}", str(manifest.get("product_page_id", ""))):
        add_error(errors, "E_MANIFEST_SCHEMA", "product_page_id格式无效")
    elif manifest.get("product_page_id") != product_page_id(
        str(manifest.get("brand", "")),
        str(manifest.get("product", "")),
        str(manifest.get("sku", "")),
        str(manifest.get("output_version", "")),
    ):
        add_error(errors, "E_IDENTITY_MIXED", "product_page_id与品牌、商品、SKU及版本不一致")
    for field in ("brand", "product", "sku", "page_snapshot_time", "output_version", "created_at", "updated_at"):
        if not nonempty(manifest, field):
            add_error(errors, "E_MANIFEST_SCHEMA", f"page_manifest缺少有效{field}")
    if manifest.get("scope") not in SCOPES:
        add_error(errors, "E_MODE_SCOPE", "scope不在允许范围")
    if manifest.get("task") not in TASKS:
        add_error(errors, "E_MODE_SCOPE", "task不在允许范围")
    if manifest.get("analysis_mode") not in ANALYSIS_MODES:
        add_error(errors, "E_MODE_SCOPE", "analysis_mode不在允许范围")
    if manifest.get("analysis_mode") == "diagnose_existing" and supporting_sources:
        add_error(errors, "E_MODE_SCOPE", "diagnose_existing不得混入补充资料")
    if manifest.get("analysis_mode") == "enhance_with_evidence" and not (
        supporting_sources
        or upstream.get("product_value", {}).get("provided")
        or upstream.get("value_expression", {}).get("provided")
    ):
        add_error(errors, "E_MODE_SCOPE", "enhance_with_evidence缺少补充资料或可选上游")
    if manifest.get("delivery_mode") not in DELIVERY_MODES:
        add_error(errors, "E_MODE_SCOPE", "delivery_mode不在允许范围")
    if manifest.get("run_status") not in RUN_STATUSES:
        add_error(errors, "E_RUN_STATUS", "run_status不在允许范围")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        add_error(errors, "E_RUN_STATUS", "analysis_status不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        add_error(errors, "E_RUN_STATUS", "delivery_status不在允许范围")
    if manifest.get("analysis_status") == "draft":
        add_error(errors, "E_RUN_STATUS", "analysis_status=draft不得正式交付")
    if not isinstance(manifest.get("limitations"), list):
        add_error(errors, "E_MANIFEST_SCHEMA", "limitations必须是数组")
    if manifest.get("delivery_mode") == "course" and manifest.get("task") != "diagnose":
        add_error(errors, "E_MODE_SCOPE", "课程模式只支持diagnose")
    if manifest.get("task") == "route" and not str(manifest.get("entry_context", "")).strip():
        add_error(errors, "E_MODE_SCOPE", "route缺少入口语境")
    if manifest.get("task") == "route":
        if manifest.get("delivery_mode") != "professional":
            add_error(errors, "E_MODE_SCOPE", "route只支持专业模式")
        if routing is None:
            add_error(errors, "E_ROUTE_DECISION_MISSING", "route缺少routing_decision.json")
    elif routing is not None:
        add_error(errors, "E_MODE_SCOPE", "非route任务不得混入routing_decision.json")
    if manifest.get("scope") == "combined" and not str(manifest.get("cross_surface_summary", "")).strip():
        add_error(errors, "E_COMBINED_CROSSCHECK_MISSING", "combined缺少跨触点一致性总结")
    if manifest.get("scope") != "combined" and manifest.get("cross_surface_summary") != "not_applicable":
        add_error(errors, "E_MODE_SCOPE", "单一页面范围的cross_surface_summary必须为not_applicable")
    if manifest.get("run_status") == "stopped":
        if manifest.get("analysis_status") != "insufficient" or manifest.get("delivery_status") != "blocked":
            add_error(errors, "E_RUN_STATUS", "stopped必须使用insufficient+blocked")
    elif manifest.get("analysis_status") not in {"complete", "partial", "stale"}:
        add_error(errors, "E_RUN_STATUS", "非停止正式交付必须是complete、partial或stale")
    analysis_status = manifest.get("analysis_status")
    delivery_status = manifest.get("delivery_status")
    allowed_pairings = {
        "complete": {"ready", "conditional"},
        "partial": {"conditional"},
        "insufficient": {"blocked"},
        "stale": {"stale"},
        "draft": {"blocked"},
    }
    if delivery_status not in allowed_pairings.get(str(analysis_status), set()):
        add_error(errors, "E_STATUS_PAIR", f"{analysis_status}+{delivery_status}不是允许的状态配对")
    if analysis_status == "stale" or delivery_status == "stale":
        add_error(errors, "E_STALE_DELIVERY", "stale交付不得作为当前正式结果")

    (
        fact_ids,
        value_ids,
        vis_ids,
        product_value_usable,
        value_expression_usable,
    ) = validate_upstream(upstream, manifest, errors)
    restricted_topics = upstream_restriction_topics(upstream)

    if manifest.get("source_count") != len(sources):
        add_error(errors, "E_PAGE_REF_MISSING", "source_count与来源清单数量不一致")
    if not sources:
        add_error(errors, "E_SURFACE_MISSING", "来源清单为空")
    source_ids: set[str] = set()
    versions: set[str] = set()
    for index, row in enumerate(sources, start=1):
        label = f"source_inventory第{index}条"
        missing = missing_fields(row, SOURCE_FIELDS)
        if missing:
            add_error(errors, "E_PAGE_REF_MISSING", f"{label}缺少字段: {', '.join(missing)}")
        source_id = str(row.get("source_file_id", ""))
        if not re.fullmatch(r"PAGE-SF-\d{3,}", source_id):
            add_error(errors, "E_PAGE_REF_INVALID", f"{label} source_file_id格式无效")
        source_ids.add(source_id)
        versions.add(str(row.get("source_version", "")))
        if row.get("page_scope") not in PAGE_SCOPES:
            add_error(errors, "E_MODE_SCOPE", f"{source_id} page_scope无效")
        if row.get("sequence_status") not in SEQUENCE_STATUSES:
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id} sequence_status无效")
        if row.get("readability_status") not in READABILITY_STATUSES:
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id} readability_status无效")
        if not isinstance(row.get("quality_excluded"), bool):
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id} quality_excluded必须为布尔值")
        if row.get("quality_excluded") and not str(row.get("quality_exclusion_reason", "")).strip():
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id}排除低质量文件时必须说明原因")
        if row.get("quality_excluded") and row.get("readability_status") in {"readable", "partially_readable"}:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}不能既作为可读页面又标为质量排除")
        media = str(row.get("media_type", ""))
        extension = str(row.get("extension", "")).lower()
        if media not in MEDIA_EXTENSIONS:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id} media_type无效")
        elif media != "other" and extension not in MEDIA_EXTENSIONS[media]:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}扩展名与media_type不一致")
        if media == "archive" and row.get("readability_status") != "unsupported_archive":
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}压缩包未解压不得标为可读")
        if media == "other" and row.get("readability_status") in {"readable", "partially_readable"}:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}未知文件类型不得直接标为可读")
        if (
            not isinstance(row.get("sequence"), int)
            or isinstance(row.get("sequence"), bool)
            or row.get("sequence", 0) < 1
        ):
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id} sequence必须为正整数")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id} sha256无效")
        relative_path = str(row.get("relative_path", ""))
        if not relative_path or re.search(
            r"(?:^[A-Za-z]:|^/|^\\|(?:^|/)\.\.(?:/|$))",
            relative_path,
        ):
            add_error(errors, "E_ABSOLUTE_PATH_LEAK", f"{source_id} relative_path不是安全相对路径")
        if not nonempty(row, "source_version") or not nonempty(row, "capture_time"):
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id}缺少版本或采集时间")
        if row.get("duplicate_of") and row.get("duplicate_of") == source_id:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}不能重复指向自身")
    source_duplicates = duplicate_ids(sources, "source_file_id")
    if source_duplicates:
        add_error(errors, "E_PAGE_REF_INVALID", f"来源ID重复: {', '.join(source_duplicates)}")
    for row in sources:
        if row.get("duplicate_of") and row.get("duplicate_of") not in source_ids:
            add_error(errors, "E_PAGE_REF_INVALID", f"{row.get('source_file_id')} duplicate_of未知")
    expected_versions = {"current", "comparison"} if manifest.get("task") == "version_review" else {"current"}
    if versions != expected_versions:
        add_error(
            errors,
            "E_VERSION_LABEL",
            f"本次任务的来源版本必须严格为{sorted(expected_versions)}，当前为{sorted(versions)}",
        )
    confirmed_sequences: dict[tuple[str, str], list[int]] = {}
    for row in sources:
        if row.get("sequence_status") != "confirmed" or row.get("page_scope") not in COMPONENT_SCOPES:
            continue
        key = (str(row.get("source_version", "")), str(row.get("page_scope", "")))
        if isinstance(row.get("sequence"), int) and not isinstance(row.get("sequence"), bool):
            confirmed_sequences.setdefault(key, []).append(row.get("sequence"))
    for key, sequence_values in confirmed_sequences.items():
        if len(sequence_values) != len(set(sequence_values)):
            add_error(errors, "E_SEQUENCE_CONFLICT", f"{key[0]}版{key[1]}存在重复页面顺序")
        if sequence_values and sorted(sequence_values) != list(range(1, max(sequence_values) + 1)):
            warnings.append(f"{key[0]}版{key[1]}的已确认顺序存在缺号，请核对是否缺页")
    if manifest.get("task") == "version_review":
        for version in ("current", "comparison"):
            version_rows = [row for row in sources if row.get("source_version") == version]
            capture_times = {str(row.get("capture_time", "")).strip() for row in version_rows}
            if not version_rows or any(not is_zoned_iso(value) for value in capture_times):
                add_error(errors, "E_VERSION_TIME", f"{version}版每条来源都必须有带时区的真实页面时间")
            if len(capture_times) != 1:
                add_error(errors, "E_VERSION_TIME", f"{version}版混入多个页面时间")
            if version == "current" and capture_times != {str(manifest.get("page_snapshot_time", "")).strip()}:
                add_error(errors, "E_VERSION_TIME", "current版来源时间与page_manifest不一致")

    supporting_source_ids: set[str] = set()
    supporting_lookup: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(supporting_sources, start=1):
        label = f"supporting_source_inventory第{index}条"
        missing = missing_fields(row, SUPPORTING_SOURCE_FIELDS)
        if missing:
            add_error(errors, "E_SUPPORT_SOURCE", f"{label}缺少字段: {', '.join(missing)}")
        source_id = str(row.get("supporting_source_id", ""))
        if not re.fullmatch(r"SUP-SF-\d{3,}", source_id):
            add_error(errors, "E_SUPPORT_SOURCE", f"{label} supporting_source_id格式无效")
        supporting_source_ids.add(source_id)
        supporting_lookup[source_id] = row
        if row.get("source_role") not in SUPPORTING_SOURCE_ROLES:
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id} source_role无效")
        if row.get("readability_status") not in READABILITY_STATUSES:
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id} readability_status无效")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id} sha256无效")
        relative_path = str(row.get("relative_path", ""))
        if not relative_path or re.search(r"(?:^[A-Za-z]:|^/|^\\|(?:^|/)\.\.(?:/|$))", relative_path):
            add_error(errors, "E_ABSOLUTE_PATH_LEAK", f"{source_id} relative_path不是安全相对路径")
        media = str(row.get("media_type", ""))
        extension = str(row.get("extension", "")).lower()
        if media not in MEDIA_EXTENSIONS:
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id} media_type无效")
        elif media != "other" and extension not in MEDIA_EXTENSIONS[media]:
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id}扩展名与media_type不一致")
        if media == "archive" and row.get("readability_status") != "unsupported_archive":
            add_error(errors, "E_SUPPORT_SOURCE", f"{source_id}压缩包未解压不得标为可读")
    duplicate_supporting = duplicate_ids(supporting_sources, "supporting_source_id")
    if duplicate_supporting:
        add_error(errors, "E_SUPPORT_SOURCE", f"补充来源ID重复: {', '.join(duplicate_supporting)}")
    for row in supporting_sources:
        duplicate_of = str(row.get("duplicate_of", ""))
        if duplicate_of and duplicate_of not in supporting_source_ids:
            add_error(errors, "E_SUPPORT_SOURCE", f"{row.get('supporting_source_id')} duplicate_of未知")

    claim_ids: set[str] = set()
    usable_claim_ids: set[str] = set()
    claim_lookup: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(claims, start=1):
        label = f"claim_ledger第{index}条"
        missing = missing_fields(row, CLAIM_FIELDS)
        if missing:
            add_error(errors, "E_CLAIM_SCHEMA", f"{label}缺少字段: {', '.join(missing)}")
        claim_id = str(row.get("claim_id", ""))
        if not re.fullmatch(r"CLAIM-\d{3,}", claim_id):
            add_error(errors, "E_CLAIM_SCHEMA", f"{label} claim_id格式无效")
        claim_ids.add(claim_id)
        claim_lookup[claim_id] = row
        if row.get("claim_type") not in SUPPORT_CLAIM_TYPES:
            add_error(errors, "E_CLAIM_SCHEMA", f"{claim_id} claim_type无效")
        if row.get("evidence_status") not in CLAIM_EVIDENCE_STATUSES:
            add_error(errors, "E_CLAIM_SCHEMA", f"{claim_id} evidence_status无效")
        if row.get("dynamic_status") not in DYNAMIC_STATUSES:
            add_error(errors, "E_CLAIM_SCHEMA", f"{claim_id} dynamic_status无效")
        for field in (
            "statement", "applicable_sku", "support_scope", "can_support",
            "cannot_prove", "human_confirmation", "boundary",
        ):
            if not nonempty(row, field):
                add_error(errors, "E_CLAIM_SCHEMA", f"{claim_id}缺少{field}")
        validate_reference_list(
            errors, claim_id, row, "supporting_source_ids", supporting_source_ids, "E_SUPPORT_SOURCE"
        )
        referenced = [supporting_lookup.get(str(item), {}) for item in list_value(row, "supporting_source_ids")]
        if not referenced:
            add_error(errors, "E_CLAIM_UNGROUNDED", f"{claim_id}必须绑定补充资料")
        if row.get("evidence_status") == "usable":
            if row.get("claim_type") not in {"confirmed_fact", "dynamic_snapshot"}:
                add_error(errors, "E_CLAIM_OVERREACH", f"{claim_id}当前类型不得标为usable")
            if not referenced or any(
                item.get("readability_status") not in {"readable", "partially_readable"}
                for item in referenced
            ):
                add_error(errors, "E_CLAIM_UNGROUNDED", f"{claim_id}的usable状态缺少可读补充来源")
            else:
                usable_claim_ids.add(claim_id)
        if row.get("claim_type") == "user_signal" and row.get("evidence_status") == "usable":
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{claim_id}把用户信号升级为商品事实")
        if row.get("claim_type") == "competitor_observation" and row.get("evidence_status") == "usable":
            add_error(errors, "E_CLAIM_OVERREACH", f"{claim_id}把竞品观察升级为本商品事实")
    duplicate_claims = duplicate_ids(claims, "claim_id")
    if duplicate_claims:
        add_error(errors, "E_CLAIM_SCHEMA", f"主张ID重复: {', '.join(duplicate_claims)}")
    if (
        manifest.get("run_status") == "partial"
        and not product_value_usable
        and not usable_claim_ids
    ):
        add_error(errors, "E_RUN_STATUS", "没有可用商品价值时，partial增强模式至少需要一条可用补充事实")

    requested_scopes = (
        set(COMPONENT_SCOPES)
        if manifest.get("scope") == "combined"
        else {str(manifest.get("scope", ""))}
    )
    expected_coverage_pairs = {
        (version, scope)
        for version in expected_versions
        for scope in requested_scopes
        if scope in COMPONENT_SCOPES
    }
    coverage_pairs: list[tuple[str, str]] = []
    coverage_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(coverage, start=1):
        coverage_id = str(row.get("coverage_id", ""))
        missing = missing_fields(row, COVERAGE_FIELDS)
        if missing:
            add_error(errors, "E_COVERAGE_SCHEMA", f"page_coverage第{index}条缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"COV-\d{3,}", coverage_id):
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id or index} coverage_id格式无效")
        version = str(row.get("source_version", ""))
        scope = str(row.get("scope", ""))
        pair = (version, scope)
        coverage_pairs.append(pair)
        coverage_lookup[pair] = row
        if version not in expected_versions or scope not in COMPONENT_SCOPES:
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id}版本或页面范围不属于本次任务")
        declared = row.get("page_declared_count")
        if declared != "unknown" and (
            not isinstance(declared, int) or isinstance(declared, bool) or declared < 1
        ):
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id} page_declared_count必须为正整数或unknown")
        for field in ("observed_source_count", "quality_excluded_count", "readable_source_count"):
            value = row.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id} {field}必须为非负整数")
        if not isinstance(row.get("sequence_gap"), bool):
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id} sequence_gap必须为布尔值")
        if row.get("coverage_status") not in COVERAGE_STATUSES:
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id} coverage_status无效")
        if pair in expected_coverage_pairs and row.get("coverage_status") == "not_applicable":
            add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id}属于本次要求范围，不能标为不适用")
        for field in ("basis", "boundary"):
            if not nonempty(row, field):
                add_error(errors, "E_COVERAGE_SCHEMA", f"{coverage_id}缺少{field}")

        pair_sources = [
            item for item in sources
            if item.get("source_version") == version
            and item.get("page_scope") == scope
            and not str(item.get("duplicate_of", "")).strip()
        ]
        observed = len(pair_sources)
        excluded = len([item for item in pair_sources if item.get("quality_excluded") is True])
        readable = len([
            item for item in pair_sources
            if item.get("quality_excluded") is not True
            and item.get("readability_status") in {"readable", "partially_readable"}
        ])
        sequence_values = [
            item.get("sequence") for item in pair_sources
            if isinstance(item.get("sequence"), int) and not isinstance(item.get("sequence"), bool)
        ]
        actual_gap = bool(sequence_values) and sorted(sequence_values) != list(
            range(1, max(sequence_values) + 1)
        )
        if row.get("observed_source_count") != observed:
            add_error(errors, "E_COVERAGE_COUNT", f"{coverage_id}登记数量与来源清单不一致")
        if row.get("quality_excluded_count") != excluded:
            add_error(errors, "E_COVERAGE_COUNT", f"{coverage_id}质量排除数量与来源清单不一致")
        if row.get("readable_source_count") != readable:
            add_error(errors, "E_COVERAGE_COUNT", f"{coverage_id}可读数量与来源清单不一致")
        if row.get("sequence_gap") != actual_gap:
            add_error(errors, "E_COVERAGE_COUNT", f"{coverage_id}顺序缺口判断与来源清单不一致")
        if isinstance(declared, int) and declared != observed:
            add_error(errors, "E_COVERAGE_COUNT", f"{coverage_id}页面声明数量与当前来源数量不一致")
        if row.get("coverage_status") == "complete_observed":
            fully_reviewed = all(
                item.get("quality_excluded") is True
                or (
                    item.get("readability_status") in {"readable", "partially_readable"}
                    and item.get("sequence_status") == "confirmed"
                )
                for item in pair_sources
            )
            if not pair_sources or not fully_reviewed or actual_gap or readable + excluded != observed:
                add_error(errors, "E_COVERAGE_FALSE_COMPLETE", f"{coverage_id}不能标为本次提供范围已看全")
    if set(coverage_pairs) != expected_coverage_pairs or len(coverage_pairs) != len(set(coverage_pairs)):
        add_error(errors, "E_COVERAGE_SCHEMA", "page_coverage必须对本次每个版本与页面范围各保留且只保留一条")
    if manifest.get("run_status") == "ready":
        incomplete = [
            pair for pair in expected_coverage_pairs
            if coverage_lookup.get(pair, {}).get("coverage_status") != "complete_observed"
        ]
        if incomplete:
            add_error(errors, "E_COVERAGE_NOT_READY", "ready状态必须确认本次要求的页面范围均已逐张看完")
    if any(
        coverage_lookup.get(pair, {}).get("coverage_status") in {"partial_observed", "unknown"}
        for pair in expected_coverage_pairs
    ):
        has_page_gap = any(
            item.get("return_to") == "page_material" and item.get("state") != "closed"
            for item in gaps
        )
        if not has_page_gap:
            add_error(errors, "E_UNKNOWN_DROPPED", "页面未确认看全时必须保留page_material开放缺口")

    readable_by_scope = {
        scope: [
            row for row in sources
            if row.get("page_scope") == scope
            and row.get("readability_status") in {"readable", "partially_readable"}
        ]
        for scope in COMPONENT_SCOPES
    }
    if manifest.get("task") == "version_review":
        readable_scopes_by_version = {
            version: {
                str(row.get("page_scope"))
                for row in sources
                if row.get("source_version") == version
                and row.get("readability_status") in {"readable", "partially_readable"}
                and row.get("page_scope") in COMPONENT_SCOPES
            }
            for version in ("current", "comparison")
        }
        common_scopes = readable_scopes_by_version["current"] & readable_scopes_by_version["comparison"]
        requested_scope = manifest.get("scope")
        if requested_scope in COMPONENT_SCOPES and requested_scope not in common_scopes:
            add_error(errors, "E_VERSION_SURFACE", f"两版都必须有可读{requested_scope}页面")
        if requested_scope == "combined" and not common_scopes:
            add_error(errors, "E_VERSION_SURFACE", "两版没有共同可读页面范围，不能正式对照")
    if manifest.get("run_status") != "stopped":
        scope = manifest.get("scope")
        if scope in COMPONENT_SCOPES and not readable_by_scope[scope]:
            add_error(errors, "E_SURFACE_MISSING", f"{scope}没有可读页面")
        if scope == "combined" and not (readable_by_scope["main_images"] or readable_by_scope["detail_page"]):
            add_error(errors, "E_SURFACE_MISSING", "combined没有任何可读主图或详情页")
        if scope == "combined" and manifest.get("run_status") == "ready":
            if not readable_by_scope["main_images"] or not readable_by_scope["detail_page"]:
                add_error(errors, "E_COMBINED_CROSSCHECK_MISSING", "ready+combined必须同时有可读主图和详情页")

    source_lookup = {str(row.get("source_file_id", "")): row for row in sources}
    component_ids: set[str] = set()
    for index, row in enumerate(components, start=1):
        label = f"page_component第{index}条"
        missing = missing_fields(row, COMPONENT_FIELDS)
        if missing:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{label}缺少字段: {', '.join(missing)}")
        component_id = str(row.get("component_id", ""))
        if not re.fullmatch(r"COMP-\d{3,}", component_id):
            add_error(errors, "E_PAGE_REF_INVALID", f"{label} component_id格式无效")
        component_ids.add(component_id)
        if row.get("scope") not in COMPONENT_SCOPES:
            add_error(errors, "E_MODE_SCOPE", f"{component_id} scope无效")
        if manifest.get("scope") in COMPONENT_SCOPES and row.get("scope") != manifest.get("scope"):
            add_error(errors, "E_MODE_SCOPE", f"{component_id}越过本次页面范围")
        if row.get("readability_status") not in {"readable", "partially_readable"}:
            add_error(errors, "E_PAGE_REF_MISSING", f"{component_id}不能建立在不可读页面上")
        if row.get("dynamic_status") not in DYNAMIC_STATUSES:
            add_error(errors, "E_DYNAMIC_TIME_SCOPE", f"{component_id} dynamic_status无效")
        if row.get("content_layer") not in CONTENT_LAYERS:
            add_error(errors, "E_COMPONENT_CLASSIFICATION", f"{component_id} content_layer无效")
        if row.get("module_role") not in MODULE_ROLES:
            add_error(errors, "E_COMPONENT_CLASSIFICATION", f"{component_id} module_role无效")
        if row.get("component_applicability") not in COMPONENT_APPLICABILITY:
            add_error(errors, "E_SKU_APPLICABILITY", f"{component_id} component_applicability无效")
        if row.get("information_node_type") not in INFORMATION_NODE_TYPES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} information_node_type无效")
        if row.get("primary_decision_name") not in DECISION_NAMES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} primary_decision_name无效")
        elif row.get("primary_decision_name") not in list_value(row, "decision_names"):
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id}主要判断不在decision_names中")
        if row.get("match_status") not in MATCH_STATUSES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} match_status无效")
        if row.get("package_version_status") not in PACKAGE_VERSION_STATUSES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} package_version_status无效")
        if row.get("adjacency_status") not in ADJACENCY_STATUSES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} adjacency_status无效")
        if row.get("claim_level") not in CLAIM_LEVELS:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} claim_level无效")
        if row.get("claim_scope") not in CLAIM_SCOPES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{component_id} claim_scope无效")
        if not nonempty(row, "support_target"):
            add_error(errors, "E_COMPONENT_CLASSIFICATION", f"{component_id}缺少support_target")
        if row.get("content_layer") == "current_campaign" and row.get("dynamic_status") == "not_dynamic":
            add_error(errors, "E_DYNAMIC_TIME_SCOPE", f"{component_id}活动信息不能标为长期静态信息")
        if row.get("module_role") in {"mechanism", "evidence", "experience_demo"} and str(
            row.get("support_target", "")
        ).strip() in {"", "not_applicable"}:
            add_error(errors, "E_SUPPORT_TARGET_MISSING", f"{component_id}必须写明它在支持哪项主张")
        if row.get("change_type") not in ACTION_TYPES:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{component_id} change_type无效")
        if row.get("status") not in ACTION_STATUSES:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{component_id} status无效")
        elif row.get("status") not in ACTIVE_ACTION_STATUSES:
            add_error(errors, "E_BLOCKED_ACTION", f"{component_id}处于blocked或stale，不得进入正式执行页")
        if (
            not isinstance(row.get("sequence"), int)
            or isinstance(row.get("sequence"), bool)
            or row.get("sequence", 0) < 1
        ):
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{component_id} sequence必须为正整数")
        for field in (
            "page_location", "current_observation", "current_role", "recommended_role",
            "execution_instruction", "required_material", "acceptance_check", "status", "boundary",
        ):
            if not nonempty(row, field):
                add_error(errors, "E_ACTION_FIELDS_MISSING", f"{component_id}缺少{field}")
        validate_reference_list(errors, component_id, row, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, component_id, row, "fact_ids", fact_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, component_id, row, "value_ids", value_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, component_id, row, "vis_ids", vis_ids, "E_UPSTREAM_REF_MISSING")
        if not product_value_usable and (
            list_value(row, "fact_ids")
            or list_value(row, "value_ids")
            or list_value(row, "vis_ids")
        ):
            add_error(errors, "E_P0_CREATED", f"{component_id}在无可用商品价值时调用了上游资产")
        if not list_value(row, "source_file_ids"):
            add_error(errors, "E_PAGE_REF_MISSING", f"{component_id}至少引用一个页面来源")
        for source_id in list_value(row, "source_file_ids"):
            source = source_lookup.get(str(source_id), {})
            if source and source.get("page_scope") != row.get("scope"):
                add_error(errors, "E_SCOPE_REFERENCE", f"{component_id}引用了不同页面范围的{source_id}")
        if list_value(row, "vis_ids") and not value_expression_usable:
            add_error(errors, "E_UPSTREAM_REF_MISSING", f"{component_id}调用了不可用VIS")
        for name in list_value(row, "decision_names"):
            if name not in DECISION_NAMES:
                add_error(errors, "E_ACTION_FIELDS_MISSING", f"{component_id}引用未知用户判断{name}")
        if not isinstance(row.get("category_task_ids"), list):
            add_error(errors, "E_CATEGORY_TASK_REF", f"{component_id}.category_task_ids必须是数组")
        elif manifest.get("run_status") != "stopped" and not row.get("category_task_ids"):
            add_error(errors, "E_CATEGORY_TASK_REF", f"{component_id}至少承接一个细分类目购买任务")
        component_text = record_text(row)
        if contains_effect_promise(component_text):
            add_error(errors, "E_EFFECT_PROMISE", f"{component_id}包含未经验证的效果承诺")
        if any(pattern.search(component_text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", f"{component_id}试图重选或替换核心价值")
        if any(pattern.search(component_text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{component_id}把评论或评价升级为事实")
        validate_upstream_boundary(
            errors,
            component_id,
            "\n".join(
                str(row.get(field, ""))
                for field in (
                    "recommended_role", "execution_instruction", "acceptance_check", "boundary"
                )
            ),
            row.get("change_type"),
            restricted_topics,
        )
    component_duplicates = duplicate_ids(components, "component_id")
    if component_duplicates:
        add_error(errors, "E_PAGE_REF_INVALID", f"组件ID重复: {', '.join(component_duplicates)}")
    if manifest.get("run_status") != "stopped" and not components:
        add_error(errors, "E_ACTION_UNGROUNDED", "非停止交付至少需要一个页面组件观察")
    for component_scope in COMPONENT_SCOPES:
        sequence_values = [
            row.get("sequence") for row in components
            if row.get("scope") == component_scope
            and isinstance(row.get("sequence"), int)
            and not isinstance(row.get("sequence"), bool)
        ]
        if len(sequence_values) != len(set(sequence_values)):
            add_error(errors, "E_SEQUENCE_CONFLICT", f"{component_scope}组件存在重复执行顺序")

    missing_chain = missing_fields(chain, CHAIN_FIELDS)
    if missing_chain:
        add_error(errors, "E_CHAIN_SCHEMA", f"page_chain缺少字段: {', '.join(missing_chain)}")
    if chain.get("schema_version") != SCHEMA_VERSION:
        add_error(errors, "E_VERSION_DRIFT", "page_chain.schema_version与脚本不一致")

    analysis_target = chain.get("analysis_target")
    if not isinstance(analysis_target, dict):
        add_error(errors, "E_ANALYSIS_TARGET", "page_chain.analysis_target必须是对象")
        analysis_target = {}
    target_required = {
        "analysis_sku", "target_basis", "page_primary_sku_or_variant",
        "visible_option_match_status", "visible_option_evidence",
        "dynamic_snapshot_applicability", "decision", "boundary",
    }
    target_missing = missing_fields(analysis_target, target_required)
    if target_missing:
        add_error(errors, "E_ANALYSIS_TARGET", f"analysis_target缺少字段: {', '.join(target_missing)}")
    if str(analysis_target.get("analysis_sku", "")).strip() != str(manifest.get("sku", "")).strip():
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target.analysis_sku必须与manifest.sku一致")
    if analysis_target.get("target_basis") not in ANALYSIS_TARGET_BASES:
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target.target_basis无效")
    if analysis_target.get("visible_option_match_status") not in VISIBLE_OPTION_MATCH_STATUSES:
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target.visible_option_match_status无效")
    if analysis_target.get("dynamic_snapshot_applicability") not in DYNAMIC_SNAPSHOT_APPLICABILITY:
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target.dynamic_snapshot_applicability无效")
    if analysis_target.get("decision") not in ANALYSIS_TARGET_DECISIONS:
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target.decision无效")
    if not nonempty(analysis_target, "boundary"):
        add_error(errors, "E_ANALYSIS_TARGET", "analysis_target必须写明对象边界")

    non_stopped = manifest.get("run_status") != "stopped"
    if non_stopped and analysis_target.get("decision") != "continue":
        add_error(errors, "E_ANALYSIS_TARGET", "非停止交付必须确认可继续分析")
    if non_stopped and analysis_target.get("target_basis") == "unknown":
        add_error(errors, "E_ANALYSIS_TARGET", "非停止交付必须说明分析SKU的识别依据")
    if non_stopped and analysis_target.get("visible_option_match_status") in {"not_found", "ambiguous"}:
        add_error(errors, "E_ANALYSIS_TARGET", "页面主讲SKU未在可见选项中唯一匹配时必须停止")
    if analysis_target.get("target_basis") == "detail_page_and_visible_option" and analysis_target.get("visible_option_match_status") != "matched":
        add_error(errors, "E_ANALYSIS_TARGET", "依据详情页主讲SKU继续分析时必须在可见选项中匹配")
    for field in (
        "precompleted_decisions", "remaining_decision_tasks", "parallel_routes",
        "surface_coverage",
        "ordered_component_ids", "continuation_handoffs", "chain_findings",
        "aggregate_implications", "presentation_actuality_checks", "variant_routes",
        "quantified_claim_checks", "limitations",
    ):
        if not isinstance(chain.get(field), list):
            add_error(errors, "E_CHAIN_SCHEMA", f"page_chain.{field}必须是数组")

    category_chain = chain.get("category_decision_chain")
    category_task_ids: set[str] = set()
    category_tasks: list[dict[str, Any]] = []
    if not isinstance(category_chain, dict):
        add_error(errors, "E_CATEGORY_CHAIN", "category_decision_chain必须是对象")
        category_chain = {}
    category_chain_required = {
        "subcategory", "decision_context", "basis_type", "maturity", "tasks", "boundary",
    }
    missing_category_chain = missing_fields(category_chain, category_chain_required)
    if missing_category_chain:
        add_error(
            errors,
            "E_CATEGORY_CHAIN",
            f"category_decision_chain缺少字段: {', '.join(missing_category_chain)}",
        )
    if category_chain.get("basis_type") not in CATEGORY_DECISION_BASIS_TYPES:
        add_error(errors, "E_CATEGORY_CHAIN", "category_decision_chain.basis_type无效")
    if category_chain.get("maturity") not in CATEGORY_DECISION_MATURITIES:
        add_error(errors, "E_CATEGORY_CHAIN", "category_decision_chain.maturity无效")
    raw_category_tasks = category_chain.get("tasks")
    if not isinstance(raw_category_tasks, list):
        add_error(errors, "E_CATEGORY_CHAIN", "category_decision_chain.tasks必须是数组")
        raw_category_tasks = []
    category_source_ids = source_ids | supporting_source_ids
    task_sequences: list[int] = []
    task_required_fields = {
        "task_id", "sequence", "task_name", "user_question", "requirement",
        "importance", "basis_summary", "source_file_ids", "boundary",
    }
    for index, task_row in enumerate(raw_category_tasks, start=1):
        if not isinstance(task_row, dict):
            add_error(errors, "E_CATEGORY_CHAIN", f"类目任务第{index}条必须是对象")
            continue
        category_tasks.append(task_row)
        task_id = str(task_row.get("task_id", ""))
        missing_task_fields = missing_fields(task_row, task_required_fields)
        if missing_task_fields:
            add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}缺少字段: {', '.join(missing_task_fields)}")
        if not re.fullmatch(r"CAT-\d{2,}", task_id) or task_id in category_task_ids:
            add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}任务ID无效或重复")
        category_task_ids.add(task_id)
        sequence = task_row.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}.sequence必须为正整数")
        else:
            task_sequences.append(sequence)
        if task_row.get("requirement") not in CATEGORY_TASK_REQUIREMENTS:
            add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}.requirement无效")
        if task_row.get("importance") not in CATEGORY_TASK_IMPORTANCE:
            add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}.importance无效")
        for field in ("task_name", "user_question", "basis_summary", "boundary"):
            if not nonempty(task_row, field):
                add_error(errors, "E_CATEGORY_CHAIN", f"{task_id or index}缺少{field}")
        validate_reference_list(
            errors, task_id or str(index), task_row, "source_file_ids",
            category_source_ids, "E_CATEGORY_TASK_REF",
        )
    if task_sequences and sorted(task_sequences) != list(range(1, len(task_sequences) + 1)):
        add_error(errors, "E_CATEGORY_CHAIN", "细分类目购买任务必须从1连续排序")
    if non_stopped:
        if len(category_tasks) < 2:
            add_error(errors, "E_CATEGORY_CHAIN", "非停止交付至少需要两个细分类目购买任务")
        for field in ("subcategory", "decision_context", "boundary"):
            if not nonempty(category_chain, field):
                add_error(errors, "E_CATEGORY_CHAIN", f"非停止交付缺少category_decision_chain.{field}")
        if category_chain.get("basis_type") == "unknown" or category_chain.get("maturity") == "unknown":
            add_error(errors, "E_CATEGORY_CHAIN", "非停止交付必须明确类目链依据与成熟度")
    if manifest.get("analysis_mode") == "diagnose_existing" and non_stopped:
        if category_chain.get("basis_type") not in {
            "page_visible_hypothesis", "category_reference_hypothesis"
        }:
            add_error(errors, "E_CATEGORY_CHAIN_OVERCLAIM", "只读当前页面时类目链只能使用页面或类目参考假设")
        if category_chain.get("maturity") != "working_hypothesis":
            add_error(errors, "E_CATEGORY_CHAIN_OVERCLAIM", "只读当前页面时类目链必须标为工作假设")
    maturity_basis = {
        "evidence_strengthened": {"page_and_supporting_evidence"},
        "brand_confirmed": {"brand_confirmed"},
        "user_validated": {"user_research_supported"},
    }
    if category_chain.get("maturity") in maturity_basis and category_chain.get("basis_type") not in maturity_basis[
        str(category_chain.get("maturity"))
    ]:
        add_error(errors, "E_CATEGORY_CHAIN_OVERCLAIM", "类目链成熟度与形成依据不一致")

    match_task_counts: Counter[str] = Counter()
    match_lookup: dict[str, dict[str, Any]] = {}
    unresolved_category_task_ids: set[str] = set()
    match_ids: set[str] = set()
    for index, row in enumerate(matches, start=1):
        match_id = str(row.get("match_id", ""))
        missing_match_fields = missing_fields(row, MATCH_FIELDS)
        if missing_match_fields:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"match第{index}条缺少字段: {', '.join(missing_match_fields)}")
        if not re.fullmatch(r"MATCH-\d{3,}", match_id) or match_id in match_ids:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index} ID无效或重复")
        match_ids.add(match_id)
        task_id = str(row.get("category_task_id", ""))
        match_task_counts[task_id] += 1
        match_lookup.setdefault(task_id, row)
        if task_id not in category_task_ids:
            add_error(errors, "E_CATEGORY_TASK_REF", f"{match_id or index}引用未知细分类目任务{task_id}")
        validate_reference_list(errors, match_id or str(index), row, "component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, match_id or str(index), row, "source_file_ids", category_source_ids, "E_PAGE_REF_INVALID")
        if row.get("coverage_status") not in CONTENT_COVERAGE_STATUSES:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}.coverage_status无效")
        if row.get("position_status") not in CONTENT_POSITION_STATUSES:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}.position_status无效")
        if row.get("evidence_connection_status") not in EVIDENCE_CONNECTION_STATUSES:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}.evidence_connection_status无效")
        if row.get("redundancy_status") not in CONTENT_REDUNDANCY_STATUSES:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}.redundancy_status无效")
        for field in (
            "current_content_summary", "match_reason", "user_consequence",
            "recommended_resolution", "boundary",
        ):
            if not nonempty(row, field):
                add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}缺少{field}")
        linked_components = list_value(row, "component_ids")
        if row.get("coverage_status") != "missing" and not linked_components:
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}非缺失任务必须绑定页面内容节点")
        if row.get("coverage_status") == "missing" and row.get("position_status") != "not_present":
            add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}缺失任务的位置必须是not_present")
        if (
            row.get("coverage_status") != "matched"
            or row.get("position_status") != "right_position"
            or row.get("evidence_connection_status") in {"weak", "disconnected", "unknown"}
            or row.get("redundancy_status") in {"duplicated", "overloaded", "unknown"}
        ):
            unresolved_category_task_ids.add(task_id)
        for component_id in linked_components:
            component = next(
                (item for item in components if str(item.get("component_id", "")) == str(component_id)),
                {},
            )
            if component and task_id not in list_value(component, "category_task_ids"):
                add_error(errors, "E_CONTENT_DECISION_MATCH", f"{match_id or index}与{component_id}的类目任务标注不一致")
    if non_stopped:
        for task_id in category_task_ids:
            if match_task_counts[task_id] != 1:
                add_error(errors, "E_CONTENT_DECISION_MATCH", f"{task_id}必须且只能有一条双链匹配记录")
    elif matches:
        add_error(errors, "E_CONTENT_DECISION_MATCH", "停止交付不得生成双链匹配结论")
    for component in components:
        component_id = str(component.get("component_id", ""))
        for task_id in list_value(component, "category_task_ids"):
            if task_id not in category_task_ids:
                add_error(errors, "E_CATEGORY_TASK_REF", f"{component_id}引用未知细分类目任务{task_id}")
                continue
            match_row = match_lookup.get(str(task_id), {})
            if component_id not in list_value(match_row, "component_ids"):
                add_error(errors, "E_CONTENT_DECISION_MATCH", f"{component_id}与{task_id}的双向匹配关系不完整")

    overall = chain.get("overall_diagnosis")
    root_problem_ids: set[str] = set()
    if not isinstance(overall, dict):
        add_error(errors, "E_OVERALL_DIAGNOSIS", "overall_diagnosis必须是对象")
        overall = {}
    overall_required = {
        "current_page_strategy", "current_conversion_logic",
        "current_core_purchase_reason", "strengths_to_preserve",
        "root_problems", "professional_judgement",
    }
    overall_missing = missing_fields(overall, overall_required)
    if overall_missing:
        add_error(errors, "E_OVERALL_DIAGNOSIS", f"overall_diagnosis缺少字段: {', '.join(overall_missing)}")
    if not isinstance(overall.get("strengths_to_preserve"), list):
        add_error(errors, "E_OVERALL_DIAGNOSIS", "strengths_to_preserve必须是数组")
    roots = overall.get("root_problems", [])
    if not isinstance(roots, list):
        add_error(errors, "E_OVERALL_DIAGNOSIS", "root_problems必须是数组")
        roots = []
    if len(roots) > 3:
        add_error(errors, "E_OVERALL_DIAGNOSIS", "整体根因最多3项")
    for index, root in enumerate(roots, start=1):
        if not isinstance(root, dict):
            add_error(errors, "E_OVERALL_DIAGNOSIS", f"root_problems第{index}项必须是对象")
            continue
        root_id = str(root.get("root_problem_id", ""))
        if not re.fullmatch(r"ROOT-\d{3,}", root_id) or root_id in root_problem_ids:
            add_error(errors, "E_OVERALL_DIAGNOSIS", f"root_problems第{index}项ID无效或重复")
        root_problem_ids.add(root_id)
        for field in ("title", "diagnosis", "supporting_observations", "purchase_consequence"):
            if not nonempty(root, field):
                add_error(errors, "E_OVERALL_DIAGNOSIS", f"{root_id or index}缺少{field}")
        if not isinstance(root.get("affected_decisions"), list) or not root.get("affected_decisions"):
            add_error(errors, "E_OVERALL_DIAGNOSIS", f"{root_id or index}缺少affected_decisions")
        elif any(name not in DECISION_NAMES for name in root.get("affected_decisions", [])):
            add_error(errors, "E_OVERALL_DIAGNOSIS", f"{root_id or index} affected_decisions无效")
        validate_reference_list(
            errors, root_id or f"root:{index}", root,
            "supporting_component_ids", component_ids, "E_PAGE_REF_INVALID",
        )
    if non_stopped:
        for field in (
            "current_page_strategy", "current_conversion_logic",
            "current_core_purchase_reason", "professional_judgement",
        ):
            if not nonempty(overall, field):
                add_error(errors, "E_OVERALL_DIAGNOSIS", f"非停止交付缺少{field}")

    rebuild = chain.get("rebuild_strategy")
    if not isinstance(rebuild, dict):
        add_error(errors, "E_REBUILD_STRATEGY", "rebuild_strategy必须是对象")
        rebuild = {}
    rebuild_required = {
        "strategic_objective", "proposed_purchase_logic", "narrative_route",
        "surface_roles", "preserve", "deprioritize_or_remove", "success_definition",
    }
    rebuild_missing = missing_fields(rebuild, rebuild_required)
    if rebuild_missing:
        add_error(errors, "E_REBUILD_STRATEGY", f"rebuild_strategy缺少字段: {', '.join(rebuild_missing)}")
    for field in ("narrative_route", "preserve", "deprioritize_or_remove"):
        if not isinstance(rebuild.get(field), list):
            add_error(errors, "E_REBUILD_STRATEGY", f"rebuild_strategy.{field}必须是数组")
    surface_roles = rebuild.get("surface_roles")
    required_surfaces = {"main_images", "transaction_panel", "detail_page", "decision_close"}
    if not isinstance(surface_roles, dict) or missing_fields(surface_roles, required_surfaces):
        add_error(errors, "E_REBUILD_STRATEGY", "surface_roles必须完整覆盖主图、交易区、详情页和决策收口")
    elif non_stopped and any(not nonempty(surface_roles, field) for field in required_surfaces):
        add_error(errors, "E_REBUILD_STRATEGY", "非停止交付的surface_roles不能留空")
    if non_stopped:
        for field in ("strategic_objective", "proposed_purchase_logic", "success_definition"):
            if not nonempty(rebuild, field):
                add_error(errors, "E_REBUILD_STRATEGY", f"非停止交付缺少{field}")
        if len(rebuild.get("narrative_route", [])) < 2:
            add_error(errors, "E_REBUILD_STRATEGY", "新版叙事路线至少需要2个连续节点")

    detail_plan = chain.get("detail_page_plan")
    if not isinstance(detail_plan, dict):
        add_error(errors, "E_DETAIL_PAGE_PLAN", "detail_page_plan必须是对象")
        detail_plan = {}
    detail_missing = missing_fields(detail_plan, DETAIL_PAGE_PLAN_FIELDS)
    if detail_missing:
        add_error(errors, "E_DETAIL_PAGE_PLAN", f"detail_page_plan缺少字段: {', '.join(detail_missing)}")
    detail_status = str(detail_plan.get("status", ""))
    if detail_status not in DETAIL_PAGE_PLAN_STATUSES:
        add_error(errors, "E_DETAIL_PAGE_PLAN", "detail_page_plan.status无效")
    for field in ("narrative_route", "modules", "asset_migration"):
        if not isinstance(detail_plan.get(field), list):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"detail_page_plan.{field}必须是数组")

    detail_component_ids = {
        str(row.get("component_id", ""))
        for row in components
        if row.get("scope") == "detail_page"
    }
    modules = detail_plan.get("modules", []) if isinstance(detail_plan.get("modules"), list) else []
    migrations = detail_plan.get("asset_migration", []) if isinstance(
        detail_plan.get("asset_migration"), list
    ) else []
    module_ids: set[str] = set()
    module_sequences: list[int] = []
    for index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"详情页内容章节第{index}项必须是对象")
            continue
        module_id = str(module.get("module_id", ""))
        missing = missing_fields(module, DETAIL_PAGE_MODULE_FIELDS)
        if missing:
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"DPM-\d{3,}", module_id) or module_id in module_ids:
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}章节ID无效或重复")
        module_ids.add(module_id)
        sequence = module.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}.sequence必须为正整数")
        else:
            module_sequences.append(sequence)
        for field in (
            "module_name", "user_question", "page_answer", "source_asset_summary",
            "presentation_direction", "material_needed", "acceptance_check", "boundary",
        ):
            if not nonempty(module, field):
                add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}缺少{field}")
        if not isinstance(module.get("required_content"), list) or not module.get("required_content"):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}.required_content必须是非空数组")
        linked_tasks = module.get("category_task_ids")
        if not isinstance(linked_tasks, list) or not linked_tasks:
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}.category_task_ids必须是非空数组")
        elif any(str(task_id) not in category_task_ids for task_id in linked_tasks):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}引用未知细分类目任务")
        source_components = module.get("source_component_ids")
        if not isinstance(source_components, list):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}.source_component_ids必须是数组")
        elif any(str(component_id) not in detail_component_ids for component_id in source_components):
            add_error(errors, "E_DETAIL_PAGE_PLAN", f"{module_id or index}只能引用详情页内容节点")
    if module_sequences and sorted(module_sequences) != list(range(1, len(module_sequences) + 1)):
        add_error(errors, "E_DETAIL_PAGE_PLAN", "详情页内容章节sequence必须从1连续递增")

    migrated_components: list[str] = []
    migration_ids: set[str] = set()
    for index, migration in enumerate(migrations, start=1):
        if not isinstance(migration, dict):
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"素材迁移第{index}项必须是对象")
            continue
        migration_id = str(migration.get("migration_id", ""))
        missing = missing_fields(migration, DETAIL_ASSET_MIGRATION_FIELDS)
        if missing:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"MIG-\d{3,}", migration_id) or migration_id in migration_ids:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}迁移ID无效或重复")
        migration_ids.add(migration_id)
        source_components = migration.get("source_component_ids")
        if not isinstance(source_components, list) or not source_components:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}.source_component_ids必须是非空数组")
            source_components = []
        unknown_components = [
            str(component_id) for component_id in source_components
            if str(component_id) not in detail_component_ids
        ]
        if unknown_components:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}引用非详情页内容节点")
        migrated_components.extend(str(component_id) for component_id in source_components)
        if migration.get("handling") not in DETAIL_ASSET_HANDLINGS:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}.handling无效")
        destinations = migration.get("destination_module_ids")
        if not isinstance(destinations, list):
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}.destination_module_ids必须是数组")
        elif any(str(module_id) not in module_ids for module_id in destinations):
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}引用未知新版内容章节")
        if migration.get("handling") != "删除" and not destinations:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}非删除内容必须写明新版去向")
        for field in ("current_content", "execution_note", "boundary"):
            if not nonempty(migration, field):
                add_error(errors, "E_DETAIL_ASSET_MIGRATION", f"{migration_id or index}缺少{field}")

    detail_in_scope = manifest.get("scope") in {"detail_page", "combined"}
    if manifest.get("run_status") == "stopped":
        if detail_status != "stopped":
            add_error(errors, "E_DETAIL_PAGE_PLAN", "停止交付的详情页计划状态必须为stopped")
    elif not detail_in_scope:
        if detail_status != "not_in_scope":
            add_error(errors, "E_DETAIL_PAGE_PLAN", "未包含详情页的任务必须标为not_in_scope")
    elif not detail_component_ids:
        if detail_status != "insufficient_material":
            add_error(errors, "E_DETAIL_PAGE_PLAN", "没有可读详情页内容时必须标为insufficient_material")
        if modules or migrations:
            add_error(errors, "E_DETAIL_PAGE_PLAN", "资料不足时不能生成详情页章节或素材迁移结论")
    else:
        if detail_status not in {"planned", "preserve_only"}:
            add_error(errors, "E_DETAIL_PAGE_PLAN", "有可读详情页时必须形成整体内容地图或明确只保留")
        if not modules:
            add_error(errors, "E_DETAIL_PAGE_PLAN", "有可读详情页时至少需要一个新版内容章节")
        if len(detail_plan.get("narrative_route", [])) < 2:
            add_error(errors, "E_DETAIL_PAGE_PLAN", "详情页新版讲述路线至少需要2个连续节点")
        migration_counts = Counter(migrated_components)
        if set(migration_counts) != detail_component_ids:
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", "素材迁移必须完整覆盖全部详情页内容节点")
        if any(count != 1 for count in migration_counts.values()):
            add_error(errors, "E_DETAIL_ASSET_MIGRATION", "每个现有详情页内容节点只能在迁移表登记一次")

    detail_assessment = chain.get("detail_page_assessment")
    if not isinstance(detail_assessment, dict):
        add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "detail_page_assessment必须是对象")
        detail_assessment = {}
    assessment_missing = missing_fields(detail_assessment, DETAIL_PAGE_ASSESSMENT_FIELDS)
    if assessment_missing:
        add_error(
            errors, "E_DETAIL_PAGE_ASSESSMENT",
            f"detail_page_assessment缺少字段: {', '.join(assessment_missing)}",
        )
    assessment_status = str(detail_assessment.get("status", ""))
    if assessment_status not in DETAIL_PAGE_ASSESSMENT_STATUSES:
        add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "detail_page_assessment.status无效")
    strengths = detail_assessment.get("strengths", [])
    opportunities = detail_assessment.get("improvement_opportunities", [])
    if not isinstance(strengths, list) or not isinstance(opportunities, list):
        add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "详情页优势与提升空间必须是数组")
        strengths = [] if not isinstance(strengths, list) else strengths
        opportunities = [] if not isinstance(opportunities, list) else opportunities
    assessment_ids: set[str] = set()
    for kind, items, required, id_pattern in (
        ("优势", strengths, DETAIL_PAGE_STRENGTH_FIELDS, r"DPA-S-\d{3,}"),
        ("提升空间", opportunities, DETAIL_PAGE_OPPORTUNITY_FIELDS, r"DPA-O-\d{3,}"),
    ):
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"详情页{kind}第{index}项必须是对象")
                continue
            assessment_id = str(item.get("assessment_id", ""))
            missing = missing_fields(item, required)
            if missing:
                add_error(
                    errors, "E_DETAIL_PAGE_ASSESSMENT",
                    f"{assessment_id or kind + str(index)}缺少字段: {', '.join(missing)}",
                )
            if not re.fullmatch(id_pattern, assessment_id) or assessment_id in assessment_ids:
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id or kind + str(index)} ID无效或重复")
            assessment_ids.add(assessment_id)
            linked_components = item.get("supporting_component_ids")
            if not isinstance(linked_components, list) or not linked_components:
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}必须绑定详情页内容节点")
            elif any(str(component_id) not in detail_component_ids for component_id in linked_components):
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}只能引用详情页内容节点")
            linked_tasks = item.get("category_task_ids")
            if not isinstance(linked_tasks, list) or not linked_tasks:
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}必须绑定细分类目任务")
            elif any(str(task_id) not in category_task_ids for task_id in linked_tasks):
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}引用未知细分类目任务")
            linked_decisions = item.get("decision_names")
            if not isinstance(linked_decisions, list) or not linked_decisions:
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}必须绑定买前判断")
            elif any(str(name) not in DECISION_NAMES for name in linked_decisions):
                add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}引用未知买前判断")
            for field in required - {
                "assessment_id", "supporting_component_ids", "category_task_ids", "decision_names",
            }:
                if not nonempty(item, field):
                    add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", f"{assessment_id}缺少{field}")
    if manifest.get("run_status") == "stopped":
        if assessment_status != "stopped":
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "停止交付的详情页评估必须标为stopped")
    elif not detail_in_scope:
        if assessment_status != "not_in_scope":
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "未包含详情页的评估必须标为not_in_scope")
    elif not detail_component_ids:
        if assessment_status != "insufficient_material":
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "没有可读详情页时评估必须标为insufficient_material")
        if strengths or opportunities:
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "没有可读详情页时不得推测优势或提升空间")
    else:
        if assessment_status != "assessed":
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "有可读详情页时必须完成优势与提升空间评估")
        if not strengths and not opportunities:
            add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "有可读详情页时至少需要一项有依据的评估结论")
    if not nonempty(detail_assessment, "assessment_basis") or not nonempty(detail_assessment, "boundary"):
        add_error(errors, "E_DETAIL_PAGE_ASSESSMENT", "详情页评估必须写明综合依据与边界")

    if chain.get("page_role") not in PAGE_ROLES:
        add_error(errors, "E_PAGE_ROLE", "page_role无效")
    if chain.get("page_role_basis") not in ENTRY_CONTEXT_BASES:
        add_error(errors, "E_PAGE_ROLE", "page_role_basis无效")
    if chain.get("entry_context_basis") not in ENTRY_CONTEXT_BASES:
        add_error(errors, "E_ENTRY_CONTEXT", "entry_context_basis无效")
    if manifest.get("run_status") == "ready" and chain.get("page_role") == "unknown":
        add_error(errors, "E_PAGE_ROLE", "ready状态必须确认当前页面角色")
    precompleted = chain.get("precompleted_decisions", []) if isinstance(
        chain.get("precompleted_decisions"), list
    ) else []
    remaining = chain.get("remaining_decision_tasks", []) if isinstance(
        chain.get("remaining_decision_tasks"), list
    ) else []
    if len(precompleted) != len(set(map(str, precompleted))) or any(
        item not in DECISION_NAMES for item in precompleted
    ):
        add_error(errors, "E_ENTRY_CONTEXT", "precompleted_decisions必须是无重复的五决策名称")
    if len(remaining) != len(set(map(str, remaining))) or any(
        item not in DECISION_NAMES for item in remaining
    ):
        add_error(errors, "E_ENTRY_CONTEXT", "remaining_decision_tasks必须是无重复的五决策名称")
    if set(precompleted).intersection(remaining):
        add_error(errors, "E_ENTRY_CONTEXT", "已完成决策与页面剩余任务不能重叠")
    if set(precompleted).union(remaining) != set(DECISION_NAMES):
        add_error(errors, "E_ENTRY_CONTEXT", "已完成决策与页面剩余任务必须共同覆盖五决策")
    if precompleted and chain.get("entry_context_basis") != "provided_evidence":
        add_error(errors, "E_ENTRY_CONTEXT", "没有可靠入口依据时不得声称用户进页前已完成决策")
    if manifest.get("run_status") != "stopped" and not remaining:
        add_error(errors, "E_ENTRY_CONTEXT", "非停止交付必须保留页面仍需完成的决策任务")
    if manifest.get("run_status") != "stopped" and not nonempty(chain, "dominant_route"):
        add_error(errors, "E_CHAIN_SCHEMA", "非停止交付必须写明页面主导路线")
    surface_rows = chain.get("surface_coverage", []) if isinstance(chain.get("surface_coverage"), list) else []
    seen_surfaces: set[str] = set()
    for index, row in enumerate(surface_rows, start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_CHAIN_SCHEMA", f"surface_coverage第{index}条必须是对象")
            continue
        surface = str(row.get("surface", ""))
        if surface not in SURFACES:
            add_error(errors, "E_CHAIN_SCHEMA", f"surface_coverage第{index}条surface无效")
        elif surface in seen_surfaces:
            add_error(errors, "E_CHAIN_SCHEMA", f"surface_coverage重复: {surface}")
        seen_surfaces.add(surface)
        if row.get("status") not in SURFACE_COVERAGE_STATUSES:
            add_error(errors, "E_CHAIN_SCHEMA", f"{surface or index}表面覆盖状态无效")
        validate_reference_list(errors, f"surface:{surface}", row, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        if not nonempty(row, "boundary"):
            add_error(errors, "E_CHAIN_SCHEMA", f"{surface or index}缺少覆盖边界")
    if seen_surfaces != SURFACES:
        add_error(errors, "E_CHAIN_SCHEMA", "surface_coverage必须固定登记四个页面表面")

    ordered_component_ids = list_value(chain, "ordered_component_ids")
    if len(ordered_component_ids) != len(set(map(str, ordered_component_ids))):
        add_error(errors, "E_CHAIN_SCHEMA", "ordered_component_ids存在重复")
    if set(map(str, ordered_component_ids)) != component_ids:
        add_error(errors, "E_CHAIN_SCHEMA", "ordered_component_ids必须完整覆盖当前组件")

    closure = chain.get("decision_closure")
    if not isinstance(closure, dict):
        add_error(errors, "E_CHAIN_SCHEMA", "decision_closure必须是对象")
        closure = {}
    if closure.get("status") not in DECISION_CLOSURE_STATUSES:
        add_error(errors, "E_CHAIN_SCHEMA", "decision_closure.status无效")
    closure_component = str(closure.get("closure_component_id", ""))
    if closure_component and closure_component not in component_ids:
        add_error(errors, "E_PAGE_REF_INVALID", "decision_closure引用未知组件")
    if closure.get("status") == "closed" and not closure_component:
        add_error(errors, "E_CHAIN_SCHEMA", "决策闭合必须绑定闭合组件")
    if closure.get("status") != "closed" and not isinstance(closure.get("unresolved_before_closure"), list):
        add_error(errors, "E_CHAIN_SCHEMA", "未闭合状态必须保留未解决任务数组")

    eligibility = chain.get("eligibility_gate")
    if not isinstance(eligibility, dict):
        add_error(errors, "E_CHAIN_SCHEMA", "eligibility_gate必须是对象")
        eligibility = {}
    if eligibility.get("status") not in ELIGIBILITY_STATUSES:
        add_error(errors, "E_ELIGIBILITY", "eligibility_gate.status无效")
    validate_reference_list(
        errors, "eligibility_gate", eligibility, "supporting_component_ids",
        component_ids, "E_PAGE_REF_INVALID",
    )
    if not isinstance(eligibility.get("exclusions_or_switch_conditions"), list) or not isinstance(
        eligibility.get("unresolved_questions"), list
    ):
        add_error(errors, "E_ELIGIBILITY", "适用对象闸门的边界与未知必须是数组")

    transaction = chain.get("current_transaction")
    if not isinstance(transaction, dict):
        add_error(errors, "E_CHAIN_SCHEMA", "current_transaction必须是对象")
        transaction = {}
    if transaction.get("transaction_role") not in TRANSACTION_ROLES:
        add_error(errors, "E_TRANSACTION_ROLE", "transaction_role无效")
    if transaction.get("regulated_product_type") not in REGULATED_PRODUCT_TYPES:
        add_error(errors, "E_REGULATED_IDENTITY", "regulated_product_type无效")
    if str(transaction.get("current_sku_id", "")).strip() != str(manifest.get("sku", "")).strip():
        add_error(errors, "E_IDENTITY_MIXED", "page_chain当前SKU与页面交付不一致")
    if not isinstance(transaction.get("variant_dimensions"), list):
        add_error(errors, "E_VARIANT_ROUTE", "variant_dimensions必须是数组")
    elif any(item not in VARIANT_TYPES for item in transaction.get("variant_dimensions", [])):
        add_error(errors, "E_VARIANT_ROUTE", "variant_dimensions存在无效类型")
    dimensions = transaction.get("variant_dimensions", []) if isinstance(
        transaction.get("variant_dimensions"), list
    ) else []
    selection_order = transaction.get("selection_dimension_order")
    if not isinstance(selection_order, list):
        add_error(errors, "E_SELECTION_ORDER", "selection_dimension_order必须是数组")
        selection_order = []
    elif (
        len(selection_order) != len(set(map(str, selection_order)))
        or any(item not in VARIANT_TYPES for item in selection_order)
        or not set(selection_order).issubset(set(dimensions))
    ):
        add_error(errors, "E_SELECTION_ORDER", "选择维度顺序必须无重复且属于当前变体维度")
    if manifest.get("run_status") == "ready" and len(set(dimensions)) > 1 and set(selection_order) != set(dimensions):
        add_error(errors, "E_SELECTION_ORDER", "多维度ready交付必须写清完整选择顺序")
    raw_spec_groups = transaction.get("raw_spec_groups")
    if not isinstance(raw_spec_groups, list):
        add_error(errors, "E_RAW_SPEC_GROUP", "raw_spec_groups必须是数组")
        raw_spec_groups = []
    raw_group_names: set[str] = set()
    raw_dimensions: set[str] = set()
    for index, row in enumerate(raw_spec_groups, start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条必须是对象")
            continue
        group_name = str(row.get("group_name", "")).strip()
        current_value = str(row.get("current_value", "")).strip()
        group_dimensions = row.get("normalized_dimensions")
        mixing_status = row.get("mixing_status")
        if not group_name or group_name in raw_group_names:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条名称为空或重复")
        raw_group_names.add(group_name)
        if not current_value:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条缺少当前选择值")
        if not isinstance(group_dimensions, list) or not group_dimensions:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条必须绑定至少一个规范化选择维度")
            group_dimensions = []
        elif (
            len(group_dimensions) != len(set(map(str, group_dimensions)))
            or any(item not in VARIANT_TYPES for item in group_dimensions)
            or not set(group_dimensions).issubset(set(dimensions))
        ):
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条选择维度无效或不属于当前交易")
        raw_dimensions.update(map(str, group_dimensions))
        if mixing_status not in RAW_SPEC_GROUP_STATUSES:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条mixing_status无效")
        elif mixing_status == "single_dimension" and len(group_dimensions) != 1:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条标为单维但实际不是一个维度")
        elif mixing_status == "mixed" and len(group_dimensions) < 2:
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条标为混合但没有两个以上维度")
        if not nonempty(row, "boundary"):
            add_error(errors, "E_RAW_SPEC_GROUP", f"raw_spec_groups第{index}条缺少解释边界")
    if manifest.get("run_status") == "ready" and dimensions and raw_dimensions != set(dimensions):
        add_error(errors, "E_RAW_SPEC_GROUP", "ready交付必须说明平台原始规格组如何覆盖全部用户选择维度")
    if not dimensions and raw_spec_groups:
        add_error(errors, "E_RAW_SPEC_GROUP", "没有变体维度时不应登记平台规格组")
    bundle_contents = transaction.get("bundle_contents")
    if not isinstance(bundle_contents, list):
        add_error(errors, "E_BUNDLE_CONTENTS", "bundle_contents必须是数组")
        bundle_contents = []
    for index, row in enumerate(bundle_contents, start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_BUNDLE_CONTENTS", f"bundle_contents第{index}条必须是对象")
            continue
        if row.get("role") not in BUNDLE_COMPONENT_ROLES:
            add_error(errors, "E_BUNDLE_CONTENTS", f"bundle_contents第{index}条role无效")
        if manifest.get("run_status") == "ready" and any(
            not str(row.get(field, "")).strip()
            for field in ("item_name", "variant_or_version", "quantity_or_size")
        ):
            add_error(errors, "E_BUNDLE_CONTENTS", f"bundle_contents第{index}条未锁定名称、版本或数量")
        if manifest.get("run_status") == "ready" and row.get("role") == "unknown":
            add_error(errors, "E_BUNDLE_CONTENTS", f"bundle_contents第{index}条角色未知")
    if "bundle" in dimensions and manifest.get("run_status") == "ready" and not bundle_contents:
        add_error(errors, "E_BUNDLE_CONTENTS", "套组ready交付必须锁定套组构成与实际到手")
    if "bundle" not in dimensions and bundle_contents:
        add_error(errors, "E_BUNDLE_CONTENTS", "非套组交易不应写入bundle_contents")
    if transaction.get("upgrade_comparison_status") not in UPGRADE_COMPARISON_STATUSES:
        add_error(errors, "E_UPGRADE_COMPARISON", "upgrade_comparison_status无效")
    if manifest.get("run_status") == "ready" and transaction.get("transaction_role") == "unknown":
        add_error(errors, "E_TRANSACTION_ROLE", "ready状态必须锁定当前交易角色")
    if manifest.get("run_status") == "ready" and transaction.get("regulated_product_type") == "unknown":
        add_error(errors, "E_REGULATED_IDENTITY", "ready状态必须确认商品监管身份类型")
    if (
        transaction.get("regulated_product_type") in HIGH_RISK_PRODUCT_TYPES
        and eligibility.get("status") != "resolved"
        and manifest.get("run_status") == "ready"
    ):
        add_error(errors, "E_ELIGIBILITY", "高风险品类适用对象未解决时不得ready")

    transaction_plan = chain.get("transaction_panel_plan")
    if not isinstance(transaction_plan, dict):
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "transaction_panel_plan必须是对象")
        transaction_plan = {}
    transaction_plan_missing = missing_fields(transaction_plan, TRANSACTION_PANEL_PLAN_FIELDS)
    if transaction_plan_missing:
        add_error(
            errors, "E_TRANSACTION_PANEL_PLAN",
            f"transaction_panel_plan缺少字段: {', '.join(transaction_plan_missing)}",
        )
    transaction_plan_status = str(transaction_plan.get("status", ""))
    if transaction_plan_status not in TRANSACTION_PANEL_PLAN_STATUSES:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "transaction_panel_plan.status无效")
    selection_area_mode = str(transaction_plan.get("selection_area_mode", ""))
    if selection_area_mode not in TRANSACTION_SELECTION_AREA_MODES:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "transaction_panel_plan.selection_area_mode无效")
    platform_capability_status = str(transaction_plan.get("platform_capability_status", ""))
    if platform_capability_status not in TRANSACTION_IMPLEMENTATION_STATUSES:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "transaction_panel_plan.platform_capability_status无效")
    if not nonempty(transaction_plan, "capability_summary"):
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区方案必须说明平台可实施性")
    for field in ("selection_route", "field_groups", "fixed_information", "dynamic_information"):
        if not isinstance(transaction_plan.get(field), list):
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"transaction_panel_plan.{field}必须是数组")

    field_groups = transaction_plan.get("field_groups", []) if isinstance(
        transaction_plan.get("field_groups"), list
    ) else []
    field_group_ids: set[str] = set()
    field_group_sequences: list[int] = []
    for index, group in enumerate(field_groups, start=1):
        if not isinstance(group, dict):
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"交易区选择组第{index}项必须是对象")
            continue
        group_id = str(group.get("group_id", ""))
        missing = missing_fields(group, TRANSACTION_FIELD_GROUP_FIELDS)
        if missing:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"TPG-\d{3,}", group_id) or group_id in field_group_ids:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}选择组ID无效或重复")
        field_group_ids.add(group_id)
        sequence = group.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}.sequence必须为正整数")
        else:
            field_group_sequences.append(sequence)
        for field in (
            "group_name", "user_question", "current_expression", "recommended_structure",
            "current_selection_display", "actual_receipt_and_offer", "implementation_path",
            "fallback_path", "confirmation_needed", "material_needed", "acceptance_check", "boundary",
        ):
            if not nonempty(group, field):
                add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}缺少{field}")
        if group.get("implementation_status") not in TRANSACTION_IMPLEMENTATION_STATUSES:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}.implementation_status无效")
        linked_tasks = group.get("category_task_ids")
        if not isinstance(linked_tasks, list) or not linked_tasks:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}.category_task_ids必须是非空数组")
        elif any(str(task_id) not in category_task_ids for task_id in linked_tasks):
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", f"{group_id or index}引用未知细分类目任务")
    if field_group_sequences and sorted(field_group_sequences) != list(range(1, len(field_group_sequences) + 1)):
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区选择组sequence必须从1连续递增")
    if transaction_plan_status == "planned" and selection_area_mode == "single_primary_area" and len(field_groups) != 1:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "需要调整的单选择区必须且只能有一个主要规格选择区")
    if transaction_plan_status == "preserve_only" and field_groups:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区保持现状时不得生成选择区改版卡")
    if selection_area_mode == "no_choice_needed" and field_groups:
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "无需选择时不能生成规格选择区")

    transaction_surface_status = next(
        (
            str(row.get("status", "")) for row in surface_rows
            if isinstance(row, dict) and row.get("surface") == "transaction_panel"
        ),
        "unknown",
    )
    if manifest.get("run_status") == "stopped":
        if transaction_plan_status != "stopped":
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "停止交付的交易区计划状态必须为stopped")
    elif transaction_surface_status == "not_applicable":
        if transaction_plan_status != "not_in_scope":
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区不在范围内时必须标为not_in_scope")
    elif transaction_surface_status in {"not_provided", "unknown", ""}:
        if transaction_plan_status != "insufficient_material":
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "没有可读交易区资料时必须标为insufficient_material")
        if selection_area_mode != "unknown":
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "没有可读交易区资料时selection_area_mode必须为unknown")
        if field_groups:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "资料不足时不能生成交易区选择组")
    else:
        if transaction_plan_status not in {"planned", "preserve_only"}:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "有可读交易区时必须形成选择方案或明确只保留")
        if selection_area_mode == "unknown":
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "有可读交易区时必须确认是单选择区或无需选择")
        if transaction_plan_status == "planned" and selection_area_mode == "single_primary_area" and not field_groups:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区需要调整且有规格选择时必须形成唯一主要规格选择区")
        if transaction_plan_status == "planned" and not transaction_plan.get("selection_route"):
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区改版方案必须写明用户选择顺序")
        if not transaction_plan.get("fixed_information") or not transaction_plan.get("dynamic_information"):
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区必须区分长期商品信息与发布前更新信息")
        if transaction_plan_status == "planned" and platform_capability_status not in {
            "confirmed_native", "content_workaround"
        }:
            add_error(errors, "E_TRANSACTION_PANEL_PLAN", "正式交易区改版方案只能保留已确认可实施的结构")
        for group in field_groups:
            if isinstance(group, dict) and group.get("implementation_status") not in {
                "confirmed_native", "content_workaround"
            }:
                add_error(errors, "E_TRANSACTION_PANEL_PLAN", "正式交易区选择区只能保留已确认可实施的动作")
    if not nonempty(transaction_plan, "strategy_summary") or not nonempty(transaction_plan, "boundary"):
        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区计划必须写明整体任务与执行边界")

    variant_ids: set[str] = set()
    for index, row in enumerate(chain.get("variant_routes", []), start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_VARIANT_ROUTE", f"variant_routes第{index}条必须是对象")
            continue
        variant_id = str(row.get("variant_id", ""))
        if not variant_id or variant_id in variant_ids:
            add_error(errors, "E_VARIANT_ROUTE", f"variant_routes第{index}条ID为空或重复")
        variant_ids.add(variant_id)
        if row.get("variant_type") not in VARIANT_TYPES:
            add_error(errors, "E_VARIANT_ROUTE", f"{variant_id or index} variant_type无效")
        if row.get("option_type") not in VARIANT_OPTION_TYPES:
            add_error(errors, "E_VARIANT_ROUTE", f"{variant_id or index} option_type无效")
        for field in ("sku_ids_or_unknown", "fact_ids", "value_ids", "evidence_component_ids", "usage_component_ids"):
            if not isinstance(row.get(field), list):
                add_error(errors, "E_VARIANT_ROUTE", f"{variant_id or index}.{field}必须是数组")
        validate_reference_list(errors, variant_id or str(index), row, "fact_ids", fact_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, variant_id or str(index), row, "value_ids", value_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, variant_id or str(index), row, "evidence_component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, variant_id or str(index), row, "usage_component_ids", component_ids, "E_PAGE_REF_INVALID")
    current_variant_id = str(transaction.get("current_variant_id", ""))
    if current_variant_id and current_variant_id not in variant_ids:
        add_error(errors, "E_VARIANT_ROUTE", "current_variant_id不在variant_routes中")
    for row in chain.get("variant_routes", []):
        if (
            isinstance(row, dict)
            and str(row.get("variant_id", "")) == current_variant_id
            and row.get("option_type") != "real_sku"
        ):
            add_error(errors, "E_VARIANT_ROUTE", "当前选中项必须是真实可成交SKU，不能是说明、服务或关联商品入口")

    for component in components:
        variant_id = str(component.get("variant_id", ""))
        if variant_id and variant_id != "not_applicable" and variant_id not in variant_ids:
            add_error(errors, "E_VARIANT_ROUTE", f"{component.get('component_id')}引用未知variant_id")
        if (
            component.get("component_applicability") == "selectable_variant"
            and not variant_id
        ):
            add_error(errors, "E_VARIANT_ROUTE", f"{component.get('component_id')}其他可选变体必须绑定variant_id")
        if component.get("component_applicability") == "brand_general" and component.get("claim_scope") == "current_sku":
            add_error(errors, "E_EVIDENCE_SCOPE", f"{component.get('component_id')}品牌通用信息不能证明当前SKU")
        if (
            component.get("component_applicability") == "current_bundle_component"
            and "bundle" not in dimensions
        ):
            add_error(errors, "E_BUNDLE_CONTENTS", f"{component.get('component_id')}标为套组单品但当前交易不是套组")
        if (
            component.get("component_applicability") == "entry_specific"
            and chain.get("entry_context_basis") != "provided_evidence"
            and manifest.get("run_status") == "ready"
        ):
            add_error(errors, "E_ENTRY_CONTEXT", f"{component.get('component_id')}缺少可靠入口依据却标为专属入口内容")
        if component.get("claim_level") == "market_performance" and component.get("claim_scope") in {"current_sku", "current_variant"}:
            add_error(errors, "E_EVIDENCE_SCOPE", f"{component.get('component_id')}市场表现不能写成当前SKU效果证明")

    for index, row in enumerate(chain.get("quantified_claim_checks", []), start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_QUANTIFIED_CLAIM", f"quantified_claim_checks第{index}条必须是对象")
            continue
        if row.get("claim_type") not in CLAIM_TYPES:
            add_error(errors, "E_QUANTIFIED_CLAIM", f"量化主张第{index}条claim_type无效")
        if row.get("source_readability") not in CLAIM_SOURCE_READABILITY:
            add_error(errors, "E_QUANTIFIED_CLAIM", f"量化主张第{index}条来源可读状态无效")
        if row.get("page_support_status") not in PAGE_SUPPORT_STATUSES:
            add_error(errors, "E_QUANTIFIED_CLAIM", f"量化主张第{index}条页面支持状态无效")
        for field in ("claim_text", "support_target", "metric", "boundary"):
            if not nonempty(row, field):
                add_error(errors, "E_QUANTIFIED_CLAIM", f"量化主张第{index}条缺少{field}")
        if (
            row.get("page_support_status") == "supported_on_page"
            and row.get("source_readability") != "readable"
        ):
            add_error(errors, "E_QUANTIFIED_CLAIM", f"量化主张第{index}条来源不可读却标为页面已支持")
        if (
            "%" in str(row.get("claim_text", ""))
            and str(row.get("baseline_or_denominator_or_unknown", "")).strip() in {"", "unknown"}
            and row.get("page_support_status") == "supported_on_page"
        ):
            add_error(errors, "E_QUANTIFIED_CLAIM", f"量化百分比第{index}条缺少分母或基准却标为页面已充分支持")

    cross_sku = chain.get("cross_surface_sku_consistency")
    if not isinstance(cross_sku, dict):
        add_error(errors, "E_CROSS_SURFACE_SKU", "cross_surface_sku_consistency必须是对象")
        cross_sku = {}
    if str(cross_sku.get("current_sku_id", "")).strip() != str(manifest.get("sku", "")).strip():
        add_error(errors, "E_CROSS_SURFACE_SKU", "跨表面当前SKU与页面交付不一致")
    if not isinstance(cross_sku.get("surface_checks"), list) or not isinstance(cross_sku.get("inconsistencies"), list):
        add_error(errors, "E_CROSS_SURFACE_SKU", "跨表面检查和冲突必须是数组")
    inconsistent_surface_checks = False
    for index, row in enumerate(cross_sku.get("surface_checks", []), start=1):
        if not isinstance(row, dict) or row.get("surface") not in SURFACES or row.get("relationship") not in SURFACE_RELATIONSHIPS:
            add_error(errors, "E_CROSS_SURFACE_SKU", f"surface_check第{index}条无效")
            continue
        if row.get("relationship") == "inconsistent":
            inconsistent_surface_checks = True
    has_cross_sku_problem = inconsistent_surface_checks or bool(cross_sku.get("inconsistencies", []))
    if has_cross_sku_problem and manifest.get("run_status") == "ready":
        add_error(errors, "E_CROSS_SURFACE_SKU", "当前成交单元跨表面冲突时不得ready交付")

    cross_surface = chain.get("cross_surface_consistency")
    if not isinstance(cross_surface, dict) or cross_surface.get("status") not in CROSS_SURFACE_CONSISTENCY_STATUSES:
        add_error(errors, "E_CHAIN_SCHEMA", "cross_surface_consistency.status无效")
    elif not isinstance(cross_surface.get("checked_surfaces"), list) or any(
        surface not in SURFACES for surface in cross_surface.get("checked_surfaces", [])
    ):
        add_error(errors, "E_CHAIN_SCHEMA", "cross_surface_consistency.checked_surfaces无效")
    if not isinstance(cross_surface, dict) or not isinstance(cross_surface.get("inconsistencies"), list):
        add_error(errors, "E_CHAIN_SCHEMA", "cross_surface_consistency.inconsistencies必须是数组")
    elif has_cross_sku_problem and not cross_surface.get("inconsistencies"):
        add_error(errors, "E_CROSS_SURFACE_SKU", "跨表面SKU存在冲突时不能把跨表面不一致清单留空")

    post_purchase = chain.get("post_purchase_handoff")
    if not isinstance(post_purchase, dict) or post_purchase.get("status") not in POST_PURCHASE_STATUSES:
        add_error(errors, "E_CHAIN_SCHEMA", "post_purchase_handoff.status无效")
    elif not nonempty(post_purchase, "boundary"):
        add_error(errors, "E_CHAIN_SCHEMA", "post_purchase_handoff缺少边界")

    findings = chain.get("chain_findings", []) if isinstance(chain.get("chain_findings"), list) else []
    for index, row in enumerate(findings, start=1):
        if not isinstance(row, dict):
            add_error(errors, "E_CHAIN_FINDING", f"chain_findings第{index}条必须是对象")
            continue
        if row.get("finding_type") not in CHAIN_FINDING_TYPES:
            add_error(errors, "E_CHAIN_FINDING", f"chain_findings第{index}条finding_type无效")
        validate_reference_list(errors, f"finding:{index}", row, "component_ids", component_ids, "E_PAGE_REF_INVALID")
        for field in ("observation", "problem", "boundary", "action_or_need"):
            if not nonempty(row, field):
                add_error(errors, "E_CHAIN_FINDING", f"chain_findings第{index}条缺少{field}")
    cross_sku_findings = {
        str(row.get("finding_type", ""))
        for row in findings
        if isinstance(row, dict)
    }
    if has_cross_sku_problem and not cross_sku_findings.intersection(
        {"cross_surface_sku_mismatch", "transaction_role_mismatch"}
    ):
        add_error(errors, "E_CROSS_SURFACE_SKU", "跨表面SKU或交易角色存在冲突时必须形成链级问题记录")
    if (
        transaction.get("upgrade_comparison_status") in {"not_comparable", "insufficient"}
        and not any(
            isinstance(row, dict) and row.get("finding_type") == "upgrade_comparison_missing"
            for row in findings
        )
    ):
        add_error(errors, "E_UPGRADE_COMPARISON", "升级对照不可比或资料不足时必须保留链级缺口")

    presentation_checks = chain.get("presentation_actuality_checks", []) if isinstance(
        chain.get("presentation_actuality_checks"), list
    ) else []
    for index, row in enumerate(presentation_checks, start=1):
        if not isinstance(row, dict) or row.get("relationship") not in PRESENTATION_RELATIONSHIPS:
            add_error(errors, "E_PRESENTATION_ACTUALITY", f"presentation_actuality_checks第{index}条无效")
            continue
        validate_reference_list(errors, f"presentation:{index}", row, "presentation_component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, f"presentation:{index}", row, "actual_contents_component_ids", component_ids, "E_PAGE_REF_INVALID")

    handoffs = chain.get("continuation_handoffs", []) if isinstance(chain.get("continuation_handoffs"), list) else []
    for index, row in enumerate(handoffs, start=1):
        if not isinstance(row, dict) or row.get("handoff_type") not in HANDOFF_TYPES:
            add_error(errors, "E_CHAIN_HANDOFF", f"continuation_handoffs第{index}条无效")
            continue
        start_component = str(row.get("start_component_id", ""))
        if start_component and start_component not in component_ids:
            add_error(errors, "E_PAGE_REF_INVALID", f"continuation_handoffs第{index}条引用未知组件")
        if row.get("handoff_type") not in {"none", "unknown"} and not nonempty(row, "return_action"):
            add_error(errors, "E_CHAIN_HANDOFF", f"continuation_handoffs第{index}条缺少返回动作")

    if manifest.get("run_status") == "stopped":
        if decisions:
            warnings.append("stopped状态仍保留了判断行；应确保都明确为资料不足")
    else:
        if len(decisions) != len(DECISION_NAMES):
            add_error(errors, "E_DECISION_INCOMPLETE", "非停止交付必须固定完成五个用户判断")
        decision_names = [str(row.get("decision_name", "")) for row in decisions]
        if set(decision_names) != set(DECISION_NAMES) or len(set(decision_names)) != len(DECISION_NAMES):
            add_error(errors, "E_DECISION_INCOMPLETE", "五个用户判断缺失、重复或名称错误")
    for index, row in enumerate(decisions, start=1):
        decision_id = str(row.get("decision_id", ""))
        missing = missing_fields(row, DECISION_FIELDS)
        if missing:
            add_error(errors, "E_DECISION_INCOMPLETE", f"decision第{index}条缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"DEC-0[1-5]", decision_id):
            add_error(errors, "E_DECISION_INCOMPLETE", f"{decision_id or index} ID格式无效")
        if row.get("decision_name") not in DECISION_NAMES:
            add_error(errors, "E_DECISION_INCOMPLETE", f"{decision_id} decision_name无效")
        if row.get("status") not in DECISION_STATUSES:
            add_error(errors, "E_DECISION_INCOMPLETE", f"{decision_id} status无效")
        for field in (
            "summary", "explained", "not_explained", "purchase_impact",
            "recommended_fix", "boundary",
        ):
            if not nonempty(row, field):
                add_error(errors, "E_DECISION_INCOMPLETE", f"{decision_id}缺少{field}")
        if row.get("status") in {"部分讲清", "未讲清", "资料不足"} and str(
            row.get("not_explained", "")
        ).strip() in {"部分讲清", "未讲清", "资料不足", "当前资料不足", "尚未讲清"}:
            add_error(errors, "E_DECISION_GAP_UNCLEAR", f"{decision_id}必须具体写明还没讲清什么")
        generic_decision_text = " ".join(
            str(row.get(field, "")) for field in (
                "explained", "not_explained", "purchase_impact", "recommended_fix"
            )
        )
        if re.search(
            r"页面已有可读内容承接|相关商品信息可以被找到|尚未把[‘'\"]?.+?[’'\"]?放进一条连续购买逻辑|"
            r"用户完成[‘'\"]?.+?[’'\"]?需要自行跨页面拼接信息|把[‘'\"]?.+?[’'\"]?所需信息放在用户做决定之前",
            generic_decision_text,
        ):
            add_error(
                errors,
                "E_DECISION_GENERIC",
                f"{decision_id}仍是通用空话，必须写出本商品的具体事实、缺口、购买影响和补法",
            )
        if not isinstance(row.get("unknowns"), list):
            add_error(errors, "E_UNKNOWN_DROPPED", f"{decision_id}.unknowns必须是数组")
        validate_reference_list(errors, decision_id, row, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, decision_id, row, "component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, decision_id, row, "fact_ids", fact_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, decision_id, row, "value_ids", value_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, decision_id, row, "vis_ids", vis_ids, "E_UPSTREAM_REF_MISSING")
        if row.get("status") != "资料不足" and (
            not list_value(row, "source_file_ids") or not list_value(row, "component_ids")
        ):
            add_error(errors, "E_DECISION_UNGROUNDED", f"{decision_id}必须绑定页面来源和组件")
        if row.get("status") == "资料不足" and not list_value(row, "unknowns"):
            add_error(errors, "E_UNKNOWN_DROPPED", f"{decision_id}标为资料不足时必须写明未知")
        component_lookup_for_decision = {
            str(item.get("component_id", "")): item for item in components
        }
        for component_id in list_value(row, "component_ids"):
            component = component_lookup_for_decision.get(str(component_id), {})
            if component and row.get("decision_name") not in list_value(component, "decision_names"):
                add_error(errors, "E_DECISION_UNGROUNDED", f"{decision_id}引用的{component_id}不承担该用户判断")
        decision_text = record_text(row)
        if contains_effect_promise(decision_text):
            add_error(errors, "E_EFFECT_PROMISE", f"{decision_id}包含未经验证的效果承诺")
        if any(pattern.search(decision_text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", f"{decision_id}试图重选或替换核心价值")
        if any(pattern.search(decision_text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{decision_id}把评论或评价升级为事实")

    decision_status_lookup = {
        str(row.get("decision_name", "")): str(row.get("status", ""))
        for row in decisions
    }

    if len(actions) > 5:
        add_error(errors, "E_ACTION_LIMIT", "优先动作总数不能超过5")
    if manifest.get("run_status") == "stopped" and actions:
        add_error(errors, "E_FORCED_ACTION", "stopped状态的优先动作必须为0")
    priorities = [item.get("priority") for item in actions]
    if any(not isinstance(priority, int) for priority in priorities):
        add_error(errors, "E_ACTION_FIELDS_MISSING", "动作priority必须是整数")
    elif priorities and sorted(priorities) != list(range(1, len(actions) + 1)):
        add_error(errors, "E_ACTION_FIELDS_MISSING", "动作priority必须从1连续排列且不重复")
    normalized_actions: list[str] = []
    for index, row in enumerate(actions, start=1):
        action_id = str(row.get("action_id", ""))
        missing = missing_fields(row, ACTION_FIELDS)
        if missing:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"action第{index}条缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"ACT-\d{3,}", action_id):
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id or index} ID格式无效")
        if row.get("scope") not in ACTION_SCOPES:
            add_error(errors, "E_MODE_SCOPE", f"{action_id} scope无效")
        if manifest.get("scope") in COMPONENT_SCOPES and row.get("scope") != manifest.get("scope"):
            add_error(errors, "E_MODE_SCOPE", f"{action_id}越过本次页面范围")
        if manifest.get("scope") != "combined" and row.get("scope") == "cross_surface":
            add_error(errors, "E_MODE_SCOPE", f"{action_id}单页面模式不能使用cross_surface")
        if row.get("decision_name") not in DECISION_NAMES:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id} decision_name无效")
        if row.get("basis_type") not in BASIS_TYPES:
            add_error(errors, "E_ACTION_UNGROUNDED", f"{action_id} basis_type无效")
        if row.get("action_type") not in ACTION_TYPES:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id} action_type无效")
        if row.get("recommendation_label") not in RECOMMENDATION_LABELS:
            add_error(
                errors,
                "E_ACTION_LABEL",
                f"{action_id} recommendation_label必须是{sorted(RECOMMENDATION_LABELS)}之一",
            )
        if not nonempty(row, "project_name") or not nonempty(row, "strategic_goal"):
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id}必须写明改版项目名称和整体目标")
        linked_category_tasks = row.get("category_task_ids")
        if not isinstance(linked_category_tasks, list):
            add_error(errors, "E_CATEGORY_TASK_REF", f"{action_id}.category_task_ids必须是数组")
            linked_category_tasks = []
        unknown_category_tasks = [
            task_id for task_id in linked_category_tasks if task_id not in category_task_ids
        ]
        if unknown_category_tasks:
            add_error(errors, "E_CATEGORY_TASK_REF", f"{action_id}引用未知细分类目任务: {unknown_category_tasks}")
        if not linked_category_tasks:
            add_error(errors, "E_CATEGORY_TASK_REF", f"{action_id}必须绑定至少一个细分类目购买任务")
        if row.get("action_type") != "保留" and not any(
            task_id in unresolved_category_task_ids for task_id in linked_category_tasks
        ):
            add_error(errors, "E_ACTION_NOT_CATEGORY_GAP", f"{action_id}没有解决任何真实双链断点")
        linked_roots = row.get("root_problem_ids")
        if not isinstance(linked_roots, list):
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id}.root_problem_ids必须是数组")
            linked_roots = []
        unknown_roots = [root_id for root_id in linked_roots if root_id not in root_problem_ids]
        if unknown_roots:
            add_error(errors, "E_ACTION_NOT_ROOTED", f"{action_id}引用未知整体根因: {unknown_roots}")
        if row.get("action_type") != "保留" and not linked_roots:
            add_error(errors, "E_ACTION_NOT_ROOTED", f"{action_id}必须先绑定整体根因，不能从单张图直接生成")
        if row.get("action_type") != "保留" and decision_status_lookup.get(
            str(row.get("decision_name", ""))
        ) == "已讲清":
            add_error(errors, "E_ACTION_NOT_GAP_TARGETED", f"{action_id}不能重复优化已经讲清的购买判断")
        if row.get("status") not in ACTION_STATUSES:
            add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id} status无效")
        elif row.get("status") not in ACTIVE_ACTION_STATUSES:
            add_error(errors, "E_BLOCKED_ACTION", f"{action_id}处于blocked或stale，不得进入优先动作")
        for field in (
            "page_location", "current_observation", "gap_or_risk", "basis_summary",
            "action_detail", "must_preserve", "material_needed", "human_confirmation",
            "acceptance_check", "validation_question", "boundary",
        ):
            if not nonempty(row, field):
                add_error(errors, "E_ACTION_FIELDS_MISSING", f"{action_id}缺少{field}")
        validate_reference_list(errors, action_id, row, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, action_id, row, "component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, action_id, row, "fact_ids", fact_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, action_id, row, "value_ids", value_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, action_id, row, "vis_ids", vis_ids, "E_UPSTREAM_REF_MISSING")
        if "supporting_source_ids" in row:
            validate_reference_list(
                errors, action_id, row, "supporting_source_ids", supporting_source_ids, "E_SUPPORT_SOURCE"
            )
        if "claim_ids" in row:
            validate_reference_list(errors, action_id, row, "claim_ids", claim_ids, "E_CLAIM_UNGROUNDED")
        if not list_value(row, "source_file_ids") or not list_value(row, "component_ids"):
            add_error(errors, "E_ACTION_UNGROUNDED", f"{action_id}必须绑定页面来源与组件观察")
        referenced_components = [
            next(
                (item for item in components if str(item.get("component_id", "")) == str(component_id)),
                {},
            )
            for component_id in list_value(row, "component_ids")
        ]
        if referenced_components and not any(
            row.get("decision_name") in list_value(component, "decision_names")
            for component in referenced_components
        ):
            add_error(errors, "E_ACTION_UNGROUNDED", f"{action_id}引用的组件不承担{row.get('decision_name')}判断")
        if any(
            component.get("component_applicability") in {
                "selectable_variant", "related_product", "brand_general", "unknown"
            }
            for component in referenced_components
        ) and row.get("action_type") != "人工核实":
            add_error(errors, "E_SKU_APPLICABILITY", f"{action_id}引用其他SKU或适用性未知内容时只能先人工核实")
        if any(
            component.get("content_layer") == "current_campaign"
            and component.get("dynamic_status") in {"expired", "unknown"}
            for component in referenced_components
        ) and row.get("action_type") != "人工核实":
            add_error(errors, "E_DYNAMIC_TIME_SCOPE", f"{action_id}引用失效或时点未知活动时只能先人工核实")
        if row.get("scope") in COMPONENT_SCOPES:
            for source_id in list_value(row, "source_file_ids"):
                source = source_lookup.get(str(source_id), {})
                if source and source.get("page_scope") != row.get("scope"):
                    add_error(errors, "E_SCOPE_REFERENCE", f"{action_id}引用了不同页面范围的{source_id}")
            for component in referenced_components:
                if component and component.get("scope") != row.get("scope"):
                    add_error(errors, "E_SCOPE_REFERENCE", f"{action_id}引用了不同页面范围的组件")
        elif row.get("scope") == "cross_surface":
            source_scopes = {
                source_lookup.get(str(source_id), {}).get("page_scope")
                for source_id in list_value(row, "source_file_ids")
            }
            component_scopes = {component.get("scope") for component in referenced_components if component}
            if not COMPONENT_SCOPES <= source_scopes or not COMPONENT_SCOPES <= component_scopes:
                add_error(errors, "E_SCOPE_REFERENCE", f"{action_id}跨触点动作必须同时绑定主图与详情页证据")
        if manifest.get("run_status") == "degraded_no_product_value":
            allowed_basis = {"page_visible_only"}
            if manifest.get("analysis_mode") == "enhance_with_evidence":
                allowed_basis |= {"supplemental_evidence", "page_and_supplemental"}
            if row.get("basis_type") not in allowed_basis:
                add_error(errors, "E_P0_CREATED", f"{action_id}当前模式使用了不允许的依据类型")
            if list_value(row, "fact_ids") or list_value(row, "value_ids") or list_value(row, "vis_ids"):
                add_error(errors, "E_P0_CREATED", f"{action_id}降级模式不得调用上游价值或VIS")
            if row.get("basis_type") in {"supplemental_evidence", "page_and_supplemental"}:
                if not list_value(row, "claim_ids"):
                    add_error(errors, "E_CLAIM_UNGROUNDED", f"{action_id}补充资料动作缺少claim_ids")
                elif any(str(item) not in usable_claim_ids for item in list_value(row, "claim_ids")):
                    add_error(errors, "E_CLAIM_OVERREACH", f"{action_id}引用了不可直接调用的补充主张")
        elif manifest.get("run_status") != "stopped":
            usable_claim_refs = [
                str(item) for item in list_value(row, "claim_ids")
                if str(item) in usable_claim_ids
            ]
            if row.get("basis_type") == "page_visible_only" and not usable_claim_refs:
                add_error(errors, "E_UPSTREAM_REF_MISSING", f"{action_id}正式增强动作必须调用有效上游或补充事实")
            if not (
                list_value(row, "fact_ids")
                or list_value(row, "value_ids")
                or list_value(row, "vis_ids")
                or usable_claim_refs
            ):
                add_error(errors, "E_UPSTREAM_REF_MISSING", f"{action_id}缺少有效上游或补充事实引用")
            if list_value(row, "claim_ids") and len(usable_claim_refs) != len(list_value(row, "claim_ids")):
                add_error(errors, "E_CLAIM_OVERREACH", f"{action_id}引用了不可直接调用的补充主张")
            if any(
                str(claim_lookup.get(claim_id, {}).get("applicable_sku", "")).strip()
                != str(manifest.get("sku", "")).strip()
                for claim_id in usable_claim_refs
            ):
                add_error(errors, "E_SKU_APPLICABILITY", f"{action_id}引用的补充事实不适用于当前SKU")
            if list_value(row, "vis_ids") and not value_expression_usable:
                add_error(errors, "E_UPSTREAM_REF_MISSING", f"{action_id}调用了不可用VIS")
        action_text = " ".join(str(row.get(field, "")) for field in (
            "current_observation", "gap_or_risk", "basis_summary", "action_detail",
            "must_preserve", "acceptance_check", "validation_question", "boundary",
        ))
        if contains_effect_promise(action_text):
            add_error(errors, "E_EFFECT_PROMISE", f"{action_id}包含未经验证的效果承诺")
        if any(pattern.search(action_text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", f"{action_id}试图重选或替换核心价值")
        if any(pattern.search(action_text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{action_id}把评论或评价升级为事实")
        validate_upstream_boundary(
            errors,
            action_id,
            "\n".join(
                str(row.get(field, ""))
                for field in (
                    "action_detail", "must_preserve", "acceptance_check",
                    "validation_question", "boundary",
                )
            ),
            row.get("action_type"),
            restricted_topics,
        )
        normalized_actions.append(
            re.sub(r"\s+", "", f"{row.get('page_location', '')}|{row.get('action_type', '')}|{row.get('action_detail', '')}")
        )
    duplicates = [value for value, count in Counter(normalized_actions).items() if value and count > 1]
    if duplicates:
        add_error(errors, "E_ACTION_PADDING", "存在重复动作或为凑数拆分的同一动作")
    action_duplicates = duplicate_ids(actions, "action_id")
    if action_duplicates:
        add_error(errors, "E_ACTION_FIELDS_MISSING", f"动作ID重复: {', '.join(action_duplicates)}")

    if len(validations) > 3:
        add_error(errors, "E_VALIDATION_LIMIT", "验证任务最多3项")
    if manifest.get("delivery_mode") == "course" and validations:
        add_error(errors, "E_COURSE_DATA_BURDEN", "课程模式不建立专业版数据验证任务")
    if manifest.get("task") == "version_review":
        if not {"current", "comparison"} <= versions:
            add_error(errors, "E_VERSION_INPUT", "version_review缺少current或comparison真实页面版本")
        if not validations:
            add_error(errors, "E_VERSION_INPUT", "version_review至少需要一个有边界的验证任务")
    for index, row in enumerate(validations, start=1):
        test_id = str(row.get("test_id", ""))
        missing = missing_fields(row, VALIDATION_FIELDS)
        if missing:
            add_error(errors, "E_VALIDATION_FIELDS", f"validation第{index}条缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"TEST-\d{3,}", test_id):
            add_error(errors, "E_VALIDATION_FIELDS", f"{test_id or index} ID格式无效")
        if row.get("scope") not in ACTION_SCOPES:
            add_error(errors, "E_MODE_SCOPE", f"{test_id} scope无效")
        elif manifest.get("scope") in COMPONENT_SCOPES and row.get("scope") != manifest.get("scope"):
            add_error(errors, "E_MODE_SCOPE", f"{test_id}越过本次页面范围")
        for field in ("version_a", "version_b", "must_keep", "single_variable", "observation_needed", "comparability", "status", "boundary"):
            if not nonempty(row, field):
                add_error(errors, "E_VALIDATION_FIELDS", f"{test_id}缺少{field}")
        if row.get("version_a") == row.get("version_b"):
            add_error(errors, "E_VERSION_INPUT", f"{test_id}不能比较同一版本")
        if manifest.get("task") == "version_review" and {
            str(row.get("version_a", "")), str(row.get("version_b", ""))
        } != {"current", "comparison"}:
            add_error(errors, "E_VERSION_BINDING", f"{test_id}必须绑定真实的current与comparison来源")
        if row.get("status") not in ACTIVE_ACTION_STATUSES:
            add_error(errors, "E_VALIDATION_FIELDS", f"{test_id} status必须是待验证建议或候选")
        text = " ".join(str(row.get(field, "")) for field in VALIDATION_FIELDS)
        if contains_effect_promise(text):
            add_error(errors, "E_EFFECT_PROMISE", f"{test_id}包含效果承诺")
        if any(pattern.search(text) for pattern in VERSION_WIN_PATTERNS):
            add_error(errors, "E_VERSION_COMPARABILITY", f"{test_id}在无受控归因下判定版本胜负或因果")

    for index, row in enumerate(gaps, start=1):
        gap_id = str(row.get("gap_id", ""))
        missing = missing_fields(row, GAP_FIELDS)
        if missing:
            add_error(errors, "E_UNKNOWN_DROPPED", f"gap第{index}条缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"GAP-\d{3,}", gap_id):
            add_error(errors, "E_UNKNOWN_DROPPED", f"{gap_id or index} ID格式无效")
        if row.get("return_to") not in GAP_RETURN_TARGETS:
            add_error(errors, "E_UNKNOWN_DROPPED", f"{gap_id} return_to无效")
        for field in ("category", "missing", "impact", "minimum_needed", "priority", "state"):
            if not nonempty(row, field):
                add_error(errors, "E_UNKNOWN_DROPPED", f"{gap_id}缺少{field}")
        validate_reference_list(errors, gap_id, row, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        gap_text = record_text(row)
        if contains_effect_promise(gap_text):
            add_error(errors, "E_EFFECT_PROMISE", f"{gap_id}包含未经验证的效果承诺")
        if any(pattern.search(gap_text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", f"{gap_id}试图重选或替换核心价值")
        if any(pattern.search(gap_text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{gap_id}把评论或评价升级为事实")
    if manifest.get("run_status") in {"degraded_no_product_value", "stopped"} and not gaps:
        add_error(errors, "E_UNKNOWN_DROPPED", "降级或停止状态必须保留资料缺口")

    if routing is not None:
        missing = missing_fields(routing, ROUTE_FIELDS)
        if missing:
            add_error(errors, "E_ROUTE_FIELDS_MISSING", f"routing_decision缺少字段: {', '.join(missing)}")
        if not re.fullmatch(r"ROUTE-\d{3,}", str(routing.get("routing_decision_id", ""))):
            add_error(errors, "E_ROUTE_DECISION_INVALID", "routing_decision_id格式无效")
        if routing.get("recommended_route") not in ROUTE_OPTIONS:
            add_error(errors, "E_ROUTE_DECISION_INVALID", "recommended_route不在允许范围")
        if routing.get("status") not in ROUTE_STATUSES:
            add_error(errors, "E_ROUTE_DECISION_INVALID", "route状态不在允许范围")
        elif routing.get("status") != "suggested_untested":
            add_error(errors, "E_BLOCKED_ACTION", "blocked或stale路由不得进入正式报告")
        if str(routing.get("entry_context", "")).strip() != str(manifest.get("entry_context", "")).strip():
            add_error(errors, "E_ROUTE_CONTEXT_MISMATCH", "路由判断的入口语境与manifest不一致")
        for field in ("decision_summary", "boundary"):
            if not nonempty(routing, field):
                add_error(errors, "E_ROUTE_FIELDS_MISSING", f"routing_decision缺少{field}")
        for field in (
            "shared_invariants", "change_scope", "activation_conditions", "source_file_ids",
            "component_ids", "fact_ids", "value_ids", "vis_ids", "human_confirmation",
        ):
            if not isinstance(routing.get(field), list):
                add_error(errors, "E_ROUTE_FIELDS_MISSING", f"routing_decision.{field}必须是数组")
        if not list_value(routing, "shared_invariants") or not list_value(routing, "change_scope"):
            add_error(errors, "E_ROUTE_FIELDS_MISSING", "路由判断必须写清共用不变量与允许变化范围")
        validate_reference_list(errors, "ROUTE-001", routing, "source_file_ids", source_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, "ROUTE-001", routing, "component_ids", component_ids, "E_PAGE_REF_INVALID")
        validate_reference_list(errors, "ROUTE-001", routing, "fact_ids", fact_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, "ROUTE-001", routing, "value_ids", value_ids, "E_UPSTREAM_REF_MISSING")
        validate_reference_list(errors, "ROUTE-001", routing, "vis_ids", vis_ids, "E_UPSTREAM_REF_MISSING")
        if not list_value(routing, "source_file_ids") or not list_value(routing, "component_ids"):
            add_error(errors, "E_ROUTE_UNGROUNDED", "路由判断必须绑定可读页面来源和组件")
        if not (list_value(routing, "fact_ids") or list_value(routing, "value_ids")):
            add_error(errors, "E_ROUTE_UNGROUNDED", "路由判断必须绑定当前商品事实或价值")
        if list_value(routing, "vis_ids") and not value_expression_usable:
            add_error(errors, "E_UPSTREAM_REF_MISSING", "路由判断调用了不可用VIS")
        gate = routing.get("standalone_gate")
        if not isinstance(gate, dict) or set(gate) != ROUTE_GATE_FIELDS:
            add_error(errors, "E_ROUTE_FIELDS_MISSING", "standalone_gate必须完整包含四项闸门")
            gate = {}
        elif any(value not in ROUTE_GATE_STATUSES for value in gate.values()):
            add_error(errors, "E_ROUTE_DECISION_INVALID", "standalone_gate状态无效")
        route = routing.get("recommended_route")
        if route == "entry_adaptation" and (
            gate.get("entry_difference") != "supported"
            or not list_value(routing, "activation_conditions")
        ):
            add_error(errors, "E_ROUTE_DYNAMIC_CONDITION", "入口适配必须有已支持的入口差异和启用条件")
        if route == "dynamic_sku_adaptation" and (
            not list_value(routing, "activation_conditions")
            or not list_value(routing, "human_confirmation")
        ):
            add_error(errors, "E_ROUTE_DYNAMIC_CONDITION", "动态或SKU适配必须写明启用条件和人工确认")
        if route == "standalone_page" and gate and set(gate.values()) != {"supported"}:
            add_error(errors, "E_ROUTE_STANDALONE_GATE", "独立精细页必须同时通过四项闸门")
        route_text = record_text(routing)
        if contains_effect_promise(route_text):
            add_error(errors, "E_EFFECT_PROMISE", "路由判断包含未经验证的效果承诺")
        if any(pattern.search(route_text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", "路由判断试图重选或替换核心价值")
        if any(pattern.search(route_text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", "路由判断把评论或评价升级为事实")

    chain_text = record_text(chain)
    if contains_effect_promise(chain_text):
        add_error(errors, "E_EFFECT_PROMISE", "page_chain包含未经验证的效果承诺")
    if any(pattern.search(chain_text) for pattern in P0_MUTATION_PATTERNS):
        add_error(errors, "E_P0_MUTATED", "page_chain试图重选或替换核心价值")
    if any(pattern.search(chain_text) for pattern in COMMENT_FACT_PATTERNS):
        add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", "page_chain把评论或评价升级为事实")

    manifest_text = record_text(manifest)
    if contains_effect_promise(manifest_text):
        add_error(errors, "E_EFFECT_PROMISE", "page_manifest包含未经验证的效果承诺")
    if any(pattern.search(manifest_text) for pattern in P0_MUTATION_PATTERNS):
        add_error(errors, "E_P0_MUTATED", "page_manifest试图重选或替换核心价值")
    if any(pattern.search(manifest_text) for pattern in COMMENT_FACT_PATTERNS):
        add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", "page_manifest把评论或评价升级为事实")

    gap_source_ids = {
        str(source_id)
        for gap in gaps
        if gap.get("state") != "closed"
        for source_id in list_value(gap, "source_file_ids")
    }
    for row in sources:
        if row.get("readability_status") in {
            "not_reviewed", "partially_readable", "unreadable", "unsupported_archive"
        } and not row.get("quality_excluded") and row.get("source_file_id") not in gap_source_ids:
            add_error(
                errors,
                "E_UNKNOWN_DROPPED",
                f"{row.get('source_file_id')}的不可读、部分可读或未复核状态没有进入缺口",
            )

    referenced_source_ids = {
        str(source_id)
        for row in [*components, *actions]
        for source_id in list_value(row, "source_file_ids")
    }
    if routing is not None:
        referenced_source_ids.update(map(str, list_value(routing, "source_file_ids")))
    source_lookup = {str(row.get("source_file_id", "")): row for row in sources}
    for source_id in referenced_source_ids:
        source = source_lookup.get(source_id, {})
        if source.get("readability_status") not in {"readable", "partially_readable"}:
            add_error(errors, "E_PAGE_REF_INVALID", f"{source_id}不可读却被组件或动作引用")
        if source.get("page_location") in {"", "unknown", None}:
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id}缺少真实页面位置")
        if source.get("sequence_status") == "unverified":
            add_error(errors, "E_PAGE_REF_MISSING", f"{source_id}顺序未确认却被正式引用")

    report_paths = required_report_paths(delivery, str(manifest.get("delivery_mode", "")))
    for path in report_paths:
        if not path.is_file():
            add_error(errors, "E_FILE_MISSING", f"缺少普通版报告: {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            add_error(errors, "E_FILE_MISSING", f"{path.name}为空")
        if PLACEHOLDER_PATTERN.search(text):
            add_error(errors, "E_REPORT_PLACEHOLDER", f"{path.name}仍有模板占位内容")
        if REPORT_ID_PATTERN.search(text):
            add_error(errors, "E_COURSE_INTERNAL_LEAK", f"{path.name}暴露内部资产ID")
        if ABSOLUTE_PATH_PATTERN.search(REMOTE_URL_PATTERN.sub("", text)):
            add_error(errors, "E_ABSOLUTE_PATH_LEAK", f"{path.name}暴露本地绝对路径")
        if contains_effect_promise(text):
            add_error(errors, "E_EFFECT_PROMISE", f"{path.name}包含未经验证的效果承诺")
        if any(pattern.search(text) for pattern in P0_MUTATION_PATTERNS):
            add_error(errors, "E_P0_MUTATED", f"{path.name}试图重选或替换核心价值")
        if any(pattern.search(text) for pattern in COMMENT_FACT_PATTERNS):
            add_error(errors, "E_COMMENT_AS_PRODUCT_FACT", f"{path.name}把评论或评价升级为事实")
        if "by 布兰德老白 BrandBAI" not in text:
            add_error(errors, "E_BRAND_NOTICE", f"{path.name}缺少固定方法署名")
        if re.search(r"最终主图|可直接上线详情页|已完成发布稿", text):
            add_error(errors, "E_FINAL_ARTWORK_CLAIM", f"{path.name}越界声称完成最终视觉稿")
        if re.search(r"下载时选中|下载选错|误选项", text):
            add_error(errors, "E_COLLECTION_PROCESS_LEAK", f"{path.name}混入下载过程信息")
        if re.search(r"(?:明天|下周|首周|本月)(?:先|再|启动|开始|完成|推进|处理|执行|上线|验证)", text):
            add_error(errors, "E_EXPIRES_WITH_TIME", f"{path.name}包含脱离明确排期就会过期的时间词")
        if re.search(r"这类商品，?用户通常(?:依次)?确认", text):
            add_error(errors, "E_USER_CONSENSUS_OVERSTATED", f"{path.name}把诊断顺序写成用户普遍共识")
        if re.search(r"本次先按这条购买顺序检查|买前需要依次想清楚|最大购买断点|完整判断依据|页面当前内容顺序|商品价值底座|已验证卖点资产", text):
            add_error(errors, "E_REPORT_INTERNAL_TONE", f"{path.name}仍含内部检查口吻")
    if manifest.get("delivery_mode") == "course" and paths["course_report"].is_file():
        course = paths["course_report"].read_text(encoding="utf-8")
        for heading in (
            "## 一、品牌先看这一页",
            "## 二、这次看了什么",
            "### 页面整体诊断",
            "### 用户买前要弄清楚什么",
            "### 整体重构思路",
            "## 三、五个买前问题还有哪些没讲清",
            "## 四、这一轮的改版项目",
            "## 五、还需要补什么资料",
            "## 六、建议先做",
            "## 七、限制说明",
        ):
            if heading not in course:
                add_error(errors, "E_COURSE_ACTION_CARD_MISSING", f"课程行动单缺少章节: {heading}")
        if course.count("| ") > 0 and len(actions) > 5:
            add_error(errors, "E_ACTION_LIMIT", "课程行动单动作超过5项")
    if manifest.get("delivery_mode") == "professional":
        for name, headings in (
            (
                "professional_report_01",
                (
                    "## 先看结论", "### 现有页面中建议继续保留",
                    "## 1｜哪些信息还需要讲清",
                    "## 2｜改版后怎么讲", "## 3｜本轮改版项目",
                    "## 4｜五个买前问题（需要时再看）",
                    "## 5｜本次分析范围", "## 6｜还需补什么与下一步",
                    "## 7｜使用边界", "### 补充资料与证明范围", "### 长期边界",
                ),
            ),
            (
                "professional_report_02",
                ("## 先看这次怎么改", "## 改版项目先做什么", "## 1｜主图怎么改", "## 2｜交易区是否需要调整", "## 3｜详情页整体怎么改", "### 现有详情内容在新版中的安排", "## 4｜上线后怎么判断是否有效"),
            ),
        ):
            if not paths[name].is_file():
                continue
            text = paths[name].read_text(encoding="utf-8")
            for heading in headings:
                if heading not in text:
                    add_error(errors, "E_PRO_TRACE_MISSING", f"{paths[name].name}缺少章节: {heading}")
            if name == "professional_report_01":
                if "**用户下单前，需要依次确认：**" not in text:
                    add_error(errors, "E_PRO_ROUTE_MISSING", "专业报告必须用用户主语说明下单前需要确认的问题")
                if "**页面现在的讲述顺序：**" not in text or "**建议的新购买顺序：**" not in text:
                    add_error(errors, "E_PRO_ROUTE_MISSING", "专业报告必须分开呈现页面当前顺序与改版后建议顺序")
                if re.search(r"(?:承接较弱|存在冲突|暂时无法判断)(?:；[^|\n]+){2,}", text):
                    add_error(errors, "E_PRO_AUDIT_JARGON", "专业报告并排暴露过多内部审计状态")
                if "已经做对" in text or "做错" in text:
                    add_error(errors, "E_PRO_AUDIT_JARGON", "专业报告不得用对错身份评价页面")
            if name == "professional_report_02" and detail_plan.get("status") in {"planned", "preserve_only"}:
                if "| 新版内容章节 |" not in text or "| 现有内容 | 新版怎么安排 | 放到新版哪里 |" not in text:
                    add_error(errors, "E_DETAIL_PAGE_PLAN", "详情页执行方案必须呈现内容地图和素材迁移表")
            if name == "professional_report_02" and transaction_plan.get("status") in {"planned", "preserve_only"}:
                if transaction_plan.get("status") == "planned" and transaction_plan.get("selection_area_mode") == "single_primary_area":
                    if "### 一个主要规格选择区｜" not in text or "- **同一组选项怎么写：**" not in text or "- **完成标准：**" not in text:
                        add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区执行方案必须呈现一个可落地的主要规格选择区")
                if transaction_plan.get("status") == "preserve_only" and "### 本轮保持现状" not in text:
                    add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区保持现状时必须说明保留理由")
                if "### 长期商品信息与当前优惠分开呈现" not in text:
                    add_error(errors, "E_TRANSACTION_PANEL_PLAN", "交易区执行方案必须区分长期商品信息与当前优惠")
            if name in {"professional_report_01", "professional_report_02"} and "已经做对" in text:
                add_error(errors, "E_PRO_AUDIT_JARGON", "品牌报告不得用已经做对评价页面")
        legacy_boundary_report = delivery / "03_资料缺口与证据边界.md"
        if legacy_boundary_report.exists():
            add_error(errors, "E_LEGACY_REPORT", "专业交付应只保留两份正式文档；资料缺口与证明边界必须合并进第一份报告")
        if manifest.get("task") == "route" and paths["professional_report_01"].is_file():
            text = paths["professional_report_01"].read_text(encoding="utf-8")
            if "## 页面共用与分版建议" not in text:
                add_error(errors, "E_PRO_TRACE_MISSING", "专业报告缺少页面共用与分版建议")

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "run_status": manifest.get("run_status"),
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
