"""Visible-Chrome collector for public TikTok pages.

The collector observes data returned by the page and visible DOM. It does not read
cookies, browser storage, credentials, request headers or signature material.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urlparse

from collector_core import (
    CollectionError, append_jsonl, atomic_write_json, canonical_handle, canonical_profile_url,
    canonical_work_id, canonical_work_url, comment_completion_state, derived_id,
    freeze_search_results, sanitize_media_url, safe_filename, select_profile_works,
    stable_pseudonym, utc_now, work_type_from_url,
)


ASSET_CHOICES = {"media", "cover", "audio"}


def normalize_assets(value: str | Iterable[str]) -> list[str]:
    values = value.split(",") if isinstance(value, str) else list(value)
    output: list[str] = []
    for raw in values:
        item = str(raw or "").strip().lower()
        if not item:
            continue
        if item not in ASSET_CHOICES:
            raise CollectionError(f"Unsupported asset choice: {item}")
        if item not in output:
            output.append(item)
    return output


def search_url(keyword: str, tab: str) -> str:
    if tab not in {"general", "video", "photo"}:
        raise ValueError("search tab must be general, video or photo")
    path = "/search" if tab == "general" else f"/search/{tab}"
    return f"https://www.tiktok.com{path}?{urlencode({'q': keyword})}"


def page_kind(url: str) -> str:
    path = urlparse(url).path
    if re.search(r"/@[^/]+/(video|photo)/\d+", path):
        return "work"
    if path.startswith("/search"):
        return "search"
    if re.fullmatch(r"/@[^/]+/?", path):
        return "profile"
    return "unknown"


def _first_url(value: Any) -> str:
    if isinstance(value, str) and value.startswith("https://"):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("urlList", "url_list", "urls", "url"):
            found = _first_url(value.get(key))
            if found:
                return found
        for child in value.values():
            found = _first_url(child)
            if found:
                return found
    return ""


def _candidate_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        keys = set(value)
        has_id = any(key in value for key in ("id", "aweme_id", "item_id"))
        looks_like_item = has_id and bool(keys.intersection({"desc", "author", "stats", "statistics", "video", "imagePost", "image_post_info"}))
        if looks_like_item:
            yield value
        for key, child in value.items():
            if key.lower() in {"headers", "cookie", "cookies", "requestheaders"}:
                continue
            yield from _candidate_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _candidate_nodes(child)


def _int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def normalize_item(node: dict[str, Any], source_url: str = "") -> dict[str, Any] | None:
    work_id = str(node.get("id") or node.get("aweme_id") or node.get("item_id") or "").strip()
    if not work_id.isdigit():
        return None
    author = node.get("author") if isinstance(node.get("author"), dict) else {}
    handle = str(author.get("uniqueId") or author.get("unique_id") or author.get("shortId") or "").lstrip("@")
    if not handle and source_url:
        try:
            handle = canonical_handle(source_url)
        except ValueError:
            pass
    image_post = node.get("imagePost") or node.get("image_post_info") or {}
    image_rows = image_post.get("images") or image_post.get("image_list") or [] if isinstance(image_post, dict) else []
    work_type = "photo" if image_rows else (work_type_from_url(source_url) if source_url and "/photo/" in source_url else "video")
    stats = node.get("stats") or node.get("statistics") or {}
    author_stats = node.get("authorStats") or node.get("author_stats") or author.get("stats") or {}
    if not isinstance(author_stats, dict):
        author_stats = {}
    video = node.get("video") if isinstance(node.get("video"), dict) else {}
    music = node.get("music") if isinstance(node.get("music"), dict) else {}
    assets: list[dict[str, Any]] = []
    if work_type == "photo":
        for order, image in enumerate(image_rows, start=1):
            raw = _first_url(image)
            if raw:
                assets.append({"kind": "photo", "order": order, "url": raw})
    else:
        raw_video = _first_url(video.get("downloadAddr") or video.get("download_addr") or video.get("playAddr") or video.get("play_addr"))
        if raw_video:
            assets.append({"kind": "video", "order": 1, "url": raw_video})
    cover = _first_url(video.get("cover") or video.get("originCover") or video.get("origin_cover") or node.get("cover"))
    if not cover and image_rows:
        cover = _first_url(image_rows[0])
    if cover:
        assets.append({"kind": "cover", "order": 1, "url": cover})
    audio = _first_url(music.get("playUrl") or music.get("play_url") or music.get("audioUrl"))
    if audio:
        assets.append({"kind": "audio", "order": 1, "url": audio})
    caption = str(node.get("desc") or node.get("description") or "").strip()
    hashtags = re.findall(r"#([^\s#]+)", caption)
    mentions = re.findall(r"@([A-Za-z0-9._-]+)", caption)
    create_time = node.get("createTime") or node.get("create_time")
    stable_creator_id = str(author.get("secUid") or author.get("sec_uid") or author.get("id") or author.get("uid") or "")
    creator_snapshot = {
        "nickname": str(author.get("nickname") or author.get("nick_name") or ""),
        "platform_account": handle,
        "stable_creator_id": stable_creator_id,
        "profile_url": canonical_profile_url(handle) if handle else "",
        "bio": str(author.get("signature") or author.get("bioLink") or author.get("bio") or ""),
        "followers": _int_value(author_stats.get("followerCount") if "followerCount" in author_stats else author_stats.get("follower_count")),
        "total_likes": _int_value(
            author_stats.get("heartCount") if "heartCount" in author_stats
            else author_stats.get("heart_count") if "heart_count" in author_stats
            else author_stats.get("diggCount")
        ),
        "snapshot_at": utc_now() if any((handle, stable_creator_id, author.get("nickname"), author.get("nick_name"))) else "",
        "source": "current_work_detail",
    }
    return {
        "platform": "tiktok", "work_id": work_id, "work_type": work_type,
        "author_handle": handle, "author_name": author.get("nickname") or author.get("nick_name") or "",
        "author_id": str(author.get("id") or author.get("uid") or ""),
        "title": caption[:120], "caption": caption, "hashtags": hashtags, "mentions": mentions,
        "published_at": int(create_time) if str(create_time or "").isdigit() else None,
        "metrics": {
            "plays": _int_value(stats.get("playCount") or stats.get("play_count")),
            "likes": _int_value(stats.get("diggCount") or stats.get("digg_count")),
            "comments": _int_value(stats.get("commentCount") or stats.get("comment_count")),
            "collects": _int_value(stats.get("collectCount") or stats.get("collect_count")),
            "shares": _int_value(stats.get("shareCount") or stats.get("share_count")),
        },
        "creator_snapshot": creator_snapshot,
        "assets": assets,
        "canonical_url": canonical_work_url(source_url or work_id, handle=handle or "unknown", work_type=work_type),
        "collected_at": utc_now(), "completion_state": "complete_visible_work" if caption or assets else "partial_selector_drift",
        "source_scope": "visible_page_and_normal_responses",
    }


def items_from_payload(payload: Any, source_url: str = "") -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in _candidate_nodes(payload):
        item = normalize_item(node, source_url)
        if item and item["work_id"] not in seen:
            seen.add(item["work_id"])
            output.append(item)
    return output


def comments_from_payload(payload: Any, work_id: str, retain_author_display: bool = False) -> tuple[list[dict[str, Any]], bool]:
    candidates: list[dict[str, Any]] = []
    exhausted = False
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if value.get("has_more") in (0, False) or value.get("hasMore") is False:
                exhausted = True
            comments = value.get("comments") or value.get("comment_list")
            if isinstance(comments, list):
                candidates.extend(row for row in comments if isinstance(row, dict))
            stack.extend(child for key, child in value.items() if key.lower() not in {"headers", "cookies"})
        elif isinstance(value, list):
            stack.extend(value)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        comment_id = str(row.get("cid") or row.get("id") or row.get("comment_id") or "")
        text = str(row.get("text") or row.get("content") or "").strip()
        if not comment_id:
            comment_id = derived_id("comment", work_id, text, row.get("create_time"))
            id_type = "derived"
        else:
            id_type = "platform"
        if comment_id in seen:
            continue
        seen.add(comment_id)
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        author_key = str(user.get("uid") or user.get("unique_id") or user.get("nickname") or comment_id)
        reply_count = _int_value(row.get("reply_comment_total") or row.get("reply_count")) or 0
        output.append({
            "comment_id": comment_id, "comment_id_type": id_type, "work_id": work_id, "level": 1,
            "parent_comment_id": "", "root_comment_id": comment_id,
            "author_id": stable_pseudonym(author_key),
            "author_display": str(user.get("nickname") or "") if retain_author_display else "",
            "content": text, "create_time": row.get("create_time"),
            "like_count": _int_value(row.get("digg_count") or row.get("like_count")),
            "declared_reply_count": reply_count, "saved_reply_count": 0,
            "reply_expansion_status": "not_requested", "collected_at": utc_now(),
        })
    return output, exhausted


def _chrome_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    candidates = [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((path for path in candidates if Path(path).is_file()), None)


def _dom_links(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(r"""
      () => Array.from(document.querySelectorAll('a[href*="/video/"],a[href*="/photo/"]')).map((a, i) => {
        const href = a.href || '';
        const m = href.match(/\/(video|photo)\/(\d+)/);
        const box = a.closest('div[data-e2e],article,div');
        const text = (box?.innerText || a.innerText || '').trim();
        const pinned = /Pinned|置顶/i.test(text);
        const img = a.querySelector('img') || box?.querySelector('img');
        return m ? {work_id:m[2],work_type:m[1],url:href,rank:i+1,title:text.slice(0,300),
          cover_url:img?.currentSrc||img?.src||'',is_pinned:pinned} : null;
      }).filter(Boolean)
    """)


def _scroll_discover(page: Any, wanted: int, max_actions: int) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    stable = 0
    for _ in range(max_actions + 1):
        before = len(by_id)
        for row in _dom_links(page):
            by_id.setdefault(str(row["work_id"]), row)
        if len(by_id) >= wanted:
            break
        stable = stable + 1 if len(by_id) == before else 0
        if stable >= 4:
            break
        page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 0.85, 600))")
        page.wait_for_timeout(700)
    return list(by_id.values())


def _write_jsonl_replace(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def missing_requested_asset_records(work: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    """Represent requested public assets that TikTok did not provide.

    A missing independent audio URL is a real evidence gap, not a failed video.
    Keeping an explicit record prevents a 19/20 package from being reported as
    19/19 and lets the ordinary delivery explain that the saved MP4 still has
    playable audio when the media download succeeded.
    """

    available = {str(asset.get("kind") or "") for asset in work.get("assets") or []}
    expected: list[tuple[str, str]] = []
    if "media" in requested:
        media_kind = "photo" if work.get("work_type") == "photo" else "video"
        if media_kind not in available:
            expected.append((media_kind, "TikTok public page did not provide a downloadable media URL"))
    if "cover" in requested and "cover" not in available:
        expected.append(("cover", "TikTok public page did not provide a cover URL"))
    if "audio" in requested and "audio" not in available:
        expected.append((
            "audio",
            "TikTok public page did not provide an independent audio URL; a saved MP4 remains playable with its embedded audio",
        ))
    return [{
        "asset_id": derived_id("asset", work["work_id"], kind, 1),
        "work_id": work["work_id"], "kind": kind, "order": 1,
        "status": "not_provided", "local_file": "", "source_url": "",
        "source_url_state": "not_provided", "bytes": 0, "sha256": "",
        "error_reason": reason,
    } for kind, reason in expected]


def _download_assets(context: Any, out: Path, work: dict[str, Any], requested: list[str], max_asset_mb: int) -> list[dict[str, Any]]:
    records = missing_requested_asset_records(work, requested)
    work_dir = out / "04_作品素材" / safe_filename(f"{work['work_id']}_{work.get('title') or 'work'}")
    work_dir.mkdir(parents=True, exist_ok=True)
    extensions = {"video": ".mp4", "audio": ".mp3", "cover": ".jpg", "photo": ".jpg"}
    for asset in work.get("assets") or []:
        kind = str(asset.get("kind") or "")
        if (kind in {"video", "photo"} and "media" not in requested) or (kind not in {"video", "photo"} and kind not in requested):
            continue
        order = int(asset.get("order") or 1)
        asset_id = derived_id("asset", work["work_id"], kind, order)
        record = {"asset_id": asset_id, "work_id": work["work_id"], "kind": kind, "order": order,
                  "status": "failed", "local_file": "", "source_url": "", "bytes": 0, "sha256": "", "error_reason": ""}
        try:
            clean_url, was_transient = sanitize_media_url(str(asset.get("url") or ""))
            record["source_url"] = clean_url
            record["source_url_state"] = "transient_url_redacted" if was_transient else "public_url"
            response = context.request.get(str(asset.get("url")), timeout=60_000)
            if not response.ok:
                raise CollectionError(f"HTTP {response.status}")
            body = response.body()
            if len(body) > max_asset_mb * 1024 * 1024:
                raise CollectionError("asset exceeds configured size limit")
            filename = f"{order:02d}_{kind}{extensions.get(kind, '.bin')}"
            target = work_dir / filename
            target.write_bytes(body)
            record.update({"status": "downloaded", "local_file": str(target.relative_to(out)), "bytes": len(body),
                           "sha256": hashlib.sha256(body).hexdigest()})
        except Exception as exc:  # keep partial evidence and continue
            record["error_reason"] = str(exc)[:240]
        records.append(record)
    return records


def _merge_selection_fields(work: dict[str, Any], seed: dict[str, Any] | None) -> dict[str, Any]:
    if not seed:
        return work
    for key in ("author_handle", "author_name", "title", "published_at"):
        if work.get(key) in (None, "") and seed.get(key) not in (None, ""):
            work[key] = seed[key]
    work["is_pinned"] = bool(seed.get("is_pinned"))
    work["selection_reason"] = seed.get("selection_reason") or "插件作品清单"
    work["selection_rank"] = seed.get("selection_rank") or seed.get("rank") or seed.get("source_rank")
    work["source_page_type"] = seed.get("source_page_type") or "selection"
    work["source_keyword"] = seed.get("source_keyword") or ""
    work["source_rank"] = seed.get("source_rank") or seed.get("rank")
    work["selection_snapshot_metrics"] = dict(seed.get("metrics") or {})
    return work


def collect(
    *, work_targets: list[str], profile_target: str | None, search_query: str | None,
    selection_rows: list[dict[str, Any]] | None, selection_metadata: dict[str, Any] | None,
    recent: int, search_limit: int, search_tab: str, search_filters: list[str],
    max_list_scroll_actions: int, profile_dir: Path, out: Path, mode: str, assets: list[str],
    comment_limit: int, max_comment_scroll_actions: int, include_replies: bool,
    retain_author_display: bool, login_wait: int, resume: bool, chrome_path: str | None,
    max_asset_mb: int, business_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt") from exc
    out.mkdir(parents=True, exist_ok=True)
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    collected_works: dict[str, dict[str, Any]] = {}
    collected_comments: dict[str, dict[str, Any]] = {}
    asset_rows: list[dict[str, Any]] = []
    profile_selection: dict[str, Any] = {}
    search_snapshots: list[dict[str, Any]] = []
    comment_states: dict[str, str] = {}
    response_items: dict[str, dict[str, Any]] = {}
    response_comments: dict[str, dict[str, Any]] = {}
    terminal_by_work: dict[str, bool] = {}
    selection_snapshot: dict[str, Any] = {}
    selection_by_id: dict[str, dict[str, Any]] = {}

    def observe_response(response: Any) -> None:
        url = response.url
        if "tiktok.com" not in url or response.request.resource_type not in {"xhr", "fetch", "document"}:
            return
        try:
            if "application/json" not in (response.headers.get("content-type") or ""):
                return
            payload = response.json()
        except Exception:
            return
        for item in items_from_payload(payload, url):
            response_items[item["work_id"]] = item
        match = re.search(r"(?:aweme_id|item_id)=([0-9]+)", url)
        work_id = match.group(1) if match else ""
        if work_id and "comment" in url.lower():
            rows, exhausted = comments_from_payload(payload, work_id, retain_author_display)
            for row in rows:
                response_comments[row["comment_id"]] = row
            terminal_by_work[work_id] = terminal_by_work.get(work_id, False) or exhausted

    with sync_playwright() as playwright:
        executable = _chrome_path(chrome_path)
        launch_args: dict[str, Any] = {"headless": False, "locale": "en-US", "viewport": None}
        if executable:
            launch_args["executable_path"] = executable
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_args)
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", observe_response)
        targets = list(work_targets)
        if selection_rows:
            normalized_rows = [dict(row) for row in selection_rows]
            selection_by_id = {str(row["work_id"]): row for row in normalized_rows}
            targets = [str(row["url"]) for row in normalized_rows]
            selection_snapshot = {
                "contract": (selection_metadata or {}).get("contract", "brandbai.tiktok.selection/v1"),
                "source": dict(selection_metadata or {}),
                "captured_at": (selection_metadata or {}).get("captured_at") or started,
                "selected_count": len(normalized_rows),
                "state": "complete_explicit_selection",
                "works": normalized_rows,
            }
        elif profile_target:
            profile_url = canonical_profile_url(profile_target)
            page.goto(profile_url, wait_until="domcontentloaded", timeout=90_000)
            if login_wait:
                page.wait_for_timeout(login_wait * 1000)
            discovered = _scroll_discover(page, recent + 20, max_list_scroll_actions)
            selection = select_profile_works(discovered, recent)
            profile_selection = {
                **selection, "profile_selection_id": derived_id("profile", profile_url, started),
                "profile_handle": canonical_handle(profile_target), "canonical_url": profile_url,
                "captured_at": utc_now(), "discovered_count": len(discovered),
                "profile": {"display_name": page.title(), "author_handle": canonical_handle(profile_target)},
            }
            targets = [row["url"] for row in selection["selected"]]
            selection_by_id = {str(row["work_id"]): row for row in selection["selected"]}
        elif search_query:
            page.goto(search_url(search_query, search_tab), wait_until="domcontentloaded", timeout=90_000)
            if login_wait:
                page.wait_for_timeout(login_wait * 1000)
            discovered = _scroll_discover(page, search_limit, max_list_scroll_actions)
            snapshot = freeze_search_results(discovered, keyword=search_query, tab=search_tab,
                                             filters=search_filters, limit=search_limit)
            search_snapshots.append(snapshot)
            targets = [row["url"] for row in snapshot["results"]]
            selection_by_id = {str(row["work_id"]): row for row in snapshot["results"]}

        for target in targets:
            page.goto(target, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(1800)
            work_id = canonical_work_id(target)
            seed = selection_by_id.get(work_id)
            work = response_items.get(work_id)
            if not work:
                dom = _dom_links(page)
                row = next((item for item in dom if str(item.get("work_id")) == work_id), None) or {
                    "work_id": work_id, "work_type": work_type_from_url(target), "url": target, "title": page.title()
                }
                work = {
                    "platform": "tiktok", "work_id": work_id, "work_type": row.get("work_type"),
                    "author_handle": canonical_handle(target), "author_name": (seed or {}).get("author_name", ""), "author_id": "",
                    "title": row.get("title") or (seed or {}).get("title") or page.title(), "caption": "", "hashtags": [], "mentions": [],
                    "published_at": None, "metrics": {}, "assets": [], "canonical_url": canonical_work_url(target),
                    "collected_at": utc_now(), "completion_state": "partial_selector_drift",
                    "source_scope": "visible_dom_fallback",
                }
            work = _merge_selection_fields(work, seed)
            collected_works[work_id] = work
            if mode in {"work", "all", "batch"} and assets:
                new_assets = _download_assets(context, out, work, assets, max_asset_mb)
                asset_rows.extend(new_assets)
                if str(work.get("completion_state") or "").startswith("complete_"):
                    if any(row["status"] == "failed" for row in new_assets):
                        work["completion_state"] = "partial_asset_failure"
                    elif any(row["status"] == "not_provided" for row in new_assets):
                        work["completion_state"] = "partial_asset_unavailable"
            if mode in {"comments", "all"}:
                stable = 0
                last_count = len(response_comments)
                for _ in range(max_comment_scroll_actions):
                    if terminal_by_work.get(work_id):
                        break
                    if comment_limit and len([r for r in response_comments.values() if r["work_id"] == work_id]) >= comment_limit:
                        break
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(500)
                    current = len(response_comments)
                    stable = stable + 1 if current == last_count else 0
                    last_count = current
                    if stable >= 8:
                        break
                rows = [row for row in response_comments.values() if row["work_id"] == work_id]
                limit_reached = bool(comment_limit and len(rows) >= comment_limit)
                if comment_limit:
                    rows = rows[:comment_limit]
                for row in rows:
                    collected_comments[row["comment_id"]] = row
                comment_states[work_id] = comment_completion_state(
                    exhausted=terminal_by_work.get(work_id, False), limit_reached=limit_reached,
                    replies_requested=include_replies,
                    declared_reply_count=sum(int(row.get("declared_reply_count") or 0) for row in rows),
                    saved_reply_count=0,
                )
        context.close()

    _write_jsonl_replace(data_dir / "works.jsonl", collected_works.values())
    _write_jsonl_replace(data_dir / "comments.jsonl", collected_comments.values())
    _write_jsonl_replace(data_dir / "assets.jsonl", asset_rows)
    _write_jsonl_replace(data_dir / "search_snapshots.jsonl", search_snapshots)
    if profile_selection:
        atomic_write_json(data_dir / "profile_selection.json", profile_selection)
    if selection_snapshot:
        atomic_write_json(data_dir / "input_selection.json", selection_snapshot)
    states = [row.get("completion_state") for row in collected_works.values()]
    states.extend(comment_states.values())
    if profile_selection:
        states.append(profile_selection.get("state"))
    if selection_snapshot:
        states.append(selection_snapshot.get("state"))
    states.extend(row.get("state") for row in search_snapshots)
    complete = bool(states) and all(str(state or "").startswith("complete_") for state in states)
    asset_status_counts = {
        status: len([row for row in asset_rows if row.get("status") == status])
        for status in ("downloaded", "not_provided", "failed")
    }
    manifest = {
        "platform": "tiktok", "mode": mode, "started_at": started, "finished_at": utc_now(),
        "state": "complete" if complete else "partial", "resume": bool(resume),
        "works": len(collected_works), "comments": len(collected_comments), "assets": len(asset_rows),
        "comment_states": comment_states,
        "profile_selection_state": profile_selection.get("state", "not_applicable"),
        "explicit_selection_state": selection_snapshot.get("state", "not_applicable"),
        "search_selection_state": search_snapshots[0].get("state") if search_snapshots else "not_applicable",
        "asset_status_counts": asset_status_counts,
        "privacy": "comment_display_authors_retained" if retain_author_display else "comment_authors_pseudonymized",
        "business_context": dict(business_context or {}),
    }
    atomic_write_json(data_dir / "run_manifest.json", manifest)
    return manifest
