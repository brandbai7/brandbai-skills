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
from urllib.parse import urlencode, urlparse

from collector_core import (
    CollectionError,
    atomic_write_json,
    canonical_note_id,
    canonical_note_url,
    canonical_profile_id,
    canonical_profile_url,
    comment_completion_state,
    derived_id,
    freeze_search_results,
    normalize_note_targets,
    safe_filename,
    sanitize_media_url,
    select_profile_notes,
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
  const tags = [...body.matchAll(/#([^#\s]+)/g)].map((match) => '#' + match[1]);
  const mentions = [...body.matchAll(/@([^@#\s]+)/g)].map((match) => '@' + match[1]);

  const mediaRoot = root.querySelector('.media-container') || root;
  const images = [];
  const imageSeen = new Set();
  for (const image of [...mediaRoot.querySelectorAll('img')]) {
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
  for (const video of [...mediaRoot.querySelectorAll('video,video source')]) {
    const source = video.currentSrc || video.src || video.getAttribute('src') || '';
    if (source.startsWith('blob:')) hasBlobVideo = true;
    if (!/^https?:\/\//i.test(source)) continue;
    const key = source.split('?')[0];
    if (videoSeen.has(key)) continue;
    videoSeen.add(key);
    videos.push({
      src: source,
      candidates: [source],
      width: video.videoWidth || video.clientWidth || 0,
      height: video.videoHeight || video.clientHeight || 0,
    });
  }

  // Dynamic photos and some videos replace the public MP4 URL with a blob URL
  // after the player starts. The same public media URL is still present in the
  // page's inline hydration data, so recover only allow-listed MP4 candidates
  // from that visible document and keep signed query parameters in memory.
  if (hasBlobVideo) {
    const player = mediaRoot.querySelector('video');
    const recoveredCandidates = [];
    let scriptText = [...document.scripts].map((script) => script.textContent || '').join('\n');
    scriptText = scriptText
      .replace(/\\u002F/gi, '/')
      .replace(/\\\//g, '/')
      .replace(/\\u0026/gi, '&')
      .replace(/\\u003D/gi, '=')
      .replace(/\\u003F/gi, '?')
      .replace(/&amp;/gi, '&');
    const scriptVideoCandidates = scriptText.match(/https?:\/\/[^"'\s<>]+/g) || [];
    for (const source of scriptVideoCandidates) {
      let parsed;
      try {
        parsed = new URL(source);
      } catch {
        continue;
      }
      const host = parsed.hostname.toLowerCase();
      if (!(host === 'xhscdn.com' || host.endsWith('.xhscdn.com'))) continue;
      if (!/\.mp4$/i.test(parsed.pathname)) continue;
      const key = parsed.pathname;
      if (videoSeen.has(key)) continue;
      videoSeen.add(key);
      recoveredCandidates.push(source);
    }
    if (recoveredCandidates.length) {
      const logicalVideo = videos[0];
      if (logicalVideo) {
        logicalVideo.candidates = [...new Set([logicalVideo.src, ...(logicalVideo.candidates || []), ...recoveredCandidates])];
      } else {
        videos.push({
          src: recoveredCandidates[0],
          candidates: recoveredCandidates,
          width: player?.videoWidth || player?.clientWidth || 0,
          height: player?.videoHeight || player?.clientHeight || 0,
        });
      }
    }
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
    published_at_text: dateText,
    region_text: '',
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


PROFILE_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const profileMatch = location.pathname.match(/\/user\/profile\/([^/?#]+)/);
  const profileId = profileMatch?.[1] || '';
  const redIdText = clean(document.querySelector('.user-redId')?.textContent);
  const regionText = clean(document.querySelector('.user-IP')?.textContent).replace(/^IP属地：?\s*/, '');
  const metrics = {};
  for (const node of [...document.querySelectorAll('.info-part .shows')]) {
    const text = clean(node.parentElement?.innerText || node.parentElement?.textContent || node.innerText || node.textContent);
    const match = text.match(/^(.+?)\s*(关注|粉丝|获赞与收藏)$/);
    if (!match) continue;
    const key = match[2] === '关注' ? 'following' : (match[2] === '粉丝' ? 'followers' : 'likes_and_collects');
    metrics[key] = match[1];
  }
  const notes = [];
  const seen = new Set();
  for (const anchor of [...document.querySelectorAll('a[href*="/explore/"]')]) {
    const href = anchor.getAttribute('href') || '';
    const noteMatch = href.match(/\/explore\/([^/?#]+)/);
    if (!noteMatch || seen.has(noteMatch[1])) continue;
    seen.add(noteMatch[1]);
    const root = anchor.parentElement || anchor;
    const detailLink = [...root.querySelectorAll('a[href]')].find((item) => {
      const value = item.getAttribute('href') || '';
      return value.includes('/' + noteMatch[1]) && value.includes('xsec_');
    });
    const title = clean(root.querySelector('.title')?.innerText || root.querySelector('.title')?.textContent);
    const author = clean(root.querySelector('.author .name')?.textContent || root.querySelector('.name')?.textContent);
    const cover = root.querySelector('img[data-xhs-img], img');
    const cardText = clean(root.innerText || root.textContent);
    notes.push({
      note_id: noteMatch[1],
      rank: notes.length + 1,
      is_pinned: Boolean(root.querySelector('.top-wrapper')) || /^置顶(?:\s|$)/.test(cardText),
      title,
      author_name: author,
      cover_url: cover?.currentSrc || cover?.src || '',
      navigation_url: detailLink?.href || anchor.href,
    });
  }
  return {
    profile: {
      profile_id: profileId,
      display_name: clean(document.querySelector('.user-name')?.textContent),
      xiaohongshu_id: redIdText.replace(/^小红书号：?\s*/, ''),
      region_text: regionText,
      description: clean(document.querySelector('.user-desc')?.innerText || document.querySelector('.user-desc')?.textContent),
      metrics,
    },
    notes,
  };
}
"""


SEARCH_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const results = [];
  const seen = new Set();
  const cards = [...document.querySelectorAll('section.note-item')]
    .sort((left, right) => Number(left.dataset.index || 0) - Number(right.dataset.index || 0));
  for (const card of cards) {
    const anchor = card.querySelector('a[href*="/search_result/"]');
    const href = anchor?.getAttribute('href') || '';
    const match = href.match(/\/search_result\/([^/?#]+)/);
    if (!match || seen.has(match[1])) continue;
    seen.add(match[1]);
    const title = clean(card.querySelector('.title')?.innerText || card.querySelector('.title')?.textContent);
    const authorLink = card.querySelector('a[href*="/user/profile/"]');
    const authorMatch = (authorLink?.getAttribute('href') || '').match(/\/user\/profile\/([^/?#]+)/);
    const cover = [...card.querySelectorAll('img')].find((image) =>
      /^https?:\/\//i.test(image.currentSrc || image.src || '') && !/avatar/i.test(image.className || '')
    );
    const cardText = clean(card.innerText || card.textContent);
    results.push({
      note_id: match[1],
      rank: results.length + 1,
      title,
      author: clean(card.querySelector('.name')?.textContent),
      author_platform_id: authorMatch?.[1] || '',
      published_at_text: clean(card.querySelector('.time')?.textContent),
      like_count_text: clean(card.querySelector('.count')?.textContent),
      note_type: card.querySelector('.play-icon, use[href="#play-s"], use[xlink\\:href="#play-s"]') ? 'video' : 'image',
      promoted_state: /(?:广告|赞助|推广)/.test(cardText) ? 'observed_visible_mark' : 'not_observed',
      cover_url: cover?.currentSrc || cover?.src || '',
      navigation_url: anchor.href,
    });
  }
  const relatedQueries = [];
  const relatedSeen = new Set();
  for (const node of [...document.querySelectorAll('.query-note-item .item-text')]) {
    const value = clean(node.textContent);
    if (value && !relatedSeen.has(value)) {
      relatedSeen.add(value);
      relatedQueries.push(value);
    }
  }
  return {
    keyword: clean(document.querySelector('input[placeholder="搜索小红书"]')?.value),
    tab: clean(document.querySelector('.channel.active')?.textContent) || '全部',
    filters: [...document.querySelectorAll('button.tab.active')].map((item) => clean(item.textContent)).filter(Boolean),
    results,
    related_queries: relatedQueries,
  };
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


def _public_profile_selection(selection: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in selection.items() if key != "selected"}
    public_rows: list[dict[str, Any]] = []
    for record in selection.get("selected") or []:
        note_id = str(record.get("note_id") or "")
        cover_url = ""
        if record.get("cover_url"):
            try:
                cover_url, _ = sanitize_media_url(str(record["cover_url"]))
            except CollectionError:
                cover_url = ""
        public_rows.append({
            "note_id": note_id,
            "rank": int(record.get("rank") or 0),
            "is_pinned": bool(record.get("is_pinned")),
            "selection_reason": str(record.get("selection_reason") or ""),
            "title": str(record.get("title") or ""),
            "author_name": str(record.get("author_name") or ""),
            "cover_url": cover_url,
            "canonical_url": canonical_note_url(note_id),
        })
    public["selected"] = public_rows
    return public


def _public_search_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in snapshot.items() if key != "results"}
    public_rows: list[dict[str, Any]] = []
    for record in snapshot.get("results") or []:
        note_id = str(record.get("note_id") or "")
        cover_url = ""
        if record.get("cover_url"):
            try:
                cover_url, _ = sanitize_media_url(str(record["cover_url"]))
            except CollectionError:
                cover_url = ""
        public_rows.append({
            "search_snapshot_id": str(record.get("search_snapshot_id") or snapshot.get("search_snapshot_id") or ""),
            "note_id": note_id,
            "rank": int(record.get("rank") or 0),
            "title": str(record.get("title") or ""),
            "author": str(record.get("author") or ""),
            "author_platform_id": str(record.get("author_platform_id") or ""),
            "published_at_text": str(record.get("published_at_text") or ""),
            "like_count_text": str(record.get("like_count_text") or ""),
            "note_type": str(record.get("note_type") or "unknown"),
            "promoted_state": str(record.get("promoted_state") or "not_observed"),
            "cover_url": cover_url,
            "canonical_url": canonical_note_url(note_id),
        })
    public["results"] = public_rows
    return public


def _wait_for_login_or_ready(page: Any, selector: str, login_wait: int) -> bool:
    """Wait for manual login without forcing users to sit through the full timeout."""
    if page.locator(selector).count():
        return True
    if login_wait <= 0:
        return False
    print(
        f"Visible Chrome is ready. Complete login or access confirmation within {login_wait} seconds.",
        flush=True,
    )
    elapsed = 0
    while elapsed < login_wait:
        step = min(1, login_wait - elapsed)
        page.wait_for_timeout(step * 1_000)
        elapsed += step
        if page.locator(selector).count():
            return True
        if page.get_by_role("link", name="我", exact=True).count():
            page.reload(wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(2_500)
            return bool(page.locator(selector).count())
    page.reload(wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(2_500)
    return bool(page.locator(selector).count())


def _discover_search_results(
    page: Any,
    keyword: str,
    *,
    tab: str,
    filters: list[str],
    limit: int,
    max_scroll_actions: int,
    login_wait: int,
) -> dict[str, Any]:
    query = str(keyword or "").strip()
    if not query:
        raise CollectionError("Search keyword must not be empty")
    if tab not in {"全部", "图文", "视频"}:
        raise CollectionError("Search tab must be one of: 全部, 图文, 视频")
    requested_filters = filters or ["综合"]
    if requested_filters != ["综合"]:
        raise CollectionError("The current stable route supports the default 综合 search ordering only")
    navigation_url = "https://www.xiaohongshu.com/search_result?" + urlencode({
        "keyword": query,
        "source": "web_search_result_notes",
    })
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_500)
    _wait_for_login_or_ready(page, 'a[href*="/search_result/"]', login_wait)
    for label in ["滑动验证", "安全验证", "请完成验证", "访问频繁"]:
        if page.get_by_text(label, exact=False).count():
            raise CollectionError("Xiaohongshu requires manual verification in the visible Chrome window")
    if tab != "全部":
        candidates = page.locator("div.channel", has_text=tab)
        if not candidates.count():
            raise CollectionError(f"The requested search tab is not visible: {tab}")
        candidates.first.click()
        page.wait_for_timeout(2_500)

    records_by_id: dict[str, dict[str, Any]] = {}
    related_queries: list[str] = []
    no_growth = 0
    scroll_actions = 0
    observed_tab = tab
    observed_filters: list[str] = []
    while scroll_actions <= max_scroll_actions:
        raw = page.evaluate(SEARCH_SCRIPT) or {}
        observed_tab = str(raw.get("tab") or observed_tab)
        observed_filters = [str(value) for value in raw.get("filters") or [] if str(value)]
        before = len(records_by_id)
        for record in raw.get("results") or []:
            note_id = str(record.get("note_id") or "").strip()
            if note_id and note_id not in records_by_id:
                row = dict(record)
                row["rank"] = len(records_by_id) + 1
                records_by_id[note_id] = row
        for value in raw.get("related_queries") or []:
            text = str(value or "").strip()
            if text and text not in related_queries:
                related_queries.append(text)
        if len(records_by_id) >= limit:
            break
        no_growth = no_growth + 1 if len(records_by_id) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            break
        page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})")
        page.wait_for_timeout(900)
        scroll_actions += 1
    if not records_by_id:
        raise CollectionError("No visible Xiaohongshu search-result notes were found")
    if observed_tab != tab:
        raise CollectionError(f"Search tab activation could not be verified: requested {tab}, observed {observed_tab}")
    if "综合" not in observed_filters:
        raise CollectionError("Default 综合 search ordering could not be verified")
    snapshot = freeze_search_results(
        records_by_id.values(), keyword=query, tab=observed_tab, filters=["综合"], limit=limit,
        related_queries=related_queries, captured_at=utc_now(),
    )
    snapshot.update({
        "schema_version": "1.0",
        "discovered_count": len(records_by_id),
        "scroll_actions": scroll_actions,
        "completion_basis": "requested_first_n_visible_results" if snapshot["state"].startswith("complete") else "scroll_or_growth_budget_exhausted",
    })
    return snapshot


def _discover_profile_notes(
    page: Any,
    navigation_url: str,
    *,
    recent: int,
    max_scroll_actions: int,
    login_wait: int,
) -> dict[str, Any]:
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_500)
    _wait_for_login_or_ready(page, 'a[href*="/explore/"]', login_wait)
    for label in ["滑动验证", "安全验证", "请完成验证", "访问频繁"]:
        if page.get_by_text(label, exact=False).count():
            raise CollectionError("Xiaohongshu requires manual verification in the visible Chrome window")

    records_by_id: dict[str, dict[str, Any]] = {}
    profile: dict[str, Any] = {}
    no_growth = 0
    scroll_actions = 0
    while scroll_actions <= max_scroll_actions:
        raw = page.evaluate(PROFILE_SCRIPT) or {}
        profile = dict(raw.get("profile") or profile)
        before = len(records_by_id)
        for record in raw.get("notes") or []:
            note_id = str(record.get("note_id") or "").strip()
            if note_id and note_id not in records_by_id:
                records_by_id[note_id] = dict(record)
        discovered = list(records_by_id.values())
        selection = select_profile_notes(discovered, recent)
        if selection["state"] == "complete_visible_pinned_plus_recent_n":
            break
        no_growth = no_growth + 1 if len(records_by_id) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            break
        page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})")
        page.wait_for_timeout(800)
        scroll_actions += 1

    if not records_by_id:
        raise CollectionError("No visible Xiaohongshu profile notes were found")
    selection = select_profile_notes(records_by_id.values(), recent)
    profile_id = str(profile.get("profile_id") or canonical_profile_id(navigation_url))
    captured_at = utc_now()
    selection.update({
        "schema_version": "1.0",
        "profile_selection_id": derived_id("profile-selection", profile_id, recent, captured_at),
        "profile_id": profile_id,
        "canonical_url": canonical_profile_url(profile_id),
        "profile": profile,
        "discovered_count": len(records_by_id),
        "scroll_actions": scroll_actions,
        "captured_at": captured_at,
        "completion_basis": "enough_recent_notes" if selection["state"].startswith("complete") else "scroll_or_growth_budget_exhausted",
    })
    return selection


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


def _split_date_region_text(value: str) -> tuple[str, str]:
    """Split only an explicit or semantically credible Xiaohongshu region."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return "", ""
    explicit = re.match(r"^(.*?)\s*IP属地[:：]?\s*([^\s]+)\s*$", text)
    if explicit:
        return explicit.group(1).strip(), explicit.group(2).strip()
    parts = text.split(" ")
    if len(parts) < 2:
        return text, ""
    region = parts[-1]
    published = " ".join(parts[:-1])
    published_looks_like_date = bool(re.search(
        r"(?:编辑于|刚刚|昨天|前天|\d+\s*(?:分钟|小时|天)前|\d{1,4}[-/.年]\d{1,2}|\d{1,2}:\d{2})",
        published,
    ))
    region_looks_like_text = any(char.isalpha() for char in region) and not bool(re.search(r"[\d:./-]", region))
    return (published, region) if published_looks_like_date and region_looks_like_text else (text, "")


def _media_dimensions(body: bytes, kind: str) -> dict[str, int]:
    """Read final-file dimensions without trusting page labels."""
    if kind == "video":
        cursor = 0
        while True:
            type_offset = body.find(b"tkhd", cursor)
            if type_offset < 0:
                break
            box_offset = type_offset - 4
            cursor = type_offset + 4
            if box_offset < 0 or box_offset + 8 > len(body):
                continue
            size = int.from_bytes(body[box_offset:box_offset + 4], "big")
            if size == 1:
                if box_offset + 16 > len(body) or int.from_bytes(body[box_offset + 8:box_offset + 12], "big") != 0:
                    continue
                size = int.from_bytes(body[box_offset + 12:box_offset + 16], "big")
            box_end = box_offset + size
            if size < 40 or box_end > len(body):
                continue
            width = round(int.from_bytes(body[box_end - 8:box_end - 4], "big") / 65536)
            height = round(int.from_bytes(body[box_end - 4:box_end], "big") / 65536)
            if 0 < width <= 16384 and 0 < height <= 16384:
                return {"width": width, "height": height}
        return {}

    if body.startswith(b"\x89PNG\r\n\x1a\n") and len(body) >= 24:
        return {"width": int.from_bytes(body[16:20], "big"), "height": int.from_bytes(body[20:24], "big")}
    if body[:6] in {b"GIF87a", b"GIF89a"} and len(body) >= 10:
        return {"width": int.from_bytes(body[6:8], "little"), "height": int.from_bytes(body[8:10], "little")}
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP" and len(body) >= 30:
        chunk = body[12:16]
        if chunk == b"VP8X":
            return {
                "width": 1 + int.from_bytes(body[24:27], "little"),
                "height": 1 + int.from_bytes(body[27:30], "little"),
            }
        if chunk == b"VP8L" and len(body) >= 25 and body[20] == 0x2F:
            bits = int.from_bytes(body[21:25], "little")
            return {"width": (bits & 0x3FFF) + 1, "height": ((bits >> 14) & 0x3FFF) + 1}
        marker = body.find(b"\x9d\x01\x2a", 20, min(len(body), 128))
        if marker >= 0 and marker + 7 <= len(body):
            return {
                "width": int.from_bytes(body[marker + 3:marker + 5], "little") & 0x3FFF,
                "height": int.from_bytes(body[marker + 5:marker + 7], "little") & 0x3FFF,
            }
    if body.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(body):
            if body[offset] != 0xFF:
                offset += 1
                continue
            marker = body[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(body):
                break
            segment_length = int.from_bytes(body[offset:offset + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and offset + 7 <= len(body):
                return {
                    "width": int.from_bytes(body[offset + 5:offset + 7], "big"),
                    "height": int.from_bytes(body[offset + 3:offset + 5], "big"),
                }
            if segment_length < 2:
                break
            offset += segment_length
    return {}


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
    result = {
        "local_file": str(target),
        "source_url": clean_url,
        "source_url_query_redacted": redacted,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "status": "downloaded",
    }
    result.update(_media_dimensions(body, kind))
    return result


def _load_note(page: Any, navigation_url: str, login_wait: int) -> dict[str, Any]:
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    _wait_for_login_or_ready(page, ".note-container", login_wait)
    for label in ["滑动验证", "安全验证", "请完成验证", "访问频繁"]:
        if page.get_by_text(label, exact=False).count():
            raise CollectionError("Xiaohongshu requires manual verification in the visible Chrome window")
    try:
        page.locator(".note-container").wait_for(state="visible", timeout=25_000)
    except Exception as exc:
        if not urlparse(navigation_url).query:
            raise CollectionError(
                "No visible Xiaohongshu note detail was found. Open the note from a visible list page and copy the full current address before retrying"
            ) from exc
        raise CollectionError("No visible Xiaohongshu note detail was found") from exc
    try:
        page.locator(
            ".note-container .media-container video, "
            ".note-container .media-container img, "
            ".note-container video"
        ).first.wait_for(state="attached", timeout=8_000)
    except Exception:
        # Text-only notes and temporarily unavailable optional media remain valid
        # note surfaces; the completion contract below records only observed media.
        pass
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
    selection_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    note_id = canonical_note_id(navigation_url)
    raw = _load_note(page, navigation_url, login_wait)
    author_key = str(raw.get("author_platform_id") or raw.get("author_name") or note_id)
    note_type = "live_photo" if raw.get("images") and raw.get("has_blob_video") else (
        "video" if raw.get("videos") or raw.get("has_blob_video") else ("image" if raw.get("images") else "text")
    )
    published_at_text, region_text = _split_date_region_text(" ".join(filter(None, [
        str(raw.get("published_at_text") or ""),
        str(raw.get("region_text") or ""),
    ])))
    note = {
        "note_id": note_id,
        "title": str(raw.get("title") or ""),
        "body": str(raw.get("body") or ""),
        "author_id": stable_pseudonym(author_key),
        "author_name": str(raw.get("author_name") or ""),
        "note_type": note_type,
        "published_at_text": published_at_text,
        "region_text": region_text,
        "topics": list(raw.get("topics") or []),
        "mentions": list(raw.get("mentions") or []),
        "metrics": dict(raw.get("metrics") or {}),
        "profile_id": str((selection_context or {}).get("profile_id") or ""),
        "profile_rank": int((selection_context or {}).get("rank") or 0),
        "search_snapshot_id": str((selection_context or {}).get("search_snapshot_id") or ""),
        "search_rank": int((selection_context or {}).get("rank") or 0) if (selection_context or {}).get("search_snapshot_id") else 0,
        "search_keyword": str((selection_context or {}).get("keyword") or ""),
        "selection_reason": str((selection_context or {}).get("selection_reason") or "direct_note"),
        "is_pinned": bool((selection_context or {}).get("is_pinned")),
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
            candidate_sources = [source, *(item.get("candidates") or [])]
            candidate_sources = list(dict.fromkeys(str(value or "") for value in candidate_sources if str(value or "")))
            last_error: Exception | None = None
            for candidate_source in candidate_sources:
                try:
                    downloaded = _download_asset(
                        context,
                        candidate_source,
                        out / "04_笔记素材" / note_id / f"{order:03d}_{kind}",
                        kind=kind,
                        max_bytes=max_asset_bytes,
                    )
                    downloaded["local_file"] = str(Path(downloaded["local_file"]).relative_to(out))
                    row.update(downloaded)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
            if last_error is not None:
                row["status"] = "failed"
                row["error_reason"] = type(last_error).__name__
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


def _collect_visible_list_records(
    context: Any,
    out: Path,
    records: list[dict[str, Any]],
    *,
    source_kind: str,
    assets: list[str],
    resume: bool,
    max_asset_bytes: int,
) -> dict[str, str]:
    """Save only facts already visible on a profile/search list page.

    This deliberately does not open note detail pages. It mirrors the fast batch
    contract used by the browser extension and reduces navigation volume and
    anti-abuse pressure. Missing detail-only fields remain blank rather than being
    inferred from the card.
    """
    notes_path = out / "data" / "notes.jsonl"
    assets_path = out / "data" / "assets.jsonl"
    known_notes = _read_jsonl_ids(notes_path, "note_id") if resume else set()
    known_assets = _read_jsonl_ids(assets_path, "asset_id") if resume else set()
    if not resume:
        for path in [notes_path, assets_path]:
            if path.exists():
                path.unlink()

    states: dict[str, str] = {}
    for record in records:
        note_id = str(record.get("note_id") or "").strip()
        if not note_id:
            continue
        author_name = str(record.get("author_name") or record.get("author") or "")
        author_key = str(record.get("author_platform_id") or author_name or note_id)
        cover_url = str(record.get("cover_url") or "")
        cover_requested = "cover" in assets
        completion_state = "complete_visible_list_card"
        completion_note = "已保存列表页可见卡片字段；未进入笔记详情页"
        asset_row: dict[str, Any] | None = None
        if cover_url:
            try:
                clean_url, redacted = sanitize_media_url(cover_url)
                asset_row = {
                    "asset_id": f"xhs:{note_id}:cover:001",
                    "note_id": note_id,
                    "kind": "cover",
                    "order": 1,
                    "status": "observed_not_requested",
                    "local_file": "",
                    "source_url": clean_url,
                    "source_url_query_redacted": redacted,
                    "width": 0,
                    "height": 0,
                    "bytes": 0,
                    "sha256": "",
                    "error_reason": "",
                    "requested": cover_requested,
                }
                if cover_requested:
                    try:
                        downloaded = _download_asset(
                            context,
                            cover_url,
                            out / "04_笔记素材" / note_id / "001_cover",
                            kind="image",
                            max_bytes=max_asset_bytes,
                        )
                        downloaded["local_file"] = str(Path(downloaded["local_file"]).relative_to(out))
                        asset_row.update(downloaded)
                    except Exception as exc:
                        asset_row["status"] = "failed"
                        asset_row["error_reason"] = type(exc).__name__
                        completion_state = "partial_cover_failure"
                        completion_note = "列表页卡片字段已保存，但请求的封面未能保存"
            except CollectionError:
                completion_state = "partial_cover_url_unavailable" if cover_requested else completion_state
                completion_note = "列表页卡片字段已保存，但封面地址不可交付" if cover_requested else completion_note
        elif cover_requested:
            completion_state = "partial_cover_not_observed"
            completion_note = "列表页卡片字段已保存，但当前卡片未观察到封面地址"

        rank = int(record.get("rank") or 0)
        search_snapshot_id = str(record.get("search_snapshot_id") or "")
        note = {
            "note_id": note_id,
            "title": str(record.get("title") or ""),
            "body": "",
            "author_id": stable_pseudonym(author_key),
            "author_name": author_name,
            "note_type": str(record.get("note_type") or "unknown"),
            "published_at_text": str(record.get("published_at_text") or ""),
            "region_text": "",
            "topics": [],
            "mentions": [],
            "metrics": {
                "likes": str(record.get("like_count_text") or ""),
                "collects": "",
                "comments": "",
                "shares": "",
            },
            "profile_id": str(record.get("profile_id") or ""),
            "profile_rank": rank if source_kind == "profile" else 0,
            "search_snapshot_id": search_snapshot_id,
            "search_rank": rank if source_kind == "search" else 0,
            "search_keyword": str(record.get("keyword") or ""),
            "selection_reason": str(record.get("selection_reason") or f"{source_kind}_list_card"),
            "is_pinned": bool(record.get("is_pinned")),
            "canonical_url": canonical_note_url(note_id),
            "collected_at": utc_now(),
            "completion_state": completion_state,
            "completion_note": completion_note,
            "detail_page_opened": False,
            "field_scope": "visible_list_card_only",
        }
        if note_id not in known_notes:
            _append_jsonl(notes_path, [note])
            known_notes.add(note_id)
        if asset_row and asset_row["asset_id"] not in known_assets:
            _append_jsonl(assets_path, [asset_row])
            known_assets.add(asset_row["asset_id"])
        states[note_id] = completion_state
    return states


def collect(
    *,
    note_targets: list[str] | None = None,
    profile_target: str | None = None,
    search_query: str | None = None,
    recent: int = 5,
    max_profile_scroll_actions: int = 80,
    search_limit: int = 10,
    search_tab: str = "全部",
    search_filters: list[str] | None = None,
    max_search_scroll_actions: int = 80,
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

    if sum(bool(value) for value in [note_targets, profile_target, search_query]) != 1:
        raise CollectionError("Choose exactly one source: note targets, one profile target, or one search keyword")
    if (profile_target or search_query) and mode != "batch":
        raise CollectionError("Profile and search collection require mode=batch; list pages are not expanded into note details")
    if note_targets and mode == "batch":
        raise CollectionError("mode=batch is only valid for profile or search list pages")
    targets = normalize_note_targets(note_targets or []) if note_targets else []
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    note_ids = [canonical_note_id(value) for value in targets]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "collector": "brandbai-xiaohongshu-download",
        "collector_version": "0.4.2",
        "mode": mode,
        "target_kind": "search" if search_query else ("profile" if profile_target else "notes"),
        "requested_note_ids": note_ids,
        "profile_selection_state": "not_applicable",
        "search_selection_state": "not_applicable",
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
            selection_by_id: dict[str, dict[str, Any]] = {}
            if profile_target:
                selection = _discover_profile_notes(
                    page,
                    profile_target,
                    recent=max(0, recent),
                    max_scroll_actions=max(0, max_profile_scroll_actions),
                    login_wait=max(0, login_wait),
                )
                public_selection = _public_profile_selection(selection)
                atomic_write_json(out / "data" / "profile_selection.json", public_selection)
                manifest["profile_selection_state"] = selection["state"]
                manifest["profile_selection"] = {
                    "profile_selection_id": selection["profile_selection_id"],
                    "profile_id": selection["profile_id"],
                    "canonical_url": selection["canonical_url"],
                    "pinned_count": selection["pinned_count"],
                    "recent_requested": selection["recent_requested"],
                    "recent_selected": selection["recent_selected"],
                    "selected_count": len(selection["selected"]),
                    "captured_at": selection["captured_at"],
                }
                targets = [str(record.get("navigation_url") or canonical_note_url(str(record["note_id"]))) for record in selection["selected"]]
                manifest["requested_note_ids"] = [str(record["note_id"]) for record in selection["selected"]]
                selection_by_id = {
                    str(record["note_id"]): {**record, "profile_id": selection["profile_id"]}
                    for record in selection["selected"]
                }
                atomic_write_json(manifest_path, manifest)
            elif search_query:
                snapshot = _discover_search_results(
                    page,
                    search_query,
                    tab=search_tab,
                    filters=list(search_filters or ["综合"]),
                    limit=max(1, search_limit),
                    max_scroll_actions=max(0, max_search_scroll_actions),
                    login_wait=max(0, login_wait),
                )
                public_snapshot = _public_search_snapshot(snapshot)
                search_path = out / "data" / "search_snapshots.jsonl"
                if not resume and search_path.exists():
                    search_path.unlink()
                _append_jsonl(search_path, [public_snapshot])
                manifest["search_selection_state"] = snapshot["state"]
                manifest["search_selection"] = {
                    "search_snapshot_id": snapshot["search_snapshot_id"],
                    "keyword": snapshot["keyword"],
                    "tab": snapshot["tab"],
                    "filters": snapshot["filters"],
                    "requested": snapshot["requested"],
                    "saved": snapshot["saved"],
                    "captured_at": snapshot["captured_at"],
                }
                targets = [
                    str(record.get("navigation_url") or canonical_note_url(str(record["note_id"])))
                    for record in snapshot["results"]
                ]
                manifest["requested_note_ids"] = [str(record["note_id"]) for record in snapshot["results"]]
                selection_by_id = {
                    str(record["note_id"]): {
                        **record,
                        "selection_reason": "search_result",
                        "search_snapshot_id": snapshot["search_snapshot_id"],
                        "keyword": snapshot["keyword"],
                    }
                    for record in snapshot["results"]
                }
                atomic_write_json(manifest_path, manifest)
            if mode == "batch":
                if profile_target:
                    list_records = [
                        {**record, "profile_id": selection["profile_id"]}
                        for record in selection["selected"]
                    ]
                    source_kind = "profile"
                else:
                    list_records = [
                        {
                            **record,
                            "search_snapshot_id": snapshot["search_snapshot_id"],
                            "keyword": snapshot["keyword"],
                            "selection_reason": "search_list_card",
                        }
                        for record in snapshot["results"]
                    ]
                    source_kind = "search"
                manifest["note_states"].update(_collect_visible_list_records(
                    context,
                    out,
                    list_records,
                    source_kind=source_kind,
                    assets=assets,
                    resume=resume,
                    max_asset_bytes=max(1, max_asset_mb) * 1024 * 1024,
                ))
                atomic_write_json(manifest_path, manifest)
            for target_index, target in enumerate([] if mode == "batch" else targets):
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
                        selection_context=selection_by_id.get(note_id),
                    )
                    manifest["note_states"][note_id] = note["completion_state"]
                    if comments:
                        manifest["comment_states"][note_id] = comments["state"]
                except Exception as exc:
                    manifest["note_states"][note_id] = "failed_no_visible_note"
                    if mode in {"comments", "all"}:
                        manifest["comment_states"][note_id] = "partial_runtime_error"
                    detail = f": {exc}" if isinstance(exc, CollectionError) and str(exc) else ""
                    manifest["warnings"].append(f"{note_id}: collection failed ({type(exc).__name__}){detail}")
                atomic_write_json(manifest_path, manifest)
        finally:
            context.close()
    states = list(manifest["note_states"].values())
    if profile_target:
        states.insert(0, manifest["profile_selection_state"])
    if search_query:
        states.insert(0, manifest["search_selection_state"])
    if mode in {"comments", "all"}:
        states.extend(manifest["comment_states"].values())
    manifest["state"] = "complete" if states and all(str(value).startswith("complete") for value in states) else "partial"
    manifest["finished_at"] = utc_now()
    atomic_write_json(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible Xiaohongshu note facts, media and comments")
    parser.add_argument("mode", choices=["note", "comments", "all", "batch"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--note", action="append", help="Repeat for more note URLs or note ids")
    source.add_argument("--profile", help="One Xiaohongshu profile URL or profile id")
    source.add_argument("--search", help="One Xiaohongshu search keyword")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned notes; all visible pinned notes are additional")
    parser.add_argument("--max-profile-scroll-actions", type=int, default=80)
    parser.add_argument("--search-limit", type=int, default=10, help="First N source-visible search-result notes")
    parser.add_argument("--search-tab", choices=["全部", "图文", "视频"], default="全部")
    parser.add_argument("--search-filter", action="append", default=None, help="Current stable route supports 综合 only")
    parser.add_argument("--max-search-scroll-actions", type=int, default=80)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", default="images,cover", help="images,video,cover,none")
    parser.add_argument("--comment-limit", type=int, default=0, help="0 means continue until the visible panel is exhausted")
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true", help="Experimental: expand source-visible replies")
    parser.add_argument("--retain-author-display", action="store_true", help="Retain comment display names; note author remains visible by default")
    parser.add_argument(
        "--login-wait", type=int, default=180,
        help="Seconds to allow manual login or access confirmation; continues early when the target becomes visible",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect(
            note_targets=args.note,
            profile_target=args.profile,
            search_query=args.search,
            recent=max(0, args.recent),
            max_profile_scroll_actions=max(0, args.max_profile_scroll_actions),
            search_limit=max(1, args.search_limit),
            search_tab=args.search_tab,
            search_filters=args.search_filter or ["综合"],
            max_search_scroll_actions=max(0, args.max_search_scroll_actions),
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
