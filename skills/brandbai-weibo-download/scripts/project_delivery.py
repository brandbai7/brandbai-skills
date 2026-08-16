"""Merge Weibo project task caches and build a factual project delivery."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from build_delivery import (
    DeliveryError,
    _interaction_status_rows,
    _load_json,
    _load_jsonl,
    _save_verified,
    _style,
    _write_sheet,
)
from collector_core import atomic_write_json, derived_id, utc_now
from package_delivery import sha256_file
from project_runner import _task_cache_dir, project_state_dir


PROJECT_DELIVERY_SCHEMA = "brandbai.weibo.project-delivery.v1"
ANALYSIS_INPUT_SCHEMA = "brandbai.weibo.analysis-input.v1"
DATASET_IDS = {
    "accounts": "uid",
    "posts": "post_id",
    "comments": "comment_id",
    "reposts": "repost_id",
    "assets": "asset_id",
    "search_snapshots": "search_snapshot_id",
    "hotlist_snapshots": "hotlist_snapshot_id",
}


def _atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    if not values:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            for row in values:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _record_score(row: dict[str, Any]) -> tuple[int, int, int]:
    downloaded = 1 if row.get("status") == "downloaded" else 0
    complete = 1 if str(row.get("completion_state") or row.get("state") or "").startswith("complete") else 0
    richness = sum(1 for value in row.values() if _nonempty(value)) + len(str(row.get("body") or ""))
    return downloaded, complete, richness


def _merge_record(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if _record_score(candidate) > _record_score(current):
        primary, secondary = dict(candidate), current
    else:
        primary, secondary = dict(current), candidate
    for key, value in secondary.items():
        if not _nonempty(primary.get(key)) and _nonempty(value):
            primary[key] = value
    return primary


def _upsert(bucket: dict[str, dict[str, Any]], key: str, row: dict[str, Any]) -> None:
    if not key:
        return
    bucket[key] = _merge_record(bucket[key], row) if key in bucket else dict(row)


def _post_source(
    *, project_id: str, task: dict[str, Any], post_id: str, rank: int,
    captured_at: str, row: dict[str, Any], query: str = "", query_kind: str = "",
) -> dict[str, Any]:
    source_type = str(task.get("source_type") or "")
    relation_id = derived_id(
        "weibo-project-post-source", project_id, task.get("source_task_id"),
        source_type, post_id, rank,
    )
    return {
        "source_relation_id": relation_id,
        "source_task_id": task.get("source_task_id"),
        "campaign_id": task.get("campaign_id"),
        "source_type": source_type,
        "source_role": task.get("source_role", ""),
        "post_id": post_id,
        "surface_profile_uid": task.get("target_key", "") if source_type == "profile" else "",
        "surface_position": rank,
        "surface_is_pinned": bool(row.get("is_pinned")),
        "content_author_uid": row.get("author_uid", ""),
        "content_author_name": row.get("author_name", ""),
        "body_preview": row.get("body_preview") or row.get("body") or "",
        "published_at_text": row.get("published_at_text", ""),
        "query": query,
        "query_kind": query_kind,
        "selection_reason": row.get("selection_reason") or task.get("selection_reason") or source_type,
        "canonical_url": row.get("canonical_url") or task.get("canonical_url") or "",
        "captured_at": captured_at,
    }


def _copy_asset(row: dict[str, Any], *, task_out: Path, out: Path, task_id: str) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if not key.startswith("__")}
    local_file = str(row.get("local_file") or "")
    if row.get("status") != "downloaded" or not local_file:
        return public
    source = (task_out / local_file).resolve()
    try:
        source.relative_to(task_out.resolve())
    except ValueError:
        public.update({"status": "missing_local_file", "local_file": "", "error_reason": "unsafe_local_file"})
        return public
    if not source.is_file():
        public.update({"status": "missing_local_file", "local_file": "", "error_reason": "source_file_missing"})
        return public
    relative = Path(local_file)
    if not relative.parts or relative.parts[0] != "06_微博素材":
        relative = Path("06_微博素材") / str(row.get("post_id") or "unknown") / source.name
    destination = (out / relative).resolve()
    try:
        destination.relative_to(out.resolve())
    except ValueError:
        public.update({"status": "missing_local_file", "local_file": "", "error_reason": "unsafe_delivery_path"})
        return public
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256_file(destination) != sha256_file(source):
        suffix = str(task_id).rsplit(":", 1)[-1][:8]
        destination = destination.with_name(f"{destination.stem}_{suffix}{destination.suffix}")
        relative = destination.relative_to(out)
    if not destination.exists():
        shutil.copy2(source, destination)
    public["local_file"] = relative.as_posix()
    public["bytes"] = destination.stat().st_size
    public["sha256"] = sha256_file(destination)
    return public


def _requested_components(tasks: list[dict[str, Any]]) -> dict[str, bool]:
    post_tasks = [task for task in tasks if task.get("source_type") == "post"]
    return {
        "comments": any((task.get("requested_scope") or {}).get("mode") in {"comments", "all"} for task in post_tasks),
        "reposts": any((task.get("requested_scope") or {}).get("mode") in {"reposts", "all"} for task in post_tasks),
        "assets": any(bool((task.get("requested_scope") or {}).get("download_assets")) for task in post_tasks),
        "search_snapshots": any(task.get("source_type") in {"search", "topic", "supertopic", "hotlist"} for task in tasks),
    }


def merge_project_sources(out_value: str | Path) -> dict[str, Any]:
    """Merge every source-task cache into stable project-level JSONL datasets."""
    out = Path(out_value).expanduser().resolve()
    data = out / "data"
    plan = _load_json(data / "project_plan.json", {})
    manifest = _load_json(data / "project_manifest.json", {})
    tasks = _load_jsonl(data / "source_tasks.jsonl")
    if not plan or not tasks:
        raise DeliveryError("Project plan or source task records are missing")
    state = project_state_dir(out)
    if not state.is_dir():
        raise DeliveryError("Project resume state was not found")

    buckets: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in DATASET_IDS}
    relations: dict[str, dict[str, Any]] = {}
    project_id = str(plan.get("project_id") or "")
    for task in tasks:
        task_id = str(task.get("source_task_id") or "")
        task_out = _task_cache_dir(state, task_id)
        task_data = task_out / "data"
        for dataset, id_field in DATASET_IDS.items():
            for row in _load_jsonl(task_data / f"{dataset}.jsonl"):
                value = dict(row)
                if dataset == "assets":
                    value["__task_out"] = str(task_out)
                    value["__source_task_id"] = task_id
                _upsert(buckets[dataset], str(row.get(id_field) or ""), value)

        if task.get("source_type") == "profile":
            selection = _load_json(task_data / "profile_selection.json", {})
            captured_at = str(selection.get("captured_at") or selection.get("finished_at") or "")
            for position, row in enumerate(selection.get("selected") or [], start=1):
                post_id = str(row.get("post_id") or "")
                if not post_id:
                    continue
                relation = _post_source(
                    project_id=project_id, task=task, post_id=post_id,
                    rank=int(row.get("rank") or position), captured_at=captured_at, row=row,
                )
                relations[relation["source_relation_id"]] = relation
        elif task.get("source_type") in {"search", "topic", "supertopic"}:
            for snapshot in _load_jsonl(task_data / "search_snapshots.jsonl"):
                for position, row in enumerate(snapshot.get("results") or [], start=1):
                    post_id = str(row.get("post_id") or "")
                    if not post_id:
                        continue
                    relation = _post_source(
                        project_id=project_id, task=task, post_id=post_id,
                        rank=int(row.get("rank") or position),
                        captured_at=str(snapshot.get("captured_at") or ""), row=row,
                        query=str(snapshot.get("query") or ""),
                        query_kind=str(snapshot.get("query_kind") or ""),
                    )
                    relations[relation["source_relation_id"]] = relation
        elif task.get("source_type") == "post":
            post_id = str((task.get("requested_scope") or {}).get("post_id") or task.get("target_key") or "")
            post = buckets["posts"].get(post_id, {})
            relation = _post_source(
                project_id=project_id, task=task, post_id=post_id, rank=0,
                captured_at=str(post.get("collected_at") or task.get("finished_at") or ""), row=post,
            )
            relations[relation["source_relation_id"]] = relation

    merged: dict[str, list[dict[str, Any]]] = {}
    for dataset, id_field in DATASET_IDS.items():
        values = sorted(buckets[dataset].values(), key=lambda row: str(row.get(id_field) or ""))
        if dataset == "assets":
            values = [
                _copy_asset(
                    row, task_out=Path(str(row.get("__task_out") or state)), out=out,
                    task_id=str(row.get("__source_task_id") or ""),
                )
                for row in values
            ]
        else:
            values = [{key: value for key, value in row.items() if not key.startswith("__")} for row in values]
        merged[dataset] = values
        _atomic_write_jsonl(data / f"{dataset}.jsonl", values)

    post_sources = sorted(
        relations.values(),
        key=lambda row: (
            str(row.get("campaign_id") or ""), str(row.get("source_type") or ""),
            int(row.get("surface_position") or 0), str(row.get("post_id") or ""),
        ),
    )
    _atomic_write_jsonl(data / "post_sources.jsonl", post_sources)

    requested = _requested_components(tasks)
    downloaded_assets = sum(1 for row in merged["assets"] if row.get("status") == "downloaded")
    structurally_ready = bool(merged["posts"] and post_sources)
    missing: list[str] = []
    if not merged["posts"]:
        missing.append("detailed_posts")
    if not post_sources:
        missing.append("source_relations")
    counts = {name: len(rows) for name, rows in merged.items()}
    counts["post_sources"] = len(post_sources)
    counts["downloaded_assets"] = downloaded_assets
    manifest.update({
        "merged_delivery_available": True,
        "merged_at": utc_now(),
        "component_counts": counts,
        "requested_components": requested,
        "usable_for_handoff": structurally_ready,
        "missing_required_components": missing,
    })
    atomic_write_json(data / "project_manifest.json", manifest)
    post_states = {str(row.get("post_id") or ""): row.get("completion_state", "unknown") for row in merged["posts"]}
    comment_states: dict[str, Any] = {}
    repost_states: dict[str, Any] = {}
    for task in tasks:
        if task.get("source_type") != "post":
            continue
        summary = task.get("result_summary") or {}
        post_id = str(summary.get("post_id") or (task.get("requested_scope") or {}).get("post_id") or task.get("target_key") or "")
        if post_id and summary.get("comment_state"):
            comment_states[post_id] = summary["comment_state"]
        if post_id and summary.get("repost_state"):
            repost_states[post_id] = summary["repost_state"]
    atomic_write_json(data / "run_manifest.json", {
        "schema_version": "1.0",
        "collector": "brandbai-weibo-download",
        "collector_version": manifest.get("collector_version", "0.1.2-project-experimental"),
        "project_id": project_id,
        "state": manifest.get("state", "unknown"),
        "post_states": post_states,
        "comment_states": comment_states,
        "repost_states": repost_states,
        "finished_at": manifest.get("finished_at", ""),
    })
    return {"counts": counts, "requested_components": requested, "project_manifest": manifest}


def _task_component_states(tasks: list[dict[str, Any]], component: str) -> dict[str, Any]:
    key = f"{component[:-1]}_state"
    states: dict[str, Any] = {}
    for task in tasks:
        if task.get("source_type") != "post":
            continue
        summary = task.get("result_summary") or {}
        post_id = str(summary.get("post_id") or (task.get("requested_scope") or {}).get("post_id") or task.get("target_key") or "")
        if post_id and summary.get(key):
            states[post_id] = summary[key]
    return states


def _new_book() -> Any:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise DeliveryError("openpyxl is missing") from exc
    workbook = Workbook()
    workbook.remove(workbook.active)
    return workbook


def _save_book(workbook: Any, path: Path) -> None:
    _style(workbook)
    if "项目总览" in workbook.sheetnames:
        workbook["项目总览"].column_dimensions["A"].width = 30
        workbook["项目总览"].column_dimensions["B"].width = 64
    _save_verified(workbook, path)


def _campaign_maps(plan: dict[str, Any]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    names: dict[str, str] = {}
    roles: dict[tuple[str, str], str] = {}
    for campaign in plan.get("campaigns") or []:
        campaign_id = str(campaign.get("campaign_id") or "")
        names[campaign_id] = str(campaign.get("campaign_name") or campaign_id)
        for actor in campaign.get("actors") or []:
            roles[(campaign_id, str(actor.get("profile_uid") or ""))] = str(actor.get("role") or "")
    return names, roles


def build_project_delivery(out_value: str | Path) -> dict[str, Any]:
    """Build project workbooks and a factual downstream-analysis handoff manifest."""
    out = Path(out_value).expanduser().resolve()
    data = out / "data"
    plan = _load_json(data / "project_plan.json", {})
    manifest = _load_json(data / "project_manifest.json", {})
    tasks = _load_jsonl(data / "source_tasks.jsonl")
    accounts = _load_jsonl(data / "accounts.jsonl")
    posts = _load_jsonl(data / "posts.jsonl")
    comments = _load_jsonl(data / "comments.jsonl")
    reposts = _load_jsonl(data / "reposts.jsonl")
    assets = _load_jsonl(data / "assets.jsonl")
    searches = _load_jsonl(data / "search_snapshots.jsonl")
    hotlists = _load_jsonl(data / "hotlist_snapshots.jsonl")
    sources = _load_jsonl(data / "post_sources.jsonl")
    if not plan or not tasks:
        raise DeliveryError("Merged project data was not found")
    requested = dict(manifest.get("requested_components") or _requested_components(tasks))
    campaign_names, actor_roles = _campaign_maps(plan)
    account_by_uid = {str(row.get("uid") or ""): row for row in accounts}

    overview = _new_book()
    _write_sheet(overview, "项目总览", ["项目字段", "项目值"], [
        ["项目ID", plan.get("project_id")],
        ["项目名称", plan.get("project_name")],
        ["项目模板", plan.get("preset")],
        ["采集深度", plan.get("capture_depth")],
        ["时间窗口开始", (plan.get("time_window") or {}).get("start")],
        ["时间窗口结束", (plan.get("time_window") or {}).get("end")],
        ["项目状态", manifest.get("state")],
        ["任务总数", manifest.get("source_task_total", len(tasks))],
        ["账号记录", len(accounts)], ["微博详情", len(posts)], ["可见来源关系", len(sources)],
        ["评论与回复", len(comments)], ["转发记录", len(reposts)],
        ["搜索/话题快照", len(searches)], ["热搜快照", len(hotlists)],
        ["已下载素材", sum(1 for row in assets if row.get("status") == "downloaded")],
        ["结构化分析交接就绪", manifest.get("usable_for_handoff", False)],
        ["可断点续跑", manifest.get("resume_available", False)],
    ])
    campaign_rows = []
    for campaign in plan.get("campaigns") or []:
        campaign_id = str(campaign.get("campaign_id") or "")
        for actor in campaign.get("actors") or []:
            uid = str(actor.get("profile_uid") or "")
            campaign_rows.append([
                campaign_id, campaign.get("campaign_name"), actor.get("role"), uid,
                (account_by_uid.get(uid) or {}).get("display_name") or actor.get("display_name"),
                actor.get("canonical_url"), campaign.get("queries"), campaign.get("topics"),
                [item.get("supertopic_id") for item in campaign.get("supertopics") or []],
                [item.get("category_name") for item in campaign.get("hotlists") or []],
                [item.get("post_id") for item in campaign.get("seed_posts") or []],
            ])
    _write_sheet(overview, "官宣分组", [
        "官宣组ID", "官宣组名称", "主体角色", "账号UID", "账号名称", "主页链接",
        "搜索词", "话题", "超话ID", "热搜榜单", "种子微博ID",
    ], campaign_rows)
    _write_sheet(overview, "任务状态", [
        "来源任务ID", "官宣组ID", "阶段", "来源类型", "主体角色", "目标", "请求范围",
        "状态", "尝试次数", "结果摘要", "错误类型", "错误说明", "可续跑",
    ], [[
        task.get("source_task_id"), task.get("campaign_id"), task.get("phase"), task.get("source_type"),
        task.get("source_role"), task.get("target_key"), task.get("requested_scope"), task.get("state"),
        task.get("attempts"), task.get("result_summary"), task.get("error_type"), task.get("error_message"),
        task.get("resume_available"),
    ] for task in tasks])
    completeness = [
        ["账号", True, len(accounts), "以来源任务状态和页面可见范围为准"],
        ["微博详情", True, len(posts), "只有进入详情采集的微博才有完整正文与互动快照"],
        ["可见内容池", True, len(sources), "同一微博可保留多条主页/搜索/话题来源关系"],
        ["评论与回复", requested.get("comments", False), len(comments), "全部仅指页面当前可返回范围"],
        ["转发扩散", requested.get("reposts", False), len(reposts), "全部仅指页面当前可返回范围"],
        ["素材", requested.get("assets", False), sum(1 for row in assets if row.get("status") == "downloaded"), "只保存页面观察到且明确请求的素材"],
        ["搜索与话题快照", requested.get("search_snapshots", False), len(searches) + len(hotlists), "仅代表采集时点指定入口的可见快照"],
    ]
    _write_sheet(overview, "完成性", ["组件", "是否请求", "保存记录", "边界说明"], completeness)
    _save_book(overview, out / "00_项目采集总览.xlsx")

    accounts_book = _new_book()
    if accounts:
        _write_sheet(accounts_book, "账号总览", [
            "账号UID", "账号名称", "认证原文", "简介", "关注原文", "粉丝原文", "微博数原文",
            "规范链接", "采集时间", "完成状态",
        ], [[
            row.get("uid"), row.get("display_name"), row.get("verification_text"), row.get("description"),
            row.get("following_text"), row.get("followers_text"), row.get("posts_text"), row.get("canonical_url"),
            row.get("collected_at"), row.get("completion_state"),
        ] for row in accounts])
    actor_rows = []
    for campaign in plan.get("campaigns") or []:
        campaign_id = str(campaign.get("campaign_id") or "")
        for actor in campaign.get("actors") or []:
            uid = str(actor.get("profile_uid") or "")
            actor_rows.append([
                campaign_id, campaign_names.get(campaign_id), actor.get("actor_id"), actor.get("role"), uid,
                (account_by_uid.get(uid) or {}).get("display_name") or actor.get("display_name"), actor.get("canonical_url"),
            ])
    _write_sheet(accounts_book, "主体映射", ["官宣组ID", "官宣组名称", "主体ID", "主体角色", "账号UID", "账号名称", "主页链接"], actor_rows)
    profile_sources = [row for row in sources if row.get("source_type") == "profile"]
    if profile_sources:
        _write_sheet(accounts_book, "主页来源", [
            "来源关系ID", "官宣组ID", "主体角色", "主页UID", "主页位次", "是否置顶", "微博ID",
            "作者UID", "页面摘要", "发布时间原文", "选择原因", "规范链接", "采集时间",
        ], [[
            row.get("source_relation_id"), row.get("campaign_id"), row.get("source_role"), row.get("surface_profile_uid"),
            row.get("surface_position"), row.get("surface_is_pinned"), row.get("post_id"), row.get("content_author_uid"),
            row.get("body_preview"), row.get("published_at_text"), row.get("selection_reason"), row.get("canonical_url"), row.get("captured_at"),
        ] for row in profile_sources])
    _save_book(accounts_book, out / "01_账号资料.xlsx")

    posts_book = _new_book()
    if posts:
        _write_sheet(posts_book, "微博详情", [
            "微博ID", "账号UID", "作者", "正文", "类型", "发布时间原文", "地区原文", "来源原文", "可见范围",
            "浏览", "转发", "评论", "点赞", "原微博ID", "原作者UID", "规范链接", "采集时间", "完成状态",
        ], [[
            row.get("post_id"), row.get("author_uid"), row.get("author_name"), row.get("body"), row.get("post_type"),
            row.get("published_at_text"), row.get("region_text"), row.get("source_text"), row.get("visibility_text"),
            (row.get("metrics") or {}).get("views"), (row.get("metrics") or {}).get("reposts"),
            (row.get("metrics") or {}).get("comments"), (row.get("metrics") or {}).get("likes"),
            row.get("original_post_id"), row.get("original_author_uid"), row.get("canonical_url"),
            row.get("collected_at"), row.get("completion_state"),
        ] for row in posts])
    _write_sheet(posts_book, "可见内容池", [
        "来源关系ID", "官宣组ID", "官宣组名称", "来源类型", "主体角色", "来源位次", "是否置顶",
        "微博ID", "作者UID", "作者", "页面摘要", "发布时间原文", "查询类型", "查询词", "选择原因", "规范链接", "采集时间",
    ], [[
        row.get("source_relation_id"), row.get("campaign_id"), campaign_names.get(str(row.get("campaign_id") or "")),
        row.get("source_type"), row.get("source_role"), row.get("surface_position"), row.get("surface_is_pinned"),
        row.get("post_id"), row.get("content_author_uid"), row.get("content_author_name"), row.get("body_preview"),
        row.get("published_at_text"), row.get("query_kind"), row.get("query"), row.get("selection_reason"),
        row.get("canonical_url"), row.get("captured_at"),
    ] for row in sources])
    _write_sheet(posts_book, "来源关系", [
        "来源关系ID", "来源任务ID", "官宣组ID", "来源类型", "来源角色", "微博ID", "来源UID",
        "来源位次", "是否置顶", "查询类型", "查询词", "选择原因", "规范链接", "采集时间",
    ], [[
        row.get("source_relation_id"), row.get("source_task_id"), row.get("campaign_id"), row.get("source_type"),
        row.get("source_role"), row.get("post_id"), row.get("surface_profile_uid"), row.get("surface_position"),
        row.get("surface_is_pinned"), row.get("query_kind"), row.get("query"), row.get("selection_reason"),
        row.get("canonical_url"), row.get("captured_at"),
    ] for row in sources])
    topic_rows = []
    for post in posts:
        for order, topic in enumerate(post.get("topics") or [], start=1):
            topic_rows.append([post.get("post_id"), "topic", order, topic])
        for order, mention in enumerate(post.get("mentions") or [], start=1):
            topic_rows.append([post.get("post_id"), "mention", order, mention])
    if topic_rows:
        _write_sheet(posts_book, "话题与提及", ["微博ID", "类型", "顺序", "原文"], topic_rows)
    if assets:
        _write_sheet(posts_book, "素材索引", [
            "素材ID", "微博ID", "类型", "顺序", "是否请求", "状态", "交付文件", "来源URL", "宽", "高", "字节数", "SHA256", "失败原因",
        ], [[
            row.get("asset_id"), row.get("post_id"), row.get("kind"), row.get("order"), row.get("requested"),
            row.get("status"), row.get("local_file"), row.get("source_url"), row.get("width"), row.get("height"),
            row.get("bytes"), row.get("sha256"), row.get("error_reason"),
        ] for row in assets])
    if posts:
        _write_sheet(posts_book, "完整性", ["微博ID", "状态", "说明", "采集时间"], [[
            row.get("post_id"), row.get("completion_state"), row.get("completion_note"), row.get("collected_at")
        ] for row in posts])
    _save_book(posts_book, out / "02_微博清单.xlsx")

    generated = ["00_项目采集总览.xlsx", "01_账号资料.xlsx", "02_微博清单.xlsx"]
    comment_states = _task_component_states(tasks, "comments")
    comment_path = out / "03_评论明细.xlsx"
    if requested.get("comments") or comments:
        comment_book = _new_book()
        _write_sheet(comment_book, "评论明细", [
            "评论ID", "ID类型", "微博ID", "父评论ID", "根评论ID", "层级", "匿名作者ID", "作者显示名", "评论原文",
            "时间原文", "地区原文", "点赞原文", "声明回复数", "已保存回复数", "回复展开状态", "采集时间",
        ], [[
            row.get("comment_id"), row.get("comment_id_type"), row.get("post_id"), row.get("parent_comment_id"),
            row.get("root_comment_id"), row.get("level"), row.get("author_id"), row.get("author_display"), row.get("content"),
            row.get("time_text"), row.get("region_text"), row.get("like_count_text"), row.get("declared_reply_count"),
            row.get("saved_reply_count"), row.get("reply_expansion_status"), row.get("collected_at"),
        ] for row in comments])
        _write_sheet(comment_book, "采集状态", ["微博ID", "保存一级评论", "保存回复", "完成状态"],
                     _interaction_status_rows(comments, "post_id", "level", comment_states))
        _save_book(comment_book, comment_path)
        generated.append(comment_path.name)
    else:
        comment_path.unlink(missing_ok=True)

    repost_states = _task_component_states(tasks, "reposts")
    repost_path = out / "04_转发扩散.xlsx"
    if requested.get("reposts") or reposts:
        repost_book = _new_book()
        _write_sheet(repost_book, "转发明细", [
            "转发ID", "ID类型", "源微博ID", "上游转发ID", "匿名作者ID", "作者显示名", "转发文案", "时间原文",
            "地区原文", "互动快照", "传播链状态", "采集时间",
        ], [[
            row.get("repost_id"), row.get("repost_id_type"), row.get("source_post_id"), row.get("upstream_repost_id"),
            row.get("author_id"), row.get("author_display"), row.get("content"), row.get("time_text"), row.get("region_text"),
            row.get("metrics"), row.get("chain_status"), row.get("collected_at"),
        ] for row in reposts])
        per_post = Counter(str(row.get("source_post_id") or "") for row in reposts)
        ids = sorted(set(per_post) | set(repost_states))
        _write_sheet(repost_book, "采集状态", ["微博ID", "保存转发记录", "完成状态"], [[
            post_id, per_post.get(post_id, 0), repost_states.get(post_id, "unknown")
        ] for post_id in ids])
        _save_book(repost_book, repost_path)
        generated.append(repost_path.name)
    else:
        repost_path.unlink(missing_ok=True)

    snapshot_path = out / "05_搜索与话题快照.xlsx"
    if searches or hotlists:
        snapshot_book = _new_book()
        result_rows, context_rows, supertopic_rows, hotlist_rows = [], [], [], []
        for snapshot in searches:
            for result in snapshot.get("results") or []:
                result_rows.append([
                    snapshot.get("search_snapshot_id"), snapshot.get("query_kind"), snapshot.get("query"), snapshot.get("sort"),
                    snapshot.get("filters"), result.get("rank"), result.get("post_id"), result.get("author_uid"),
                    result.get("author_name"), result.get("body_preview"), result.get("promoted_state"), result.get("canonical_url"),
                    snapshot.get("captured_at"), snapshot.get("state"),
                ])
            context = snapshot.get("topic_context") or {}
            if context or snapshot.get("query_kind") == "topic":
                context_rows.append([
                    snapshot.get("search_snapshot_id"), snapshot.get("query"), context.get("read_text"),
                    context.get("discuss_text"), context.get("host_text"), snapshot.get("captured_at"),
                ])
            supertopic = snapshot.get("supertopic_context") or {}
            if supertopic or snapshot.get("query_kind") == "supertopic":
                supertopic_rows.append([
                    snapshot.get("search_snapshot_id"), supertopic.get("supertopic_id"), supertopic.get("name"),
                    supertopic.get("canonical_url"), supertopic.get("category_text"), supertopic.get("post_count_text"),
                    supertopic.get("member_count_text"), supertopic.get("member_label_text"), supertopic.get("checkin_text"),
                    supertopic.get("rank_text"), supertopic.get("visible_tabs"), supertopic.get("selected_tab") or snapshot.get("sort"),
                    snapshot.get("captured_at"), snapshot.get("state"),
                ])
        for snapshot in hotlists:
            for entry in snapshot.get("entries") or []:
                hotlist_rows.append([
                    snapshot.get("hotlist_snapshot_id"), snapshot.get("category_code"), snapshot.get("category_name"),
                    entry.get("observed_position"), entry.get("rank_text"), entry.get("rank_numeric"), entry.get("keyword"),
                    entry.get("heat_text"), entry.get("topic_category_text"), entry.get("label_text"), entry.get("is_pinned"),
                    entry.get("is_special"), entry.get("query_url"), snapshot.get("captured_at"), snapshot.get("state"),
                ])
        _write_sheet(snapshot_book, "快照状态", [
            "快照ID", "快照类型", "查询或榜单", "保存可见记录", "采集时间", "范围状态",
        ], [[
            snapshot.get("search_snapshot_id"), snapshot.get("query_kind"), snapshot.get("query"),
            len(snapshot.get("results") or []), snapshot.get("captured_at"), snapshot.get("state"),
        ] for snapshot in searches] + [[
            snapshot.get("hotlist_snapshot_id"), "hotlist", snapshot.get("category_name") or snapshot.get("category_code"),
            len(snapshot.get("entries") or []), snapshot.get("captured_at"), snapshot.get("state"),
        ] for snapshot in hotlists])
        if result_rows:
            _write_sheet(snapshot_book, "结果位次", [
                "搜索快照ID", "查询类型", "查询词", "排序", "筛选", "位次", "微博ID", "账号UID", "作者", "摘要",
                "推广标记", "规范链接", "采集时间", "范围状态",
            ], result_rows)
        if context_rows:
            _write_sheet(snapshot_book, "话题上下文", ["搜索快照ID", "话题", "阅读原文", "讨论原文", "主持原文", "采集时间"], context_rows)
        if supertopic_rows:
            _write_sheet(snapshot_book, "超话资料", [
                "搜索快照ID", "超话ID", "超话名称", "规范链接", "分类原文", "帖子数原文", "成员数原文",
                "成员称呼原文", "今日签到原文", "排行原文", "页面可见分区", "采集分区", "采集时间", "范围状态",
            ], supertopic_rows)
        if hotlist_rows:
            _write_sheet(snapshot_book, "热搜榜单", [
                "榜单快照ID", "榜单代码", "榜单名称", "页面可见顺序", "排名原文", "数字排名", "词条",
                "热度原文", "词条分类原文", "榜单标签", "是否置顶", "是否特殊行", "词条搜索链接", "采集时间", "范围状态",
            ], hotlist_rows)
        _save_book(snapshot_book, snapshot_path)
        generated.append(snapshot_path.name)
    else:
        snapshot_path.unlink(missing_ok=True)

    material_dir = out / "06_微博素材"
    downloaded_assets = [row for row in assets if row.get("status") == "downloaded" and row.get("local_file")]
    if downloaded_assets:
        generated.append(material_dir.name)
    elif material_dir.is_dir() and not any(material_dir.rglob("*")):
        material_dir.rmdir()

    description = f"""# BrandBAI 微博项目采集说明

