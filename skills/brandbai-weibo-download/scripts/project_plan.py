"""Deterministic project-plan contracts for BrandBAI Weibo collection."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from collector_core import (
    CollectionError,
    canonical_hotlist_url,
    canonical_post_id,
    canonical_post_url,
    canonical_profile_id,
    canonical_profile_url,
    canonical_search_url,
    canonical_supertopic_id,
    canonical_supertopic_url,
    derived_id,
    normalize_hotlist_category,
    normalize_supertopic_tab,
    normalize_topic_query,
)


PROJECT_SCHEMA_VERSION = "brandbai.weibo.project.v1"
DRY_RUN_SCHEMA_VERSION = "brandbai.weibo.project-dry-run.v1"
SUPPORTED_PRESETS = {"celebrity_announcement"}
CAPTURE_DEPTHS = {"fast", "standard", "deep"}
ACTOR_ROLES = {
    "celebrity",
    "brand",
    "studio",
    "agency",
    "brand_subaccount",
    "fan_org",
    "media",
    "other",
}
SELECTION_RULES = {"seed_only", "seed_plus_role_posts", "manual_only"}
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,95}$")
CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")


def load_project_plan(path: Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CollectionError(f"Project plan does not exist: {source}") from exc
    except json.JSONDecodeError as exc:
        raise CollectionError(f"Project plan is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CollectionError("Project plan root must be a JSON object")
    return value


def _text(value: Any, label: str, *, maximum: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise CollectionError(f"{label} must not be empty")
    if len(text) > maximum:
        raise CollectionError(f"{label} is too long")
    return text


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int = 10000) -> int:
    if isinstance(value, bool):
        raise CollectionError(f"{label} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CollectionError(f"{label} must be an integer") from exc
    if number < minimum or number > maximum:
        raise CollectionError(f"{label} must be between {minimum} and {maximum}")
    return number


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise CollectionError(f"{label} must be true or false")
    return value


def _unique_texts(values: Any, label: str, *, normalizer=None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise CollectionError(f"{label} must be a list")
    output: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values, start=1):
        text = _text(value, f"{label}[{index}]")
        normalized = normalizer(text) if normalizer else text
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _date_text(value: Any, label: str) -> str:
    text = _text(value, label, maximum=10)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise CollectionError(f"{label} must use YYYY-MM-DD") from exc
    return text


def _normalize_actor(value: Any, campaign_id: str, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectionError(f"campaign {campaign_id} actor {index} must be an object")
    role = _text(value.get("role"), f"campaign {campaign_id} actor role", maximum=40).lower()
    if role not in ACTOR_ROLES:
        raise CollectionError(f"campaign {campaign_id} has unsupported actor role: {role}")
    source = value.get("profile_url") or value.get("profile_uid") or value.get("uid")
    try:
        uid = canonical_profile_id(_text(source, f"campaign {campaign_id} actor profile"))
    except ValueError as exc:
        raise CollectionError(f"campaign {campaign_id} actor profile is invalid: {exc}") from exc
    actor_id = str(value.get("actor_id") or f"{role}:{uid}").strip()
    result = {
        "actor_id": actor_id,
        "role": role,
        "profile_uid": uid,
        "canonical_url": canonical_profile_url(uid),
    }
    display_name = str(value.get("display_name") or "").strip()
    if display_name:
        result["display_name"] = display_name[:120]
    return result


def _normalize_seed_post(value: Any, campaign_id: str, index: int) -> dict[str, Any]:
    if isinstance(value, str):
        source = value
        reason = "explicit_seed_post"
    elif isinstance(value, dict):
        source = value.get("canonical_url") or value.get("url") or value.get("post_id")
        reason = str(value.get("selection_reason") or "explicit_seed_post").strip()
    else:
        raise CollectionError(f"campaign {campaign_id} seed_posts[{index}] must be a string or object")
    try:
        source_text = _text(source, f"campaign {campaign_id} seed_posts[{index}]")
        post_id = canonical_post_id(source_text)
        canonical_url = canonical_post_url(source_text)
    except ValueError as exc:
        raise CollectionError(f"campaign {campaign_id} seed post is invalid: {exc}") from exc
    return {
        "post_id": post_id,
        "canonical_url": canonical_url,
        "selection_reason": reason[:120] or "explicit_seed_post",
    }


def _normalize_campaign(value: Any, position: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectionError(f"campaigns[{position}] must be an object")
    campaign_id = _text(value.get("campaign_id"), f"campaigns[{position}].campaign_id", maximum=64)
    if not CAMPAIGN_ID_RE.fullmatch(campaign_id):
        raise CollectionError("campaign_id must use letters, numbers, dot, underscore, colon or hyphen")

    actors_raw = value.get("actors")
    if not isinstance(actors_raw, list) or not actors_raw:
        raise CollectionError(f"campaign {campaign_id} must include actors")
    actors = [_normalize_actor(actor, campaign_id, index) for index, actor in enumerate(actors_raw, start=1)]
    actor_keys = [(actor["role"], actor["profile_uid"]) for actor in actors]
    if len(actor_keys) != len(set(actor_keys)):
        raise CollectionError(f"campaign {campaign_id} contains duplicate actors")
    roles = {actor["role"] for actor in actors}
    if not {"celebrity", "brand"}.issubset(roles):
        raise CollectionError(f"campaign {campaign_id} must include celebrity and brand actors")

    queries = _unique_texts(value.get("queries"), f"campaign {campaign_id} queries")
    topics = _unique_texts(
        value.get("topics"), f"campaign {campaign_id} topics", normalizer=normalize_topic_query
    )
    supertopics_raw = value.get("supertopics") or []
    if not isinstance(supertopics_raw, list):
        raise CollectionError(f"campaign {campaign_id} supertopics must be a list")
    supertopics: list[dict[str, str]] = []
    seen_supertopics: set[str] = set()
    for index, item in enumerate(supertopics_raw, start=1):
        if isinstance(item, str):
            source, tab = item, value.get("supertopic_tab", "热门")
        elif isinstance(item, dict):
            source = item.get("canonical_url") or item.get("url") or item.get("supertopic_id")
            tab = item.get("selected_tab") or item.get("tab") or value.get("supertopic_tab", "热门")
        else:
            raise CollectionError(f"campaign {campaign_id} supertopics[{index}] must be a string or object")
        try:
            supertopic_id = canonical_supertopic_id(_text(source, f"campaign {campaign_id} supertopic"))
            selected_tab = normalize_supertopic_tab(str(tab or "热门"))
        except ValueError as exc:
            raise CollectionError(f"campaign {campaign_id} supertopic is invalid: {exc}") from exc
        key = f"{supertopic_id}:{selected_tab}"
        if key in seen_supertopics:
            continue
        seen_supertopics.add(key)
        supertopics.append({
            "supertopic_id": supertopic_id,
            "canonical_url": canonical_supertopic_url(supertopic_id),
            "selected_tab": selected_tab,
        })

    hotlists_raw = value.get("hotlists") or []
    if not isinstance(hotlists_raw, list):
        raise CollectionError(f"campaign {campaign_id} hotlists must be a list")
    hotlists: list[dict[str, str]] = []
    seen_hotlists: set[str] = set()
    for index, item in enumerate(hotlists_raw, start=1):
        try:
            code, name = normalize_hotlist_category(_text(item, f"campaign {campaign_id} hotlists[{index}]"))
        except ValueError as exc:
            raise CollectionError(f"campaign {campaign_id} hotlist is invalid: {exc}") from exc
        if code in seen_hotlists:
            continue
        seen_hotlists.add(code)
        hotlists.append({"category_code": code, "category_name": name, "canonical_url": canonical_hotlist_url(code)})

    seed_raw = value.get("seed_posts") or []
    if not isinstance(seed_raw, list):
        raise CollectionError(f"campaign {campaign_id} seed_posts must be a list")
    seed_posts: list[dict[str, Any]] = []
    seen_posts: set[str] = set()
    for index, item in enumerate(seed_raw, start=1):
        post = _normalize_seed_post(item, campaign_id, index)
        if post["post_id"] in seen_posts:
            continue
        seen_posts.add(post["post_id"])
        seed_posts.append(post)

    if not queries and not seed_posts:
        raise CollectionError(f"campaign {campaign_id} must include at least one query or seed post")

    return {
        "campaign_id": campaign_id,
        "campaign_name": str(value.get("campaign_name") or campaign_id).strip()[:120],
        "actors": actors,
        "queries": queries,
        "topics": topics,
        "supertopics": supertopics,
        "hotlists": hotlists,
        "seed_posts": seed_posts,
        "profile_recent_n": _integer(value.get("profile_recent_n", 8), f"campaign {campaign_id} profile_recent_n", maximum=100),
        "search_limit": _integer(value.get("search_limit", 20), f"campaign {campaign_id} search_limit", minimum=1, maximum=500),
        "hotlist_limit": _integer(value.get("hotlist_limit", 50), f"campaign {campaign_id} hotlist_limit", minimum=1, maximum=100),
    }


def _normalize_deep_capture(value: Any, depth: str) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CollectionError("deep_capture must be an object")
    default_limit = 0 if depth == "deep" else 200
    rule = str(value.get("selection_rule") or "seed_plus_role_posts").strip()
    if rule not in SELECTION_RULES:
        raise CollectionError(f"Unsupported deep_capture selection_rule: {rule}")
    return {
        "enabled": depth != "fast",
        "selection_rule": rule,
        "max_deep_posts_per_campaign": _integer(
            value.get("max_deep_posts_per_campaign", 4),
            "deep_capture.max_deep_posts_per_campaign",
            minimum=1,
            maximum=100,
        ),
        "comment_limit_per_post": _integer(
            value.get("comment_limit_per_post", default_limit),
            "deep_capture.comment_limit_per_post",
            maximum=100000,
        ),
        "repost_limit_per_post": _integer(
            value.get("repost_limit_per_post", default_limit),
            "deep_capture.repost_limit_per_post",
            maximum=100000,
        ),
        "expand_replies": _boolean(value.get("expand_replies", True), "deep_capture.expand_replies"),
        "download_assets": _boolean(value.get("download_assets", True), "deep_capture.download_assets"),
    }


def normalize_project_plan(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CollectionError("Project plan root must be an object")
    schema = _text(value.get("schema_version"), "schema_version", maximum=80)
    if schema != PROJECT_SCHEMA_VERSION:
        raise CollectionError(f"Unsupported project schema_version: {schema}")
    project_id = _text(value.get("project_id"), "project_id", maximum=96)
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise CollectionError("project_id must use letters, numbers, dot, underscore, colon or hyphen")
    project_name = _text(value.get("project_name"), "project_name", maximum=120)
    preset = _text(value.get("preset"), "preset", maximum=80)
    if preset not in SUPPORTED_PRESETS:
        raise CollectionError(f"Unsupported project preset: {preset}")
    depth = _text(value.get("capture_depth"), "capture_depth", maximum=20).lower()
    if depth not in CAPTURE_DEPTHS:
        raise CollectionError("capture_depth must be fast, standard or deep")

    window = value.get("time_window")
    if not isinstance(window, dict):
        raise CollectionError("time_window must be an object")
    start = _date_text(window.get("start"), "time_window.start")
    end = _date_text(window.get("end"), "time_window.end")
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise CollectionError("time_window.start must not be after time_window.end")

    campaigns_raw = value.get("campaigns")
    if not isinstance(campaigns_raw, list) or not campaigns_raw:
        raise CollectionError("campaigns must contain at least one campaign")
    campaigns = [_normalize_campaign(item, index) for index, item in enumerate(campaigns_raw, start=1)]
    campaign_ids = [campaign["campaign_id"] for campaign in campaigns]
    if len(campaign_ids) != len(set(campaign_ids)):
        raise CollectionError("campaign_id values must be unique within a project")

    deep_capture = _normalize_deep_capture(value.get("deep_capture"), depth)
    if deep_capture["enabled"] and deep_capture["selection_rule"] in {"seed_only", "manual_only"}:
        if any(not campaign["seed_posts"] for campaign in campaigns):
            raise CollectionError("seed_only/manual_only deep capture requires seed_posts in every campaign")
    if deep_capture["enabled"]:
        oversized = [
            campaign["campaign_id"] for campaign in campaigns
            if len(campaign["seed_posts"]) > deep_capture["max_deep_posts_per_campaign"]
        ]
        if oversized:
            raise CollectionError(
                "max_deep_posts_per_campaign is smaller than explicit seed_posts for: "
                + ", ".join(oversized)
            )

    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project_id": project_id,
        "project_name": project_name,
        "preset": preset,
        "capture_depth": depth,
        "time_window": {"start": start, "end": end},
        "campaigns": campaigns,
        "deep_capture": deep_capture,
    }


def _task_id(project_id: str, campaign_id: str, phase: str, source_type: str, target_key: str) -> str:
    return derived_id("weibo-project-task", project_id, campaign_id, phase, source_type, target_key)


def _task(
    *, project_id: str, campaign_id: str, phase: str, source_type: str,
    target_key: str, canonical_url: str, requested_scope: dict[str, Any],
    source_role: str = "", selection_reason: str = "",
) -> dict[str, Any]:
    result = {
        "source_task_id": _task_id(project_id, campaign_id, phase, source_type, target_key),
        "campaign_id": campaign_id,
        "phase": phase,
        "source_type": source_type,
        "target_key": target_key,
        "canonical_url": canonical_url,
        "requested_scope": requested_scope,
        "required": True,
        "initial_state": "queued",
    }
    if source_role:
        result["source_role"] = source_role
    if selection_reason:
        result["selection_reason"] = selection_reason
    return result


def _count_by(tasks: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(task[key]) for task in tasks).items()))


def build_project_dry_run(
    raw_plan: dict[str, Any], *, mode: str, profile_dir: Path, out: Path,
    assets: list[str], resume: bool, package_zip: bool,
) -> dict[str, Any]:
    plan = normalize_project_plan(raw_plan)
    tasks: list[dict[str, Any]] = []
    deep = plan["deep_capture"]
    for campaign in plan["campaigns"]:
        campaign_id = campaign["campaign_id"]
        for actor in campaign["actors"]:
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase="discovery", source_type="profile", target_key=actor["profile_uid"],
                canonical_url=actor["canonical_url"], source_role=actor["role"],
                requested_scope={
                    "pinned_policy": "all_currently_visible_pinned_additional",
                    "recent_non_pinned": campaign["profile_recent_n"],
                    "detail_capture": "list_snapshot_only",
                },
            ))
        for query in campaign["queries"]:
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase="discovery", source_type="search", target_key=query,
                canonical_url=canonical_search_url(query),
                requested_scope={
                    "query": query, "query_kind": "keyword",
                    "first_visible_results": campaign["search_limit"],
                    "detail_capture": "list_snapshot_only",
                },
            ))
        for topic in campaign["topics"]:
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase="discovery", source_type="topic", target_key=topic,
                canonical_url=canonical_search_url(topic, topic=True),
                requested_scope={
                    "query": topic, "query_kind": "topic",
                    "first_visible_results": campaign["search_limit"],
                    "detail_capture": "list_snapshot_only",
                },
            ))
        for supertopic in campaign["supertopics"]:
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase="discovery", source_type="supertopic",
                target_key=f"{supertopic['supertopic_id']}:{supertopic['selected_tab']}",
                canonical_url=supertopic["canonical_url"],
                requested_scope={
                    "supertopic_id": supertopic["supertopic_id"],
                    "selected_tab": supertopic["selected_tab"],
                    "first_visible_results": campaign["search_limit"],
                    "detail_capture": "list_snapshot_only",
                },
            ))
        for hotlist in campaign["hotlists"]:
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase="discovery", source_type="hotlist", target_key=hotlist["category_code"],
                canonical_url=hotlist["canonical_url"],
                requested_scope={
                    "category_code": hotlist["category_code"],
                    "category_name": hotlist["category_name"],
                    "ranked_limit": campaign["hotlist_limit"],
                    "visible_pinned_and_special_rows": "additional",
                },
            ))
        for post in campaign["seed_posts"]:
            phase = "deep_capture" if deep["enabled"] else "discovery"
            tasks.append(_task(
                project_id=plan["project_id"], campaign_id=campaign_id,
                phase=phase, source_type="post", target_key=post["post_id"],
                canonical_url=post["canonical_url"], selection_reason=post["selection_reason"],
                requested_scope={
                    "post_id": post["post_id"],
                    "mode": mode if deep["enabled"] else "posts",
                    "comment_limit": deep["comment_limit_per_post"] if deep["enabled"] else 0,
                    "repost_limit": deep["repost_limit_per_post"] if deep["enabled"] else 0,
                    "include_replies": deep["expand_replies"] if deep["enabled"] else False,
                    "download_assets": deep["download_assets"] if deep["enabled"] else False,
                },
            ))

    deferred = deep["enabled"] and deep["selection_rule"] == "seed_plus_role_posts"
    warnings = [
        "The plan freezes current visible page ranges, not Weibo internal absolute totals.",
        "Login, CAPTCHA, slider and access confirmation require manual user action.",
        "Discovery tasks use list snapshots; only frozen focus posts enter deep interaction capture.",
    ]
    if deferred:
        warnings.append("Additional deep-capture post IDs remain deferred until discovery results are frozen.")
    if deep["enabled"] and (deep["comment_limit_per_post"] == 0 or deep["repost_limit_per_post"] == 0):
        warnings.append("A zero interaction limit means continue until the visible list ends; it does not mean platform absolute full data.")

    return {
        "schema_version": DRY_RUN_SCHEMA_VERSION,
        "operation": "project_dry_run",
        "execution_available": True,
        "execution_scope": "fixed_tasks_only" if deferred else "all_frozen_tasks",
        "project": plan,
        "source_tasks": tasks,
        "task_summary": {
            "fixed_task_count": len(tasks),
            "by_phase": _count_by(tasks, "phase"),
            "by_source_type": _count_by(tasks, "source_type"),
            "deferred_deep_capture": deferred,
            "max_deep_posts_per_campaign": deep["max_deep_posts_per_campaign"] if deep["enabled"] else 0,
        },
        "runtime": {
            "browser_policy": "one_visible_signed_in_chrome_session_for_the_project",
            "profile_dir": str(Path(profile_dir)),
            "out": str(Path(out)),
            "mode": mode,
            "assets": list(assets),
            "resume": bool(resume),
            "zip": bool(package_zip),
        },
        "boundaries": {
            "download_only": True,
            "analysis_generated": False,
            "commercial_effect_inference": False,
            "visible_scope_not_platform_absolute_total": True,
        },
        "warnings": warnings,
    }
