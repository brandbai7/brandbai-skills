"""Single-session task runner for BrandBAI Weibo project plans."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from browser_collect_weibo import (
    _collect_hotlist_snapshot,
    _collect_one_post,
    _discover_profile_posts,
    _discover_search_results,
    _discover_supertopic_results,
    _public_hotlist_snapshot,
    _public_profile_selection,
    _public_search_snapshot,
    find_chrome_executable,
)
from collector_core import CollectionError, atomic_write_json, utc_now
from project_plan import build_project_dry_run


PROJECT_MANIFEST_SCHEMA = "brandbai.weibo.project-manifest.v1"
TASK_STATES = {"queued", "running", "complete", "partial", "blocked", "failed"}


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _task_cache_dir(state_dir: Path, task_id: str) -> Path:
    digest = str(task_id).rsplit(":", 1)[-1]
    if not digest or not all(character in "0123456789abcdef" for character in digest.lower()):
        raise CollectionError("Project task ID is not safe for a cache directory")
    return state_dir / "source_tasks" / digest


def project_state_dir(out_value: str | Path) -> Path:
    """Return the private sibling directory used for resumable project task caches."""
    out = Path(out_value).expanduser().resolve()
    return out.parent / f".{out.name}.weibo-project-state"


def _public_task_record(record: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_task_id", "campaign_id", "phase", "source_type", "target_key",
        "canonical_url", "requested_scope", "required", "source_role",
        "selection_reason", "state", "attempts", "started_at", "finished_at",
        "result_summary", "error_type", "error_message", "resume_available",
    }
    return {key: value for key, value in record.items() if key in allowed}


def _project_plan_sha256(plan: dict[str, Any]) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _redact_runtime_paths(message: str, paths: list[Path]) -> str:
    redacted = str(message or "")
    for path in sorted({str(item) for item in paths if item}, key=len, reverse=True):
        redacted = redacted.replace(path, "<local-path>")
        redacted = redacted.replace(path.replace("\\", "/"), "<local-path>")
    return redacted[:500]


def _project_state(records: list[dict[str, Any]], *, deferred: bool) -> str:
    required = [record for record in records if record.get("required", True)]
    states = [str(record.get("state") or "queued") for record in required]
    if states and all(state == "complete" for state in states) and not deferred:
        return "complete"
    if states and all(state in {"queued", "blocked"} for state in states) and "blocked" in states:
        return "blocked"
    if states and all(state == "failed" for state in states):
        return "failed"
    return "partial"


def _project_manifest(
    dry_run: dict[str, Any], records: list[dict[str, Any]], *, started_at: str,
    finished_at: str = "",
) -> dict[str, Any]:
    deferred = bool(dry_run["task_summary"].get("deferred_deep_capture"))
    state = _project_state(records, deferred=deferred)
    counts = dict(sorted(Counter(str(record.get("state") or "queued") for record in records).items()))
    return {
        "schema_version": PROJECT_MANIFEST_SCHEMA,
        "collector": "brandbai-weibo-download",
        "collector_version": "0.1.2-project-experimental",
        "project_id": dry_run["project"]["project_id"],
        "project_name": dry_run["project"]["project_name"],
        "project_plan_sha256": _project_plan_sha256(dry_run["project"]),
        "preset": dry_run["project"]["preset"],
        "capture_depth": dry_run["project"]["capture_depth"],
        "state": state,
        "source_task_counts": counts,
        "source_task_total": len(records),
        "fixed_tasks_complete": bool(records) and all(record.get("state") == "complete" for record in records),
        "deferred_deep_capture": deferred,
        "usable_for_handoff": False,
        "missing_required_components": ["project_merged_delivery"],
        "resume_available": deferred or any(record.get("state") != "complete" for record in records),
        "browser_policy": "one_visible_signed_in_chrome_session_for_the_project",
        "download_only": True,
        "analysis_generated": False,
        "started_at": started_at,
        "finished_at": finished_at,
    }


@contextmanager
def visible_chrome_session(
    *, profile_dir: Path, chrome_path: str | None = None,
) -> Iterator[tuple[Any, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt first") from exc
    executable = find_chrome_executable(chrome_path)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir.resolve()), executable_path=executable, headless=False,
            viewport=None, args=["--start-maximized"], accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield context, page
        finally:
            context.close()


def _write_task_manifest(task_out: Path, task: dict[str, Any], result: dict[str, Any]) -> None:
    atomic_write_json(task_out / "data" / "run_manifest.json", {
        "schema_version": "1.0",
        "collector": "brandbai-weibo-download",
        "collector_version": "0.1.2-project-experimental",
        "source_task_id": task["source_task_id"],
        "campaign_id": task["campaign_id"],
        "target_kind": task["source_type"],
        "state": result["state"],
        "result_summary": result,
        "finished_at": utc_now(),
    })


def _component_fulfills_requested_scope(
    result: dict[str, Any], *, requested_limit: int, saved_key: str,
) -> bool:
    state = str(result.get("state") or "")
    if state.startswith("complete"):
        return True
    if state != "partial_limit_sample" or requested_limit <= 0:
        return False
    return int(result.get(saved_key) or 0) >= requested_limit


def execute_browser_source_task(
    task: dict[str, Any], *, task_out: Path, context: Any, page: Any,
    assets: list[str], max_profile_scroll_actions: int,
    max_search_scroll_actions: int, max_scroll_actions: int,
    login_wait: int, retain_author_display: bool, max_asset_mb: int,
    resume: bool,
) -> dict[str, Any]:
    """Execute one frozen source task using an already-open browser context."""
    task_out.mkdir(parents=True, exist_ok=True)
    data = task_out / "data"
    data.mkdir(parents=True, exist_ok=True)
    source_type = str(task["source_type"])
    scope = dict(task.get("requested_scope") or {})

    if source_type == "profile":
        selection = _discover_profile_posts(
            page, task["canonical_url"],
            recent=max(0, int(scope.get("recent_non_pinned") or 0)),
            max_scroll_actions=max(0, max_profile_scroll_actions),
            login_wait=max(0, login_wait),
        )
        public = _public_profile_selection(selection)
        atomic_write_json(data / "profile_selection.json", public)
        _atomic_write_jsonl(data / "accounts.jsonl", [selection["account"]])
        result = {
            "state": selection["state"],
            "saved_accounts": 1,
            "saved_visible_post_refs": len(selection.get("selected") or []),
        }
    elif source_type in {"search", "topic"}:
        query_kind = "topic" if source_type == "topic" else "keyword"
        snapshot = _discover_search_results(
            page, str(scope.get("query") or task["target_key"]),
            query_kind=query_kind,
            limit=max(1, int(scope.get("first_visible_results") or 1)),
            max_scroll_actions=max(0, max_search_scroll_actions),
            login_wait=max(0, login_wait),
        )
        _atomic_write_jsonl(data / "search_snapshots.jsonl", [_public_search_snapshot(snapshot)])
        result = {"state": snapshot["state"], "saved_visible_post_refs": snapshot["saved"]}
    elif source_type == "supertopic":
        snapshot = _discover_supertopic_results(
            page, task["canonical_url"],
            tab=str(scope.get("selected_tab") or "热门"),
            limit=max(1, int(scope.get("first_visible_results") or 1)),
            max_scroll_actions=max(0, max_search_scroll_actions),
            login_wait=max(0, login_wait),
        )
        _atomic_write_jsonl(data / "search_snapshots.jsonl", [_public_search_snapshot(snapshot)])
        result = {"state": snapshot["state"], "saved_visible_post_refs": snapshot["saved"]}
    elif source_type == "hotlist":
        snapshot = _collect_hotlist_snapshot(
            page, str(scope.get("category_code") or task["target_key"]),
            ranked_limit=max(1, int(scope.get("ranked_limit") or 1)),
            login_wait=max(0, login_wait),
        )
        _atomic_write_jsonl(data / "hotlist_snapshots.jsonl", [_public_hotlist_snapshot(snapshot)])
        result = {
            "state": snapshot["state"],
            "saved_ranked": snapshot["saved_ranked"],
            "saved_extras": snapshot["saved_extras"],
        }
    elif source_type == "post":
        requested_assets = assets if bool(scope.get("download_assets")) else []
        post, comments, reposts = _collect_one_post(
            page, context, task["canonical_url"], task_out,
            mode=str(scope.get("mode") or "posts"),
            assets=requested_assets,
            comment_limit=max(0, int(scope.get("comment_limit") or 0)),
            repost_limit=max(0, int(scope.get("repost_limit") or 0)),
            max_scroll_actions=max(1, max_scroll_actions),
            include_replies=bool(scope.get("include_replies")),
            retain_author_display=retain_author_display,
            login_wait=max(0, login_wait),
            max_asset_bytes=max(1, max_asset_mb) * 1024 * 1024,
            resume=resume,
            selection_context={
                "selection_reason": task.get("selection_reason") or "project_seed_post",
            },
        )
        scope_fulfilled = str(post["completion_state"]).startswith("complete")
        if comments:
            scope_fulfilled = scope_fulfilled and _component_fulfills_requested_scope(
                comments,
                requested_limit=max(0, int(scope.get("comment_limit") or 0)),
                saved_key="saved_comments",
            )
        if reposts:
            scope_fulfilled = scope_fulfilled and _component_fulfills_requested_scope(
                reposts,
                requested_limit=max(0, int(scope.get("repost_limit") or 0)),
                saved_key="saved_reposts",
            )
        result = {
            "state": "complete_requested_scope" if scope_fulfilled else "partial",
            "post_id": post["post_id"],
            "post_state": post["completion_state"],
            "comment_state": comments["state"] if comments else "not_requested",
            "repost_state": reposts["state"] if reposts else "not_requested",
        }
    else:
        raise CollectionError(f"Unsupported project source task: {source_type}")

    _write_task_manifest(task_out, task, result)
    return result


def _default_task_executor(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return execute_browser_source_task(task, **kwargs)


def run_project_tasks(
    raw_plan: dict[str, Any], *, profile_dir: Path, out: Path,
    mode: str, assets: list[str], resume: bool,
    max_profile_scroll_actions: int = 80,
    max_search_scroll_actions: int = 80,
    max_scroll_actions: int = 800,
    login_wait: int = 0,
    retain_author_display: bool = False,
    chrome_path: str | None = None,
    max_asset_mb: int = 200,
    task_executor: Callable[..., dict[str, Any]] | None = None,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run all fixed project tasks in one browser session and persist resumable state."""
    profile_dir = Path(profile_dir).expanduser().resolve()
    out = Path(out).expanduser().resolve()
    if profile_dir == out or profile_dir in out.parents or out in profile_dir.parents:
        raise CollectionError("The private Chrome profile and delivery directory must be separate")
    state_dir = project_state_dir(out)
    if state_dir == profile_dir or state_dir in profile_dir.parents or profile_dir in state_dir.parents:
        raise CollectionError("The project state directory and private Chrome profile must be separate")
    if state_dir.exists() and any(state_dir.iterdir()) and not resume:
        raise CollectionError("Project state already exists; use --resume or choose a new output directory")

    dry_run = build_project_dry_run(
        raw_plan, mode=mode, profile_dir=profile_dir, out=out,
        assets=assets, resume=resume, package_zip=False,
    )
    tasks = sorted(
        dry_run["source_tasks"],
        key=lambda task: (0 if task["phase"] == "discovery" else 1, task["campaign_id"], task["source_task_id"]),
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "data" / "project_plan.json", dry_run["project"])

    stored = _read_json(state_dir / "task_state.json", {}) if resume else {}
    plan_sha256 = _project_plan_sha256(dry_run["project"])
    if resume and stored:
        if str(stored.get("project_id") or "") != dry_run["project"]["project_id"]:
            raise CollectionError("The saved project state belongs to a different project_id")
        if str(stored.get("project_plan_sha256") or "") != plan_sha256:
            raise CollectionError("The project plan changed after tasks were frozen; use a new output directory")
    stored_records = {
        str(record.get("source_task_id") or ""): record
        for record in (stored.get("source_tasks") or [])
        if isinstance(record, dict) and record.get("source_task_id")
    }
    records: list[dict[str, Any]] = []
    for task in tasks:
        previous = stored_records.get(task["source_task_id"], {})
        record = {**task}
        record.update({
            "state": previous.get("state", "queued") if resume else "queued",
            "attempts": int(previous.get("attempts") or 0) if resume else 0,
            "started_at": str(previous.get("started_at") or "") if resume else "",
            "finished_at": str(previous.get("finished_at") or "") if resume else "",
            "result_summary": dict(previous.get("result_summary") or {}) if resume else {},
            "error_type": str(previous.get("error_type") or "") if resume else "",
            "error_message": str(previous.get("error_message") or "") if resume else "",
            "resume_available": previous.get("state") != "complete" if resume else True,
        })
        records.append(record)

    started_at = str(stored.get("started_at") or utc_now()) if resume else utc_now()

    def persist(*, finished_at: str = "") -> dict[str, Any]:
        manifest = _project_manifest(dry_run, records, started_at=started_at, finished_at=finished_at)
        atomic_write_json(state_dir / "task_state.json", {
            "schema_version": "brandbai.weibo.project-task-state.v1",
            "project_id": dry_run["project"]["project_id"],
            "project_plan_sha256": plan_sha256,
            "started_at": started_at,
            "source_tasks": records,
        })
        _atomic_write_jsonl(out / "data" / "source_tasks.jsonl", [_public_task_record(record) for record in records])
        atomic_write_json(out / "data" / "project_manifest.json", manifest)
        return manifest

    persist()
    executor = task_executor or _default_task_executor
    factory = session_factory or visible_chrome_session
    if resume and records and all(record["state"] == "complete" for record in records):
        return persist(finished_at=utc_now())
    blocked = False
    with factory(profile_dir=profile_dir, chrome_path=chrome_path) as (context, page):
        for record in records:
            if resume and record["state"] == "complete":
                continue
            if blocked:
                break
            record.update({
                "state": "running",
                "attempts": int(record.get("attempts") or 0) + 1,
                "started_at": utc_now(),
                "finished_at": "",
                "error_type": "",
                "error_message": "",
            })
            persist()
            task_out = _task_cache_dir(state_dir, record["source_task_id"])
            try:
                result = executor(
                    record,
                    task_out=task_out,
                    context=context,
                    page=page,
                    assets=assets,
                    max_profile_scroll_actions=max_profile_scroll_actions,
                    max_search_scroll_actions=max_search_scroll_actions,
                    max_scroll_actions=max_scroll_actions,
                    login_wait=login_wait,
                    retain_author_display=retain_author_display,
                    max_asset_mb=max_asset_mb,
                    resume=resume or record["attempts"] > 1,
                )
                state = str(result.get("state") or "failed")
                if state.startswith("complete"):
                    normalized_state = "complete"
                elif state.startswith("partial"):
                    normalized_state = "partial"
                elif state in TASK_STATES:
                    normalized_state = state
                else:
                    normalized_state = "failed"
                record.update({
                    "state": normalized_state,
                    "finished_at": utc_now(),
                    "result_summary": result,
                    "resume_available": normalized_state != "complete",
                })
            except Exception as exc:
                message = _redact_runtime_paths(
                    str(exc).strip(), [profile_dir, out, state_dir, task_out]
                )
                needs_user = isinstance(exc, CollectionError) and (
                    "manual login" in message.lower() or "verification" in message.lower()
                )
                record.update({
                    "state": "blocked" if needs_user else "failed",
                    "finished_at": utc_now(),
                    "result_summary": {},
                    "error_type": type(exc).__name__,
                    "error_message": message,
                    "resume_available": True,
                })
                blocked = needs_user
            persist()

    return persist(finished_at=utc_now())