## 项目与交付

- 项目：{plan.get('project_name', '')}（{plan.get('project_id', '')}）
- 官宣分组：{len(plan.get('campaigns') or [])}
- 来源任务：{len(tasks)}；项目状态：{manifest.get('state', 'unknown')}
- 账号记录：{len(accounts)}；微博详情：{len(posts)}；可见来源关系：{len(sources)}
- 评论与回复：{len(comments)}；转发记录：{len(reposts)}
- 搜索/话题/超话快照：{len(searches)}；热搜快照：{len(hotlists)}
- 已下载素材：{len(downloaded_assets)}
- 构建时间：{utc_now()}

## 文件怎么读

1. `00_项目采集总览.xlsx` 先看项目范围、官宣分组、任务状态与完成性。
2. `01_账号资料.xlsx` 保存账号事实与明星、品牌等主体角色映射。
3. `02_微博清单.xlsx` 中“微博详情”是进入详情页采集的数据，“可见内容池”保留主页、搜索、话题等入口观察到的内容和位次；同一微博可有多条来源关系。
4. 评论、转发和搜索快照文件只在对应能力已请求或实际有记录时生成。
5. `handoff/analysis_input_manifest.json` 只说明数据结构是否可交给后续分析，不代表样本量足够，也不自动生成口碑、舆情、代言匹配或商业归因结论。

