"""Collect source-visible Xiaohongshu note facts, media and comments in Chrome.

The collector uses a dedicated persistent Chrome profile chosen by the user.
It never exports cookies, request headers, browser profiles, signatures,
verification data, or transient xsec query parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from collector_core import (
    CollectionError,
    atomic_write_json,
    canonical_note_id,
    canonical_note_url,
    comment_completion_state,
    derived_id,
    normalize_note_targets,
    safe_filename,
    sanitize_media_url,
    stable_pseudonym,
    utc_now,
)


NOTE_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const root = document.querySelector('.note-container');
  if (!root) return null;
  const content = root.querySelector('.note-content') || root;
  const authorRoot = root.querySelector('.author-container') || root.querySelector('.author');
  const authorLink = authorRoot?.querySelector('a[href*="/user/profile/"]');
  const authorHref = authorLink?.getAttribute('href') || '';
  const authorMatch = authorHref.match(/\/user\/profile\/([^/?#]+)/);
  const title = clean(content.querySelector('.title')?.textContent);
  const body = clean(content.querySelector('.desc')?.innerText || content.querySelector('.desc')?.textContent);
  const dateText = clean(content.querySelector('.date')?.innerText || content.querySelector('.date')?.textContent);
  const dateLocation = dateText.match(/^(.*?)(?:\s+)([^\s]+)$/);
  const tags = [...body.matchAll(/#([^#\s]+)/g)].map((match) => '#' + match[1]);
  const mentions = [...body.matchAll(/@([^@#\s]+)/g)].map((match) => '@' + match[1]);

  const mediaRoot = root.querySelector('.media-container');
  const images = [];
  const imageSeen = new Set();
  for (const image of [...(mediaRoot?.querySelectorAll('img') || [])]) {
    const source = image.currentSrc || image.src || '';
    if (!/^https?:\/\//i.test(source) || /avatar|picasso-static/i.test(source)) continue;
    const key = source.split('?')[0];
    if (imageSeen.has(key)) continue;
    imageSeen.add(key);
    images.push({
      src: source,
      width: image.naturalWidth || image.clientWidth || 0,
      height: image.naturalHeight || image.clientHeight || 0,
    });
  }
  const videos = [];
  const videoSeen = new Set();
  let hasBlobVideo = false;
  for (const video of [...(mediaRoot?.querySelectorAll('video,video source') || [])]) {
    const source = video.currentSrc || video.src || video.getAttribute('src') || '';
    if (source.startsWith('blob:')) hasBlobVideo = true;
    if (!/^https?:\/\//i.test(source)) continue;
    const key = source.split('?')[0];
    if (videoSeen.has(key)) continue;
    videoSeen.add(key);
    videos.push({src: source, width: video.videoWidth || video.clientWidth || 0, height: video.videoHeight || video.clientHeight || 0});
  }

  const counts = [...root.querySelectorAll('.engage-bar-container .buttons .count')]
    .map((node) => clean(node.textContent));
  const commentsText = clean(root.querySelector('.comments-container')?.innerText);
  const declaredMatch = commentsText.match(/共\s*([0-9.万wW+]+)\s*条评论/);
  return {
    title,
    body,
    author_name: clean(authorRoot?.querySelector('.username')?.textContent),
    author_platform_id: authorMatch ? authorMatch[1] : '',
    published_at_text: dateLocation ? clean(dateLocation[1]) : dateText,
    region_text: dateLocation ? clean(dateLocation[2]) : '',
    topics: [...new Set(tags)],
    mentions: [...new Set(mentions)],
    metrics: {likes: counts[0] || '', collects: counts[1] || '', comments: counts[2] || declaredMatch?.[1] || '', shares: counts[3] || ''},
    declared_comment_count_text: declaredMatch?.[1] || '',
    images,
    videos,
    has_blob_video: hasBlobVideo,
    data_type: root.getAttribute('data-type') || '',
  };
}
"""


