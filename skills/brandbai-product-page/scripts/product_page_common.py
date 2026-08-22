"""Shared helpers and schema constants for BrandBAI Product Page."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "0.3.0"
SKILL_VERSION = "0.3.1"

SCOPES = {"main_images", "detail_page", "combined"}
TASKS = {"diagnose", "design", "route", "version_review"}
DELIVERY_MODES = {"course", "professional"}
RUN_STATUSES = {"ready", "partial", "degraded_no_product_value", "stopped"}
ANALYSIS_STATUSES = {"draft", "complete", "partial", "insufficient", "stale"}
DELIVERY_STATUSES = {"ready", "conditional", "blocked", "stale"}
UPSTREAM_ANALYSIS_STATUSES = {"complete", "partial"}
UPSTREAM_DELIVERY_STATUSES = {"ready", "conditional"}
DECISION_NAMES = ("认对", "看懂", "相信", "选对", "放心买")
DECISION_STATUSES = {"已讲清", "部分讲清", "未讲清", "资料不足"}
ACTION_TYPES = {"保留", "删除", "补充", "前移", "重新组织", "人工核实"}
ACTION_STATUSES = {"suggested_untested", "candidate", "blocked", "stale"}
READABILITY_STATUSES = {
    "not_reviewed",
    "readable",
    "partially_readable",
    "unreadable",
    "unsupported_archive",
}
SEQUENCE_STATUSES = {"unverified", "confirmed", "not_applicable"}
PAGE_SCOPES = {"shelf_entry", "main_images", "transaction_panel", "detail_page", "unknown"}
COMPONENT_SCOPES = {"main_images", "detail_page"}
ACTION_SCOPES = {"main_images", "detail_page", "cross_surface"}
DYNAMIC_STATUSES = {"not_dynamic", "current_snapshot", "expired", "unknown"}
CONTENT_LAYERS = {
    "evergreen_product",
    "current_campaign",
    "transaction_support",
    "trust_and_compliance",
}
MODULE_ROLES = {
    "identity",
    "problem_education",
    "value_claim",
    "mechanism",
    "evidence",
    "experience_demo",
    "sku_selection",
    "campaign_benefit",
    "fulfilment_service",
    "usage_boundary",
    "brand_trust",
    "other",
}
COMPONENT_APPLICABILITY = {
    "current_sku",
    "current_bundle_component",
    "current_product",
    "selectable_variant",
    "entry_specific",
    "related_product",
    "brand_general",
    "unknown",
}
PAGE_ROLES = {
    "single_product_page",
    "selection_hub_page",
    "entry_landing_page",
    "mixed",
    "unknown",
}
ENTRY_CONTEXT_BASES = {
    "provided_evidence",
    "page_visible_inference",
    "unknown",
}
BUNDLE_COMPONENT_ROLES = {
    "primary",
    "secondary",
    "gift",
    "unknown",
}
INFORMATION_NODE_TYPES = {
    "identity",
    "problem",
    "value",
    "mechanism",
    "proof",
    "experience",
    "variant_choice",
    "usage",
    "transaction",
    "fulfilment",
    "boundary",
    "handoff",
    "other",
}
MATCH_STATUSES = {"matched", "partially_matched", "misplaced", "unsupported", "unknown"}
PACKAGE_VERSION_STATUSES = {
    "not_applicable",
    "current_confirmed",
    "old_or_new_random",
    "multiple_versions",
    "unknown",
}
ADJACENCY_STATUSES = {"adjacent", "separated", "not_applicable", "unknown"}
CLAIM_LEVELS = {"product_fact", "page_claim", "market_performance", "user_signal", "unknown"}
CLAIM_SCOPES = {
    "current_sku",
    "current_variant",
    "current_product",
    "series",
    "brand",
    "market_performance",
    "not_applicable",
    "unknown",
}
SURFACES = {"shelf_entry", "main_images", "transaction_panel", "detail_page"}
SURFACE_COVERAGE_STATUSES = {"observed", "partially_observed", "not_provided", "unknown", "not_applicable"}
DECISION_CLOSURE_STATUSES = {"closed", "partially_closed", "not_closed", "unknown"}
HANDOFF_TYPES = {
    "variant_choice",
    "related_product",
    "alternative_usage",
    "post_purchase",
    "campaign_or_service",
    "brand_or_store_extension",
    "none",
    "unknown",
}
PRESENTATION_RELATIONSHIPS = {
    "matched",
    "serving_suggestion",
    "extra_material_required",
    "inconsistent",
    "unknown",
}
ELIGIBILITY_STATUSES = {
    "resolved",
    "partially_resolved",
    "unresolved",
    "not_applicable",
    "unknown",
}
VARIANT_TYPES = {
    "capacity",
    "quantity",
    "color_shade",
    "flavor",
    "formula",
    "life_stage",
    "breed",
    "size",
    "bundle",
    "usage",
    "product_form",
    "package_version",
    "other",
}
RAW_SPEC_GROUP_STATUSES = {
    "single_dimension",
    "mixed",
    "underspecified",
    "unknown",
}
VARIANT_OPTION_TYPES = {
    "real_sku",
    "explanation_entry",
    "service_entry",
    "related_product",
    "placeholder",
    "unknown",
}
TRANSACTION_ROLES = {
    "standard",
    "trial",
    "new_customer",
    "refill",
    "stock_up",
    "gift",
    "unknown",
}
REGULATED_PRODUCT_TYPES = {
    "ordinary_consumer_product",
    "special_use_cosmetic",
    "medical_device",
    "infant_formula",
    "infant_food",
    "other_regulated",
    "unknown",
}
HIGH_RISK_PRODUCT_TYPES = {
    "special_use_cosmetic",
    "medical_device",
    "infant_formula",
    "infant_food",
    "other_regulated",
}
CLAIM_TYPES = {
    "product_result",
    "composition",
    "market_performance",
    "user_feedback",
    "price_or_offer",
    "other",
}
CLAIM_SOURCE_READABILITY = {"readable", "partially_readable", "unreadable", "absent"}
PAGE_SUPPORT_STATUSES = {
    "supported_on_page",
    "partially_supported",
    "unsupported_on_page",
    "unknown",
}
SURFACE_RELATIONSHIPS = {"matched", "explicitly_scoped_other", "inconsistent", "unknown"}
CROSS_SURFACE_CONSISTENCY_STATUSES = {
    "fully_checked",
    "partially_checked",
    "not_checked",
    "unknown",
}
POST_PURCHASE_STATUSES = {
    "resolved",
    "partially_resolved",
    "not_checked",
    "not_applicable",
    "unknown",
}
UPGRADE_COMPARISON_STATUSES = {"not_applicable", "comparable", "partially_comparable", "not_comparable", "insufficient"}
CHAIN_FINDING_TYPES = {
    "missing",
    "too_early",
    "too_late",
    "jump",
    "too_dense",
    "isolated",
    "inconsistent",
    "action_without_decision",
    "cross_surface_inconsistent",
    "aggregate_implication",
    "evidence_mismatch",
    "premature_scope_switch",
    "post_closure_contamination",
    "presentation_actuality_mismatch",
    "continuation_without_return",
    "eligibility_unresolved",
    "target_object_conflict",
    "variant_evidence_leakage",
    "quantified_claim_scope_missing",
    "quantified_claim_basis_missing",
    "cross_surface_sku_mismatch",
    "transaction_role_mismatch",
    "regulated_identity_unresolved",
    "upgrade_comparison_missing",
}
COVERAGE_STATUSES = {"complete_observed", "partial_observed", "unknown", "not_applicable"}
BASIS_TYPES = {
    "product_value",
    "value_expression",
    "product_value_and_value_expression",
    "page_visible_only",
}
GAP_RETURN_TARGETS = {
    "product_value",
    "value_expression",
    "page_material",
    "human_confirmation",
}
ROUTE_OPTIONS = {
    "shared_master",
    "entry_adaptation",
    "dynamic_sku_adaptation",
    "standalone_page",
}
ROUTE_GATE_STATUSES = {"supported", "not_supported", "unknown"}
ROUTE_STATUSES = {"suggested_untested", "blocked", "stale"}

COURSE_REPORT = "01_商品页与主图优先优化行动单.md"
PROFESSIONAL_REPORTS = (
    "01_商品页判断与优先修复.md",
    "02_主图与详情页下一步.md",
)
DATA_FILES = (
    "page_manifest.json",
    "upstream_snapshot.json",
    "source_inventory.jsonl",
    "page_coverage.jsonl",
    "page_component_ledger.jsonl",
    "page_chain.json",
    "decision_ledger.jsonl",
    "action_ledger.jsonl",
    "validation_ledger.jsonl",
    "gap_ledger.jsonl",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def product_page_id(brand: str, product: str, sku: str, output_version: str = "V1") -> str:
    normalized = "|".join(
        value.strip().casefold() for value in (brand, product, sku, output_version)
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"PP-{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} 第 {line_number} 行不是有效 JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path.name} 第 {line_number} 行必须是 JSON 对象")
            rows.append(value)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value.rstrip() + "\n")


def md(value: Any, empty: str = "未提供") -> str:
    if value is None or value == "":
        return empty
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        if not value:
            return empty
        value = "、".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def bullet_lines(values: Iterable[Any], empty: str = "暂无") -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def delivery_paths(delivery: Path) -> dict[str, Path]:
    data = delivery / "data"
    return {
        "manifest": data / "page_manifest.json",
        "upstream": data / "upstream_snapshot.json",
        "sources": data / "source_inventory.jsonl",
        "coverage": data / "page_coverage.jsonl",
        "components": data / "page_component_ledger.jsonl",
        "chain": data / "page_chain.json",
        "decisions": data / "decision_ledger.jsonl",
        "actions": data / "action_ledger.jsonl",
        "validation": data / "validation_ledger.jsonl",
        "gaps": data / "gap_ledger.jsonl",
        "routing": data / "routing_decision.json",
        "course_report": delivery / COURSE_REPORT,
        "professional_report_01": delivery / PROFESSIONAL_REPORTS[0],
        "professional_report_02": delivery / PROFESSIONAL_REPORTS[1],
    }


def required_report_paths(delivery: Path, delivery_mode: str) -> tuple[Path, ...]:
    if delivery_mode == "course":
        return (delivery / COURSE_REPORT,)
    return tuple(delivery / name for name in PROFESSIONAL_REPORTS)