## 重要边界

1. “全部”只表示采集时页面当前可返回范围，不代表微博平台内部绝对全量。
2. 主页置顶为采集时点额外可见项，不占最近 N 条非置顶名额；搜索、话题、超话与热搜仅是指定入口、排序、筛选和时点快照。
3. 评论回复或转发传播链未完全展开时，完成状态必须保留为部分完成；记录数为 0 不等于平台没有记录。
4. 本包只做下载、结构化、去重、来源保留和质量说明；微博中的身份、关系、购买、效果与体验主张未经本阶段核验。
5. 登录资料、Cookie、验证码、手机号、请求头和带鉴权参数的媒体地址不进入交付包；隐藏断点缓存也不进入 ZIP。
"""
    (out / "07_采集说明.md").write_text(description, encoding="utf-8")
    generated.append("07_采集说明.md")

    structurally_ready = bool(posts and sources)
    limitations = [
        "结构就绪不等于样本充分，分析阶段仍需按问题核查覆盖范围与可比性。",
        "主页、搜索、话题、超话与热搜均为采集时点页面可见快照。",
    ]
    if manifest.get("state") != "complete":
        limitations.append(f"项目状态为 {manifest.get('state', 'unknown')}，应先查看任务状态和完成性。")
    if manifest.get("deferred_deep_capture"):
        limitations.append("仍有发现后深采目标待冻结，当前详情样本不是最终深采集合。")
    handoff = {
        "schema_version": ANALYSIS_INPUT_SCHEMA,
        "project_id": plan.get("project_id"),
        "project_name": plan.get("project_name"),
        "structurally_ready_for_analysis": structurally_ready,
        "analysis_sufficiency_assessed": False,
        "download_only_source": True,
        "analysis_generated": False,
        "dataset_files": {
            "accounts": "data/accounts.jsonl" if accounts else "",
            "posts": "data/posts.jsonl" if posts else "",
            "post_sources": "data/post_sources.jsonl" if sources else "",
            "comments": "data/comments.jsonl" if comments else "",
            "reposts": "data/reposts.jsonl" if reposts else "",
            "search_snapshots": "data/search_snapshots.jsonl" if searches else "",
            "hotlist_snapshots": "data/hotlist_snapshots.jsonl" if hotlists else "",
        },
        "counts": dict(manifest.get("component_counts") or {}),
        "project_state": manifest.get("state", "unknown"),
        "limitations": limitations,
        "built_at": utc_now(),
    }
    handoff_dir = out / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(handoff_dir / "analysis_input_manifest.json", handoff)
    generated.append("handoff/analysis_input_manifest.json")

    summary = {
        "schema_version": PROJECT_DELIVERY_SCHEMA,
        "project_id": plan.get("project_id"),
        "project_state": manifest.get("state", "unknown"),
        "built_at": utc_now(),
        "generated_files": generated,
        "counts": dict(manifest.get("component_counts") or {}),
        "structurally_ready_for_analysis": structurally_ready,
        "analysis_generated": False,
    }
    atomic_write_json(data / "delivery_manifest.json", summary)
    return summary


def finalize_project_delivery(out_value: str | Path) -> dict[str, Any]:
    merge = merge_project_sources(out_value)
    delivery = build_project_delivery(out_value)
    out = Path(out_value).expanduser().resolve()
    manifest = _load_json(out / "data" / "project_manifest.json", {})
    manifest.update({
        "delivery_built_at": delivery.get("built_at", ""),
        "delivery_generated_files": list(delivery.get("generated_files") or []),
    })
    atomic_write_json(out / "data" / "project_manifest.json", manifest)
    merge["project_manifest"] = manifest
    return {"merge": merge, "delivery": delivery}
