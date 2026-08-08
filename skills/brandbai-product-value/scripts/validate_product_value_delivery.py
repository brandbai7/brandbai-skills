"""Validate a BrandBAI Product Value delivery before formal handoff."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from product_value_common import (
    ANALYSIS_STATUSES,
    DELIVERY_STATUSES,
    FACT_TYPES,
    FC_LEVELS,
    GAP_PRIORITIES,
    INPUT_MODES,
    P0_STATUSES,
    PKG_LEVELS,
    READINESS_LEVELS,
    SCHEMA_VERSION,
    SC_LEVELS,
    SKILL_VERSION,
    SKU_STATUSES,
    VALUE_LAYERS,
    delivery_paths,
    read_json,
    read_jsonl,
)


MANIFEST_FIELDS = {
    "schema_version",
    "skill_version",
    "product_value_id",
    "brand",
    "product",
    "category",
    "sku",
    "sku_status",
    "sku_basis",
    "identity_id",
    "input_mode",
    "package_version",
    "output_version",
    "fc",
    "sc",
    "pkg_level",
    "analysis_status",
    "delivery_status",
    "limitations",
    "created_at",
    "updated_at",
}
SOURCE_INVENTORY_FIELDS = {
    "source_file_id",
    "filename",
    "relative_path",
    "media_type",
    "size_bytes",
    "sha256",
    "status",
}
SOURCE_FIELDS = {
    "source_id",
    "source_file_id",
    "source_type",
    "title",
    "locator",
    "captured_at",
    "sku_scope",
    "status",
    "notes",
}
FACT_FIELDS = {"fact_id", "fact_type", "statement", "source_id", "locator", "sku_scope", "time_scope", "status", "boundary"}
EVIDENCE_FACT_FIELDS = {"evidence_detail_confidence", "exact_fields_verified"}
FABE_FIELDS = {
    "fabe_id",
    "value_id",
    "feature",
    "feature_fact_ids",
    "advantage",
    "benefit",
    "evidence",
    "evidence_fact_ids",
    "reference_frame",
    "user_language",
    "derivation_status",
    "boundary",
}
ANCHOR_FIELDS = {"anchor_id", "anchor_type", "statement", "fact_ids", "status", "boundary"}
VALUE_FIELDS = {
    "value_id",
    "layer",
    "p0_candidate",
    "p0_status",
    "user_task",
    "value_statement",
    "supporting_fact_ids",
    "strategic_potential",
    "execution_maturity",
    "user_perception_goal",
    "sku_scope",
    "scope",
    "cannot_prove",
    "downstream_readiness",
}
DECISION_FIELDS = {
    "decision_id",
    "candidate_value_ids",
    "recommended_value_id",
    "status",
    "rationale",
    "current_execution_axis",
    "cannot_prove",
    "validation_questions",
    "decided_at",
    "valid_until",
    "supersedes",
}
GAP_FIELDS = {"gap_id", "category", "missing", "impact", "minimum_needed", "priority", "state"}

RISKY_INFERENCE_RULES = (
    (re.compile(r"SGS.{0,8}(?:安全)?认证|安全认证", re.IGNORECASE), "检测报告不能自动改写为安全认证"),
    (re.compile(r"(?:确保|保证).{0,12}(?:原料)?品质"), "检测或选材信号不能写成确保品质"),
    (re.compile(r"敏感人群.{0,8}(?:安心|适合|友好)"), "不得从无硫熏或配料信息推导敏感人群适用性"),
    (re.compile(r"控脂人群.{0,8}(?:安心|适合|友好)"), "零脂肪标示不能自动推导控脂人群适用性"),
    (re.compile(r"(?:滋养|滋补)(?:收益|功效|效果)"), "食品商品价值不得预设未经资料支持的滋养收益或功效"),
    (re.compile(r"第三方(?:安全)?检测背书"), "页面展示的检测报告应写成支持该页面主张，不写成笼统背书"),
    (re.compile(r"无刺激"), "不得把页面中的入口温和或去麻描述扩大为无刺激"),
)
EXPIRY_WORDS_RE = re.compile(r"已过期|已经过期|时效性过期")
DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
INTERNAL_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:PV-[0-9a-f]{12}|(?:SF|SRC|ID|ANCHOR|FABE|V|F|H|EX|U|DYN|STRAT|GAP|P0D)-\d{3,})(?![A-Za-z0-9])"
)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
ALL_SKU_RE = re.compile(r"(?:全\s*SKU|所有\s*SKU|all[_\s-]*skus?)", re.IGNORECASE)
QUANTIFIED_STEAM_DRY_RE = re.compile(
    r"(?:九|[一二三四五六七八九十两0-9]+)\s*蒸\s*(?:九|[一二三四五六七八九十两0-9]+)\s*晒"
)
EXACT_EVIDENCE_FIELD_RE = re.compile(
    r"报告(?:编号|号)|发布日期|签发日期|报告日期|检测日期|证书编号|批次号|生产批号|证书日期"
)


def parse_reference_date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def classify_time_scope(value: Any, reference: date | None) -> str | None:
    """Classify a fully dated DYN scope at the delivery snapshot date."""

    if reference is None:
        return None
    dates: list[date] = []
    for year, month, day in DATE_RE.findall(str(value)):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            return None
    if not dates:
        return None
    start = dates[0]
    end = dates[-1]
    if reference < start:
        return "upcoming"
    if reference > end:
        return "expired"
    return "active"


def iter_analysis_texts(
    facts: list[dict[str, Any]],
    fabe: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    values: list[dict[str, Any]],
    decision: dict[str, Any],
) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for item in facts:
        if item.get("fact_type") == "H":
            texts.extend((f"{item.get('fact_id')}.{key}", str(item.get(key, ""))) for key in ("statement", "boundary"))
    for item in fabe:
        texts.extend(
            (f"{item.get('fabe_id')}.{key}", str(item.get(key, "")))
            for key in ("advantage", "benefit", "user_language", "boundary")
        )
    for item in anchors:
        texts.append((f"{item.get('anchor_id')}.statement", str(item.get("statement", ""))))
    for item in values:
        texts.extend(
            (f"{item.get('value_id')}.{key}", str(item.get(key, "")))
            for key in ("user_task", "value_statement", "user_perception_goal")
        )
    texts.extend(
        (f"p0_decision.{key}", str(decision.get(key, "")))
        for key in ("rationale", "current_execution_axis")
    )
    return texts


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def duplicate_ids(records: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = str(record.get(key, ""))
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []

    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"缺少必需文件 {name}: {path}")
    if errors:
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    try:
        manifest = read_json(paths["manifest"])
        source_inventory = read_jsonl(paths["source_inventory"])
        sources = read_jsonl(paths["sources"])
        facts = read_jsonl(paths["facts"])
        fabe = read_jsonl(paths["fabe"])
        anchors = read_jsonl(paths["anchors"])
        values = read_jsonl(paths["values"])
        decision = read_json(paths["decision"])
        gaps = read_jsonl(paths["gaps"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    counts = {
        "source_files": len(source_inventory),
        "sources": len(sources),
        "facts": len(facts),
        "fabe": len(fabe),
        "anchors": len(anchors),
        "values": len(values),
        "gaps": len(gaps),
    }

    missing = missing_fields(manifest, MANIFEST_FIELDS)
    if missing:
        errors.append(f"product_manifest.json 缺少字段: {', '.join(missing)}")
    if not re.fullmatch(r"PV-[0-9a-f]{12}", str(manifest.get("product_value_id", ""))):
        errors.append("product_value_id 必须使用 PV- 加 12 位小写十六进制")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须是 {SCHEMA_VERSION}")
    if manifest.get("skill_version") != SKILL_VERSION:
        errors.append(f"skill_version 必须是 {SKILL_VERSION}")
    if not re.fullmatch(r"ID-\d{3,}", str(manifest.get("identity_id", ""))):
        errors.append("identity_id 格式无效")
    if manifest.get("input_mode") not in INPUT_MODES:
        errors.append("input_mode 不在允许范围")
    if manifest.get("fc") not in FC_LEVELS:
        errors.append("fc 不在 FC0—FC3 范围")
    if manifest.get("sc") not in SC_LEVELS:
        errors.append("sc 不在 SC0—SC3 范围")
    if manifest.get("pkg_level") not in PKG_LEVELS:
        errors.append("pkg_level 不在 PKG-L0—PKG-L4 范围")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        errors.append("analysis_status 不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        errors.append("delivery_status 不在允许范围")
    if manifest.get("sku_status") not in SKU_STATUSES:
        errors.append("sku_status 必须是 confirmed/partial/unverified")
    if not str(manifest.get("sku_basis", "")).strip():
        errors.append("sku_basis 不得为空；标题片段不能单独作为 SKU 确认依据")
    if manifest.get("sku_status") == "confirmed":
        sku_basis = str(manifest.get("sku_basis", ""))
        if not re.search(r"SKU\s*选择|规格(?:栏|表|选择)|包装|商品信息|成交单元|订单", sku_basis, re.IGNORECASE):
            errors.append("sku_status=confirmed 时，sku_basis 必须来自 SKU 选择器、包装、规格表、商品信息区或订单成交单元")
    if manifest.get("analysis_status") == "draft":
        errors.append("analysis_status=draft，不得作为正式交付")
    if not isinstance(manifest.get("limitations"), list):
        errors.append("limitations 必须是数组")

    ledger_specs = (
        ("source_inventory", source_inventory, "source_file_id", SOURCE_INVENTORY_FIELDS, r"SF-\d{3,}"),
        ("source_ledger", sources, "source_id", SOURCE_FIELDS, r"SRC-\d{3,}"),
        ("fact_ledger", facts, "fact_id", FACT_FIELDS, r"(?:F|STRAT|DYN|U|EX|H)-\d{3,}"),
        ("fabe_ledger", fabe, "fabe_id", FABE_FIELDS, r"FABE-\d{3,}"),
        ("anchor_ledger", anchors, "anchor_id", ANCHOR_FIELDS, r"ANCHOR-\d{3,}"),
        ("value_ledger", values, "value_id", VALUE_FIELDS, r"V-\d{3,}"),
        ("gap_ledger", gaps, "gap_id", GAP_FIELDS, r"GAP-\d{3,}"),
    )
    for ledger_name, records, id_key, fields, pattern in ledger_specs:
        for index, record in enumerate(records, start=1):
            record_missing = missing_fields(record, fields)
            if record_missing:
                errors.append(f"{ledger_name} 第 {index} 条缺少字段: {', '.join(record_missing)}")
            if not re.fullmatch(pattern, str(record.get(id_key, ""))):
                errors.append(f"{ledger_name} 第 {index} 条 {id_key} 格式无效")
        duplicates = duplicate_ids(records, id_key)
        if duplicates:
            errors.append(f"{ledger_name} 存在重复 ID: {', '.join(duplicates)}")

    source_files_by_id = {item.get("source_file_id"): item for item in source_inventory}
    for item in source_inventory:
        source_file_id = str(item.get("source_file_id", ""))
        relative_path = str(item.get("relative_path", ""))
        filename = str(item.get("filename", ""))
        if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            errors.append(f"{source_file_id} 的 relative_path 必须是输入目录内的相对路径")
        if Path(relative_path).name != filename:
            errors.append(f"{source_file_id} 的 filename 与 relative_path 不一致")
        if not isinstance(item.get("size_bytes"), int) or item.get("size_bytes", -1) < 0:
            errors.append(f"{source_file_id} 的 size_bytes 必须是非负整数")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            errors.append(f"{source_file_id} 的 sha256 必须是 64 位小写十六进制")
        if item.get("status") != "indexed":
            errors.append(f"{source_file_id} 的 status 必须是 indexed")

    for source in sources:
        source_id = str(source.get("source_id", ""))
        source_file_id = str(source.get("source_file_id", "")).strip()
        locator = str(source.get("locator", "")).strip()
        if source_file_id:
            indexed = source_files_by_id.get(source_file_id)
            if indexed is None:
                errors.append(f"{source_id} 引用了不存在的 source_file_id: {source_file_id}")
            elif str(indexed.get("relative_path", "")) not in locator:
                errors.append(f"{source_id} 的 locator 必须保留 {source_file_id} 的真实 relative_path")
        elif not URL_RE.match(locator):
            errors.append(f"{source_id} 是本地来源时必须绑定 source_file_id；仅 URL 来源可留空")

    source_ids = {item.get("source_id") for item in sources}
    sources_by_id = {item.get("source_id"): item for item in sources}
    fact_ids = {item.get("fact_id") for item in facts}
    facts_by_id = {item.get("fact_id"): item for item in facts}
    value_ids = {item.get("value_id") for item in values}
    values_by_id = {item.get("value_id"): item for item in values}
    fabe_by_value: dict[str, list[dict[str, Any]]] = {}
    snapshot_date = parse_reference_date(manifest.get("updated_at"))
    dyn_expected_states: dict[str, str] = {}

    for fact in facts:
        fact_id = str(fact.get("fact_id", ""))
        fact_type = fact.get("fact_type")
        if fact_type not in FACT_TYPES:
            errors.append(f"{fact_id} 的 fact_type 不在允许范围")
        expected_prefix = "F" if fact_type in {"F-PAGE", "F-EVIDENCE"} else fact_type
        if expected_prefix and not fact_id.startswith(f"{expected_prefix}-"):
            errors.append(f"{fact_id} 与 fact_type={fact_type} 的前缀不一致")
        source_id = fact.get("source_id")
        if source_id not in source_ids:
            if fact_type == "H" and not source_id and str(fact.get("boundary", "")).strip():
                warnings.append(f"{fact_id} 是无直接来源的分析推导，已依赖 boundary 限定")
            else:
                errors.append(f"{fact_id} 引用了不存在的 source_id: {source_id}")
        if fact_type == "F-EVIDENCE":
            evidence_missing = missing_fields(fact, EVIDENCE_FACT_FIELDS)
            if evidence_missing:
                errors.append(f"{fact_id} 是证据事实，缺少字段: {', '.join(evidence_missing)}")
            confidence = fact.get("evidence_detail_confidence")
            exact_fields_verified = fact.get("exact_fields_verified")
            if confidence not in {"high", "medium", "low"}:
                errors.append(f"{fact_id} 的 evidence_detail_confidence 必须是 high/medium/low")
            if not isinstance(exact_fields_verified, bool):
                errors.append(f"{fact_id} 的 exact_fields_verified 必须是布尔值")
            exact_text = f"{fact.get('statement', '')} {fact.get('locator', '')}"
            if EXACT_EVIDENCE_FIELD_RE.search(exact_text) and not (
                confidence == "high" and exact_fields_verified is True
            ):
                errors.append(f"{fact_id} 含报告编号、日期、批次等精确字段，必须 high 且 exact_fields_verified=true")
        if QUANTIFIED_STEAM_DRY_RE.search(str(fact.get("statement", ""))):
            source = sources_by_id.get(source_id, {})
            source_text = " ".join(
                str(source.get(key, "")) for key in ("title", "locator", "notes")
            )
            if not QUANTIFIED_STEAM_DRY_RE.search(source_text):
                errors.append(f"{fact_id} 把反复蒸晒扩大成具体次数；来源标题、定位或摘录未支持该次数")
        if fact_type == "DYN" and not str(fact.get("time_scope", "")).strip():
            errors.append(f"{fact_id} 是动态交易事实，必须填写 time_scope")
        if fact_type == "DYN":
            expected = classify_time_scope(fact.get("time_scope"), snapshot_date)
            if expected is None:
                warnings.append(f"{fact_id} 的 time_scope 无法按完整日期自动核验，须人工确认年份和时区")
            else:
                dyn_expected_states[fact_id] = expected
                status = str(fact.get("status", "")).strip().lower()
                if expected == "active" and status in {"expired", "stale", "inactive"}:
                    errors.append(f"{fact_id} 在交付更新时间仍处活动期，但 status={status}")
                if expected == "expired" and status in {"active", "confirmed", "current"}:
                    errors.append(f"{fact_id} 在交付更新时间已经结束，但 status={status}")
                if expected == "upcoming" and status in {"active", "confirmed", "current", "expired", "stale"}:
                    errors.append(f"{fact_id} 在交付更新时间尚未开始，但 status={status}")
                if expected == "active" and EXPIRY_WORDS_RE.search(str(fact.get("boundary", ""))):
                    errors.append(f"{fact_id} 在交付更新时间仍处活动期，但 boundary 写成已过期")
        if not str(fact.get("statement", "")).strip():
            errors.append(f"{fact_id} 的 statement 为空")
        if not str(fact.get("boundary", "")).strip():
            errors.append(f"{fact_id} 的 boundary 为空")

    for anchor in anchors:
        anchor_id = str(anchor.get("anchor_id", ""))
        if anchor.get("anchor_type") not in {"main", "supporting"}:
            errors.append(f"{anchor_id} 的 anchor_type 必须是 main 或 supporting")
        references = anchor.get("fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{anchor_id} 必须引用至少一个 fact_id")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{anchor_id} 引用了不存在的 fact_id: {fact_id}")

    allowed_derivation_statuses = {"page_supported", "reasoned", "to_validate"}
    for item in fabe:
        fabe_id = str(item.get("fabe_id", ""))
        value_id = str(item.get("value_id", ""))
        if value_id not in value_ids:
            errors.append(f"{fabe_id} 引用了不存在的 value_id: {value_id}")
        else:
            fabe_by_value.setdefault(value_id, []).append(item)
        for key in ("feature_fact_ids", "evidence_fact_ids"):
            references = item.get(key)
            if not isinstance(references, list) or not references:
                errors.append(f"{fabe_id} 的 {key} 必须引用至少一个 fact_id")
            else:
                for fact_id in references:
                    if fact_id not in fact_ids:
                        errors.append(f"{fabe_id} 的 {key} 引用了不存在的 fact_id: {fact_id}")
        for key in ("feature", "advantage", "benefit", "evidence", "reference_frame", "user_language", "boundary"):
            if not str(item.get(key, "")).strip():
                errors.append(f"{fabe_id} 的 {key} 为空")
        if item.get("derivation_status") not in allowed_derivation_statuses:
            errors.append(f"{fabe_id} 的 derivation_status 必须是 page_supported/reasoned/to_validate")

    allowed_axis = {"high", "medium", "low", "unknown"}
    for value in values:
        value_id = str(value.get("value_id", ""))
        if value.get("layer") not in VALUE_LAYERS:
            errors.append(f"{value_id} 的 layer 不在允许范围")
        if not isinstance(value.get("p0_candidate"), bool):
            errors.append(f"{value_id} 的 p0_candidate 必须是布尔值")
        if value.get("p0_status") not in P0_STATUSES | {"", "not_applicable"}:
            errors.append(f"{value_id} 的 p0_status 不在允许范围")
        references = value.get("supporting_fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{value_id} 必须引用至少一个事实或推导")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{value_id} 引用了不存在的 fact_id: {fact_id}")
        scope_text = f"{value.get('sku_scope', '')} {value.get('scope', '')}"
        if ALL_SKU_RE.search(scope_text):
            unsupported = [
                str(fact_id)
                for fact_id in (references or [])
                if not ALL_SKU_RE.search(str(facts_by_id.get(fact_id, {}).get("sku_scope", "")))
            ]
            if unsupported:
                errors.append(
                    f"{value_id} 声称适用于全 SKU，但支撑事实未逐条覆盖全 SKU: {', '.join(unsupported)}"
                )
        for key in ("strategic_potential", "execution_maturity"):
            if value.get(key) not in allowed_axis:
                errors.append(f"{value_id} 的 {key} 必须是 high/medium/low/unknown")
        if value.get("downstream_readiness") not in READINESS_LEVELS:
            errors.append(f"{value_id} 的 downstream_readiness 不在允许范围")
        if not isinstance(value.get("cannot_prove"), list):
            errors.append(f"{value_id} 的 cannot_prove 必须是数组")
        if not str(value.get("value_statement", "")).strip():
            errors.append(f"{value_id} 的 value_statement 为空")
        if value.get("layer") != "deferred" and not fabe_by_value.get(value_id):
            errors.append(f"{value_id} 缺少 FABE 完整推导链")

    for gap in gaps:
        gap_id = str(gap.get("gap_id", ""))
        if gap.get("priority") not in GAP_PRIORITIES:
            errors.append(f"{gap_id} 的 priority 必须是 P0/P1/P2/P3")
        combined = " ".join(str(gap.get(key, "")) for key in ("missing", "impact", "minimum_needed"))
        for fact_id, expected in dyn_expected_states.items():
            if expected == "active" and fact_id in combined and EXPIRY_WORDS_RE.search(combined):
                errors.append(f"{gap_id} 把仍处活动期的 {fact_id} 写成已过期")

    limitation_text = " ".join(str(item) for item in (manifest.get("limitations") or []))
    for fact_id, expected in dyn_expected_states.items():
        if expected == "active" and (fact_id in limitation_text or "DYN" in limitation_text) and EXPIRY_WORDS_RE.search(limitation_text):
            errors.append(f"limitations 把仍处活动期的 {fact_id} 写成已过期")

    for location, text in iter_analysis_texts(facts, fabe, anchors, values, decision):
        for pattern, explanation in RISKY_INFERENCE_RULES:
            if pattern.search(text):
                errors.append(f"{location} 存在越界表达：{explanation}")

    p0_values = [item for item in values if item.get("layer") == "P0"]
    if len(p0_values) > 1:
        errors.append("当前 layer=P0 的价值超过一个；未推荐候选应保留在其他层或 deferred")
    for layer in ("P1", "P2"):
        count = sum(1 for item in values if item.get("layer") == layer)
        if count > 3:
            errors.append(f"普通版 {layer} 超过 3 个，需合并或降为暂缓")

    decision_missing = missing_fields(decision, DECISION_FIELDS)
    if decision_missing:
        errors.append(f"p0_decision.json 缺少字段: {', '.join(decision_missing)}")
    if not re.fullmatch(r"P0D-\d{3,}", str(decision.get("decision_id", ""))):
        errors.append("decision_id 格式无效")
    if decision.get("status") not in P0_STATUSES:
        errors.append("P0 决策状态不在允许范围")
    candidate_ids = decision.get("candidate_value_ids")
    if not isinstance(candidate_ids, list):
        errors.append("candidate_value_ids 必须是数组")
        candidate_ids = []
    for value_id in candidate_ids:
        if value_id not in value_ids:
            errors.append(f"P0 候选池引用了不存在的 value_id: {value_id}")
        elif values_by_id[value_id].get("p0_candidate") is not True:
            errors.append(f"{value_id} 在 P0 候选池中，但 p0_candidate 不是 true")
    recommended_id = decision.get("recommended_value_id")
    if recommended_id:
        if recommended_id not in value_ids:
            errors.append(f"P0 推荐引用了不存在的 value_id: {recommended_id}")
        else:
            if recommended_id not in candidate_ids:
                errors.append("P0 推荐值不在 candidate_value_ids 中")
            if values_by_id[recommended_id].get("layer") != "P0":
                errors.append("P0 推荐值的 layer 必须是 P0")

    analysis_status = manifest.get("analysis_status")
    delivery_status = manifest.get("delivery_status")
    if analysis_status in {"complete", "partial"}:
        for key in ("brand", "product", "sku"):
            if not str(manifest.get(key, "")).strip():
                errors.append(f"analysis_status={analysis_status} 时 {key} 不得为空")
        if not sources:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个来源")
        if not facts:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个事实或推导")
        if not values:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个可用价值")
        if manifest.get("sku_status") in {"partial", "unverified"}:
            has_open_sku_gap = any(
                gap.get("state") == "open"
                and re.search(r"SKU|规格|成交单元|商品身份", f"{gap.get('category', '')} {gap.get('missing', '')}", re.IGNORECASE)
                for gap in gaps
            )
            if not has_open_sku_gap:
                errors.append("SKU 未完全确认时，必须登记一个开放的 SKU/规格资料缺口")
            if delivery_status == "ready":
                errors.append("SKU 未完全确认时 delivery_status 不得为 ready")
    if analysis_status == "complete":
        if not recommended_id:
            errors.append("analysis_status=complete 时必须有当前推荐 P0")
        if decision.get("status") in {"P0-CANDIDATE", "P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
            errors.append("analysis_status=complete 与当前 P0 决策状态不一致")
        if delivery_status not in {"ready", "conditional"}:
            errors.append("analysis_status=complete 时 delivery_status 应为 ready 或 conditional")
    elif analysis_status == "partial":
        if delivery_status != "conditional":
            errors.append("analysis_status=partial 时 delivery_status 必须是 conditional")
    elif analysis_status == "insufficient":
        if not gaps:
            errors.append("analysis_status=insufficient 时至少需要一个资料缺口")
        if delivery_status != "blocked":
            errors.append("analysis_status=insufficient 时 delivery_status 必须是 blocked")
    elif analysis_status == "stale":
        if delivery_status != "stale":
            errors.append("analysis_status=stale 时 delivery_status 必须是 stale")

    for report_key in ("report_01", "report_02"):
        text = paths[report_key].read_text(encoding="utf-8")
        if "{{" in text or "}}" in text:
            errors.append(f"{paths[report_key].name} 仍包含模板占位符")
        if re.search(r"[A-Za-z]:\\(?:Users|Documents|Desktop)\\", text, re.IGNORECASE):
            errors.append(f"{paths[report_key].name} 暴露了本地绝对路径")
        if INTERNAL_ID_RE.search(text):
            errors.append(f"{paths[report_key].name} 暴露了内部资产 ID")
        if re.search(r"[（(]\s*[,/;+、，;；:：]+|[,/;+、，;；:：]+\s*[)）]", text):
            errors.append(f"{paths[report_key].name} 含隐藏内部 ID 后遗留的异常标点")
        if re.search(r"\|\s*>[^|\r\n]*\|", text):
            errors.append(f"{paths[report_key].name} 的表格单元格含多余的 > 符号")

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "analysis_status": analysis_status,
        "delivery_status": delivery_status,
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