COMMENTS_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const root = document.querySelector('.note-container');
  if (!root) return {rows: [], exhausted: false, declared: ''};
  const container = root.querySelector('.comments-container');
  if (!container) return {rows: [], exhausted: false, declared: ''};
  const containerText = clean(container.innerText);
  const declared = containerText.match(/共\s*([0-9.万wW+]+)\s*条评论/)?.[1] || '';
  const parentRoots = [...container.querySelectorAll('.parent-comment')];
  const rows = [];
  for (const parent of parentRoots) {
    const cards = [...parent.querySelectorAll('.comment-item')];
    const declaredReplies = Number((clean(parent.innerText).match(/(?:展开|共)\s*(\d+)\s*条回复/) || [])[1] || 0);
    cards.forEach((card, index) => {
      const nameLink = card.querySelector('a.name[href*="/user/profile/"]');
      const href = nameLink?.getAttribute('href') || '';
      const platformAuthor = (href.match(/\/user\/profile\/([^/?#]+)/) || [])[1] || '';
      const content = clean(card.querySelector('.content .note-text')?.innerText || card.querySelector('.content .note-text')?.textContent);
      const dateRoot = card.querySelector('.date');
      const region = clean(dateRoot?.querySelector('.location')?.textContent);
      let time = clean(dateRoot?.innerText || dateRoot?.textContent);
      if (region && time.endsWith(region)) time = clean(time.slice(0, -region.length));
      rows.push({
        level: index === 0 ? 1 : 2,
        author_name: clean(nameLink?.textContent),
        author_platform_id: platformAuthor,
        content,
        time_text: time,
        region_text: region,
        like_count_text: clean(card.querySelector('.interactions .like .count')?.textContent),
        declared_reply_count: index === 0 ? declaredReplies : 0,
        saved_reply_count: index === 0 ? Math.max(0, cards.length - 1) : 0,
      });
    });
  }
  return {rows, exhausted: /THE END/i.test(containerText), declared};
}
"""


def find_chrome_executable(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return str(path)
        raise CollectionError(f"Chrome executable not found: {path}")
    candidates: list[Path] = []
    if sys.platform == "win32":
        for root in [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]:
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise CollectionError("Google Chrome was not found; pass --chrome-path explicitly")


def normalize_assets(value: str) -> list[str]:
    allowed = {"images", "video", "cover", "none"}
    parts: list[str] = []
    for raw in str(value or "").split(","):
        part = raw.strip()
        if part and part not in parts:
            parts.append(part)
    unknown = [part for part in parts if part not in allowed]
    if unknown:
        raise CollectionError(f"Unknown asset type(s): {', '.join(unknown)}")
    if "none" in parts and len(parts) > 1:
        raise CollectionError("assets=none cannot be combined with other asset types")
    return [] if parts == ["none"] else parts


def _read_jsonl_ids(path: Path, field: str) -> set[str]:
    if not path.is_file():
        return set()
    values: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = str(value.get(field) or "") if isinstance(value, dict) else ""
        if item:
            values.add(item)
    return values


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def _extension(clean_url: str, content_type: str, kind: str) -> str:
    suffix = Path(urlparse(clean_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed or (".mp4" if kind == "video" else ".bin")


def _download_asset(context: Any, source: str, target_base: Path, *, kind: str, max_bytes: int) -> dict[str, Any]:
    clean_url, redacted = sanitize_media_url(source)
    response = context.request.get(source, timeout=90_000)
    if not response.ok:
        raise CollectionError(f"Asset request returned HTTP {response.status}")
    body = response.body()
    if len(body) > max_bytes:
        raise CollectionError(f"Asset exceeds configured size limit ({len(body)} bytes)")
    content_type = response.headers.get("content-type", "")
    target = target_base.with_suffix(_extension(clean_url, content_type, kind))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {
        "local_file": str(target),
        "source_url": clean_url,
        "source_url_query_redacted": redacted,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "status": "downloaded",
    }


def _load_note(page: Any, navigation_url: str, login_wait: int) -> dict[str, Any]:
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    if not page.locator(".note-container").count() and login_wait > 0:
        print(f"Visible Chrome is ready. Complete login or access confirmation within {login_wait} seconds.")
        page.wait_for_timeout(login_wait * 1_000)
        page.reload(wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2_500)
    for label in ["滑动验证", "安全验证", "请完成验证", "访问频繁"]:
        if page.get_by_text(label, exact=False).count():
            raise CollectionError("Xiaohongshu requires manual verification in the visible Chrome window")
    try:
        page.locator(".note-container").wait_for(state="visible", timeout=25_000)
    except Exception as exc:
        raise CollectionError("No visible Xiaohongshu note detail was found") from exc
    raw = page.evaluate(NOTE_SCRIPT)
    if not raw or not str(raw.get("title") or raw.get("body") or "").strip():
        raise CollectionError("Visible note title and body were not found")
    return raw


def _normalize_comment_rows(
    raw_rows: list[dict[str, Any]], note_id: str, retain_author_display: bool, include_replies: bool,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    current_root = ""
    for row in raw_rows:
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        level = int(row.get("level") or 1)
        author_key = str(row.get("author_platform_id") or row.get("author_name") or "unknown")
        comment_id = derived_id("comment", note_id, level, author_key, content)
        if level == 1:
            current_root = comment_id
        declared_replies = max(int(row.get("declared_reply_count") or 0), int(row.get("saved_reply_count") or 0))
        visible_saved_replies = int(row.get("saved_reply_count") or 0) if include_replies else 0
        if level > 1:
            reply_status = "not_applicable"
        elif not declared_replies:
            reply_status = "not_applicable"
        elif not include_replies:
            reply_status = "not_requested"
        elif visible_saved_replies >= declared_replies:
            reply_status = "complete_visible_replies"
        else:
            reply_status = "partial_reply_not_expanded"
        output.append({
            "comment_id": comment_id,
            "comment_id_type": "derived",
            "note_id": note_id,
            "parent_comment_id": current_root if level > 1 else "",
            "root_comment_id": current_root or comment_id,
            "level": level,
            "author_id": stable_pseudonym(author_key),
            "author_display": str(row.get("author_name") or "") if retain_author_display else "",
            "content": content,
            "time_text": str(row.get("time_text") or ""),
            "region_text": str(row.get("region_text") or ""),
            "like_count_text": str(row.get("like_count_text") or ""),
            "declared_reply_count": declared_replies if level == 1 else 0,
            "saved_reply_count": visible_saved_replies if level == 1 else 0,
            "reply_expansion_status": reply_status,
            "collected_at": utc_now(),
        })
    return output


def _expand_visible_replies(page: Any, remaining_actions: int) -> int:
    if remaining_actions <= 0:
        return 0
    candidates = page.locator('.note-container').get_by_text(re.compile(r"展开\s*\d+\s*条回复"))
    clicked = 0
    for index in range(min(candidates.count(), remaining_actions)):
        candidate = candidates.nth(index)
        try:
            if candidate.is_visible():
                candidate.click(timeout=5_000)
                page.wait_for_timeout(250)
                clicked += 1
        except Exception:
            continue
    return clicked


def _collect_comments(
    page: Any,
    note_id: str,
    comments_path: Path,
    *,
    limit: int,
    max_scroll_actions: int,
    include_replies: bool,
    retain_author_display: bool,
    resume: bool,
    declared_comment_count_hint: str = "",
) -> dict[str, Any]:
    existing_rows = _read_jsonl_rows(comments_path) if resume else []
    saved = {str(row.get("comment_id") or "") for row in existing_rows if row.get("comment_id")}
    current_saved = {str(row.get("comment_id") or "") for row in existing_rows if str(row.get("note_id") or "") == note_id}
    saved_first_level = {
        str(row.get("comment_id") or "") for row in existing_rows
        if str(row.get("note_id") or "") == note_id and int(row.get("level") or 1) == 1
    }
    if not resume and comments_path.exists():
        comments_path.unlink()
    no_growth = 0
    exhausted = False
    limit_reached = False
    scroll_actions = 0
    reply_actions = 0
    completion_basis = ""
    observed_comment_ids: set[str] = set()
    while scroll_actions <= max_scroll_actions:
        before = len(current_saved)
        if include_replies:
            reply_actions += _expand_visible_replies(page, max(0, max_scroll_actions - reply_actions))
        raw = page.evaluate(COMMENTS_SCRIPT)
        normalized = _normalize_comment_rows(raw.get("rows") or [], note_id, retain_author_display, include_replies)
        observed_comment_ids.update(str(row.get("comment_id") or "") for row in normalized if row.get("comment_id"))
        pending: list[dict[str, Any]] = []
        for row in normalized:
            if not include_replies and row["level"] > 1:
                continue
            if row["comment_id"] in saved:
                continue
            if limit > 0 and len(current_saved) >= limit:
                limit_reached = True
                break
            pending.append(row)
            saved.add(row["comment_id"])
            current_saved.add(row["comment_id"])
            if row["level"] == 1:
                saved_first_level.add(row["comment_id"])
        _append_jsonl(comments_path, pending)
        exhausted = bool(raw.get("exhausted"))
        if exhausted:
            completion_basis = "visible_end_marker"
        declared_text = str(raw.get("declared") or declared_comment_count_hint or "").strip()
        if declared_text.isdigit() and len(observed_comment_ids) >= int(declared_text):
            exhausted = True
            completion_basis = "declared_count_reached"
        if limit_reached or exhausted:
            break
        no_growth = no_growth + 1 if len(current_saved) == before else 0
        if no_growth >= 4:
            break
        scroller = page.locator(".note-container .note-scroller")
        if not scroller.count():
            break
        scroller.evaluate("el => el.scrollTo({top: el.scrollHeight, behavior: 'instant'})")
        page.wait_for_timeout(650)
        scroll_actions += 1
    declared_replies = sum(row.get("declared_reply_count", 0) for row in normalized if row.get("level") == 1) if 'normalized' in locals() else 0
    saved_replies = sum(1 for row in normalized if row.get("level") == 2) if 'normalized' in locals() else 0
    state = comment_completion_state(
        exhausted=exhausted,
        limit_reached=limit_reached,
        declared_reply_count=declared_replies,
        saved_reply_count=saved_replies,
        replies_requested=include_replies,
    )
    if state == "complete_visible_panel_exhausted" and completion_basis == "declared_count_reached":
        state = "complete_visible_declared_count_reached"
    return {
        "state": state,
        "saved_comments": len(current_saved),
        "observed_comment_records": len(observed_comment_ids),
        "exhausted": exhausted,
        "limit": limit,
        "limit_reached": limit_reached,
        "include_replies": include_replies,
        "scroll_actions": scroll_actions,
        "reply_expand_actions": reply_actions,
        "completion_basis": completion_basis or "no_termination_signal",
        "finished_at": utc_now(),
    }


def _collect_one_note(
    page: Any,
    context: Any,
    navigation_url: str,
    out: Path,
    *,
    mode: str,
    assets: list[str],
    comment_limit: int,
    max_scroll_actions: int,
    include_replies: bool,
    retain_author_display: bool,
    login_wait: int,
    max_asset_bytes: int,
    resume: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    note_id = canonical_note_id(navigation_url)
    raw = _load_note(page, navigation_url, login_wait)
    author_key = str(raw.get("author_platform_id") or raw.get("author_name") or note_id)
    note_type = "live_photo" if raw.get("images") and raw.get("has_blob_video") else (
        "video" if raw.get("videos") or raw.get("has_blob_video") else ("image" if raw.get("images") else "text")
    )
    note = {
        "note_id": note_id,
        "title": str(raw.get("title") or ""),
        "body": str(raw.get("body") or ""),
        "author_id": stable_pseudonym(author_key),
        "author_name": str(raw.get("author_name") or ""),
        "note_type": note_type,
        "published_at_text": str(raw.get("published_at_text") or ""),
        "region_text": str(raw.get("region_text") or ""),
        "topics": list(raw.get("topics") or []),
        "mentions": list(raw.get("mentions") or []),
        "metrics": dict(raw.get("metrics") or {}),
        "is_pinned": False,
        "canonical_url": canonical_note_url(note_id),
        "collected_at": utc_now(),
        "completion_state": "complete_visible_note",
        "completion_note": "页面可见标题、正文与指标已保存",
    }
    asset_rows: list[dict[str, Any]] = []
    media_specs: list[tuple[str, dict[str, Any]]] = []
    media_specs.extend(("image", item) for item in raw.get("images") or [])
    media_specs.extend(("video", item) for item in raw.get("videos") or [])
    counters = {"image": 0, "video": 0, "cover": 0}
    seen: set[tuple[str, str]] = set()
    for kind, item in media_specs:
        source = str(item.get("src") or "")
        try:
            clean_url, redacted = sanitize_media_url(source)
        except CollectionError:
            continue
        key = (kind, clean_url)
        if key in seen:
            continue
        seen.add(key)
        counters[kind] += 1
        order = counters[kind]
        requested = (kind == "image" and "images" in assets) or (kind == "video" and "video" in assets) or (
            kind == "image" and "cover" in assets and order == 1
        )
        row: dict[str, Any] = {
            "asset_id": f"xhs:{note_id}:{kind}:{order:03d}",
            "note_id": note_id,
            "kind": kind,
            "order": order,
            "status": "observed_not_requested",
            "local_file": "",
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "bytes": 0,
            "sha256": "",
            "error_reason": "",
            "requested": requested,
        }
        if requested:
            try:
                downloaded = _download_asset(
                    context,
                    source,
                    out / "04_笔记素材" / note_id / f"{order:03d}_{kind}",
                    kind=kind,
                    max_bytes=max_asset_bytes,
                )
                downloaded["local_file"] = str(Path(downloaded["local_file"]).relative_to(out))
                row.update(downloaded)
            except Exception as exc:
                row["status"] = "failed"
                row["error_reason"] = type(exc).__name__
        asset_rows.append(row)
    if raw.get("has_blob_video") and not raw.get("videos"):
        live_video_requested = "video" in assets
        asset_rows.append({
            "asset_id": f"xhs:{note_id}:live_photo_video:000",
            "note_id": note_id,
            "kind": "live_photo_video" if note_type == "live_photo" else "video",
            "order": 0,
            "status": "not_observed" if live_video_requested else "observed_not_requested",
            "local_file": "",
            "source_url": "",
            "source_url_query_redacted": False,
            "width": 0,
            "height": 0,
            "bytes": 0,
            "sha256": "",
            "error_reason": "页面只暴露 blob 播放地址，未观察到可保存的源文件地址",
            "requested": live_video_requested,
        })
    requested_rows = [row for row in asset_rows if row.get("requested")]
    if any(row["status"] != "downloaded" for row in requested_rows):
        note["completion_state"] = "partial_asset_failure"
        note["completion_note"] = "笔记字段已保存，但至少一项请求素材未能从可见页面保存"

    notes_path = out / "data" / "notes.jsonl"
    assets_path = out / "data" / "assets.jsonl"
    known_notes = _read_jsonl_ids(notes_path, "note_id") if resume else set()
    known_assets = _read_jsonl_ids(assets_path, "asset_id") if resume else set()
    if not resume:
        for path in [notes_path, assets_path]:
            if path.exists():
                path.unlink()
    if note_id not in known_notes:
        _append_jsonl(notes_path, [note])
    _append_jsonl(assets_path, [row for row in asset_rows if row["asset_id"] not in known_assets])

    comment_manifest = None
    if mode in {"comments", "all"}:
        comment_manifest = _collect_comments(
            page,
            note_id,
            out / "data" / "comments.jsonl",
            limit=comment_limit,
            max_scroll_actions=max_scroll_actions,
            include_replies=include_replies,
            retain_author_display=retain_author_display,
            resume=resume,
            declared_comment_count_hint=str(raw.get("declared_comment_count_text") or (raw.get("metrics") or {}).get("comments") or ""),
        )
    return note, comment_manifest


def collect(
    *,
    note_targets: list[str],
    profile_dir: Path,
    out: Path,
    mode: str,
    assets: list[str],
    comment_limit: int,
    max_scroll_actions: int,
    include_replies: bool,
    retain_author_display: bool,
    login_wait: int,
    resume: bool,
    chrome_path: str | None,
    max_asset_mb: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt first") from exc

    targets = normalize_note_targets(note_targets)
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    note_ids = [canonical_note_id(value) for value in targets]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "collector": "brandbai-xiaohongshu-download",
        "collector_version": "0.1.0",
        "mode": mode,
        "requested_note_ids": note_ids,
        "requested_assets": assets,
        "privacy_mode": "comment_display_authors_retained" if retain_author_display else "comment_authors_pseudonymized",
        "note_states": {},
        "comment_states": {},
        "warnings": [],
        "state": "running",
        "started_at": utc_now(),
        "finished_at": "",
    }
    manifest_path = out / "data" / "run_manifest.json"
    atomic_write_json(manifest_path, manifest)
    executable = find_chrome_executable(chrome_path)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir.resolve()),
            executable_path=executable,
            headless=False,
            viewport=None,
            args=["--start-maximized"],
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for target_index, target in enumerate(targets):
                note_id = canonical_note_id(target)
                try:
                    note, comments = _collect_one_note(
                        page,
                        context,
                        target,
                        out,
                        mode=mode,
                        assets=assets,
                        comment_limit=max(0, comment_limit),
                        max_scroll_actions=max(1, max_scroll_actions),
                        include_replies=include_replies,
                        retain_author_display=retain_author_display,
                        login_wait=max(0, login_wait),
                        max_asset_bytes=max(1, max_asset_mb) * 1024 * 1024,
                        resume=resume or target_index > 0,
                    )
                    manifest["note_states"][note_id] = note["completion_state"]
                    if comments:
                        manifest["comment_states"][note_id] = comments["state"]
                except Exception as exc:
                    manifest["note_states"][note_id] = "failed_no_visible_note"
                    if mode in {"comments", "all"}:
                        manifest["comment_states"][note_id] = "partial_runtime_error"
                    manifest["warnings"].append(f"{note_id}: collection failed ({type(exc).__name__})")
                atomic_write_json(manifest_path, manifest)
        finally:
            context.close()
    states = list(manifest["note_states"].values())
    if mode in {"comments", "all"}:
        states.extend(manifest["comment_states"].values())
    manifest["state"] = "complete" if states and all(str(value).startswith("complete") for value in states) else "partial"
    manifest["finished_at"] = utc_now()
    atomic_write_json(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible Xiaohongshu note facts, media and comments")
    parser.add_argument("mode", choices=["note", "comments", "all"])
    parser.add_argument("--note", action="append", required=True, help="Repeat for more note URLs or note ids")
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", default="images,cover", help="images,video,cover,none")
    parser.add_argument("--comment-limit", type=int, default=0, help="0 means continue until the visible panel is exhausted")
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true", help="Experimental: expand source-visible replies")
    parser.add_argument("--retain-author-display", action="store_true", help="Retain comment display names; note author remains visible by default")
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect(
            note_targets=args.note,
            profile_dir=args.profile_dir,
            out=args.out,
            mode=args.mode,
            assets=normalize_assets(args.assets),
            comment_limit=max(0, args.comment_limit),
            max_scroll_actions=max(1, args.max_scroll_actions),
            include_replies=args.include_replies,
            retain_author_display=args.retain_author_display,
            login_wait=max(0, args.login_wait),
            resume=args.resume,
            chrome_path=args.chrome_path,
            max_asset_mb=max(1, args.max_asset_mb),
        )
    except (CollectionError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
