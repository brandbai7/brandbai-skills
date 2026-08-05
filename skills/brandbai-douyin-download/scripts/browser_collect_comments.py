#!/usr/bin/env python3
"""Collect Douyin comments through normal browser interactions.

This route intentionally does not generate request signatures, inject cookies, bypass
verification, or expose a remote debugging port.  It launches a user-visible Chrome
profile, observes JSON responses produced by the website itself, and triggers more
pages by scrolling and expanding visible reply controls.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from collector_core import (
    CommentStore,
    as_bool,
    as_int,
    export_bundle,
    find_list,
    find_scalar,
    pick,
    utc_now,
)


PROVIDER = "douyin_web_browser_ui"
VIDEO_ID_RE = re.compile(r"(?:/(?:video|note)/|modal_id=)(\d{10,})")
COMMENT_URL_MARKERS = ("comment/list", "comment_list", "comment/reply", "comment_reply")
REPLY_URL_MARKERS = ("comment/list/reply", "comment/reply", "reply/list", "reply_list")
RELATIVE_TIME_RE = re.compile(
    r"^(?:刚刚|\d+(?:秒|分钟|小时|天|周|个月|月|年)前|昨天|前天|\d{1,4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?)"
)
REPLY_COUNT_RE = re.compile(r"(?:展开|查看|更多|继续)?\s*(\d+)\s*条?回复")
DOM_COMMENT_ID_RE = re.compile(r"^(?:\d{8,}|[A-Za-z0-9_-]{16,})$")
DOM_UI_RE = re.compile(
    r"^(?:\.\.\.|…|分享|回复|点赞|举报|置顶|作者|加载中|收起|展开|查看|更多|继续)$"
)
REPLY_EXPANDER_RE = re.compile(
    r"(?:(?:展开|查看|加载|继续).{0,22}(?:条)?回复|\d+\s*条回复|更多回复|回复\s*[（(]?\d+[）)]?)"
)
RUNTIME_TRACE_PATH: Optional[Path] = None
DIAGNOSTIC_TRACE_ENABLED = False


def emit_runtime_event(payload: Dict[str, Any]) -> None:
    event = {"at": utc_now(), **payload}
    line = json.dumps(event, ensure_ascii=False)
    console_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    console_line = line.encode(console_encoding, errors="replace").decode(console_encoding)
    print(console_line, flush=True)
    if RUNTIME_TRACE_PATH is not None:
        with RUNTIME_TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class BrowserRouteError(RuntimeError):
    pass


class ActionBudgetExceeded(BrowserRouteError):
    pass


class ActionBudget:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.used = 0

    def take(self, count: int = 1) -> None:
        if self.used + count > self.limit:
            raise ActionBudgetExceeded(
                f"UI action budget exhausted ({self.used}/{self.limit})"
            )
        self.used += count


def video_id_from(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{10,}", value):
        return value
    match = VIDEO_ID_RE.search(value)
    return match.group(1) if match else ""


def content_kind_from(value: str) -> str:
    """Preserve Douyin's real content route so notes are not forced through /video/."""
    path = urlsplit(value.strip()).path.lower()
    if re.search(r"/note/\d{10,}", path):
        return "note"
    return "video"


def normalize_video_urls(values: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        aweme_id = video_id_from(value)
        if not aweme_id or aweme_id in seen:
            continue
        seen.add(aweme_id)
        content_kind = content_kind_from(value)
        output.append(f"https://www.douyin.com/{content_kind}/{aweme_id}")
    return output


def load_work_rows(path_value: str) -> List[Dict[str, Any]]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise BrowserRouteError(f"works.json not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrowserRouteError(f"Unable to read works.json: {path}") from exc
    rows = payload.get("works") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise BrowserRouteError("works.json must be a list or contain a works list")
    return [row for row in rows if isinstance(row, dict)]


def work_url(row: Dict[str, Any]) -> str:
    source_url = str(row.get("source_url") or "").strip()
    if video_id_from(source_url):
        return source_url
    aweme_id = str(row.get("aweme_id") or "").strip()
    if not video_id_from(aweme_id):
        return ""
    route = "note" if str(row.get("type") or "").strip().lower() in {"图文", "note"} else "video"
    return f"https://www.douyin.com/{route}/{aweme_id}"


def work_seed(row: Dict[str, Any]) -> Dict[str, Any]:
    """Translate works-collector metadata into the comment store's video schema."""
    return {
        "aweme_id": str(row.get("aweme_id") or ""),
        "source_url": work_url(row),
        "author": {"nickname": str(row.get("author") or "")},
        "title": str(row.get("title") or ""),
        "publish_time": row.get("publish_time"),
        "statistics": {
            "digg_count": as_int(row.get("digg_count")),
            "comment_count": as_int(row.get("comment_count")),
            "collect_count": as_int(row.get("collect_count")),
            "share_count": as_int(row.get("share_count")),
        },
        "is_pinned": as_bool(row.get("is_pinned")),
    }


def is_transient_navigation_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "execution context was destroyed",
            "most likely because of a navigation",
            "page.goto: timeout",
            "net::err_aborted",
            "navigation interrupted",
        )
    )


def is_page_crash_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "page crashed",
            "target page, context or browser has been closed",
            "targetclosederror",
        )
    )


def find_chrome_path(explicit: str = "") -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise BrowserRouteError(f"Chrome executable not found: {path}")
        return str(path)
    candidates = []
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("PROGRAMFILES", "")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    if local:
        candidates.append(Path(local) / "Google/Chrome/Application/chrome.exe")
    if program_files:
        candidates.append(Path(program_files) / "Google/Chrome/Application/chrome.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Google/Chrome/Application/chrome.exe")
    for path in candidates:
        if path.is_file():
            return str(path)
    raise BrowserRouteError("Google Chrome was not found; pass --chrome-path")


def safe_request_params(url: str) -> Dict[str, Any]:
    query = parse_qs(urlsplit(url).query)
    allow = ("aweme_id", "item_id", "comment_id", "cursor", "count")
    return {key: query[key][0] for key in allow if query.get(key)}


def classify_comment_payload(url: str, payload: Dict[str, Any]) -> str:
    lower = url.lower()
    if any(marker in lower for marker in REPLY_URL_MARKERS):
        return "reply"
    query = parse_qs(urlsplit(url).query)
    if query.get("comment_id"):
        return "reply"
    if any(marker in lower for marker in COMMENT_URL_MARKERS):
        return "comment"
    items = find_list(payload, ("comments", "comment_list", "replies"), max_depth=7) or []
    if items and isinstance(items[0], dict) and pick(items[0], "cid", "comment_id", default=""):
        return "comment"
    return ""


class ResponseCapture:
    def __init__(self, store: CommentStore) -> None:
        self.store = store
        self.current_aweme_id = ""
        self.responses_observed = 0
        self.comment_responses = 0
        self.dom_duplicates_replaced = 0
        self.last_capture_at = 0.0
        self.errors: List[str] = []

    def set_current_video(self, aweme_id: str) -> None:
        self.current_aweme_id = aweme_id
        self.store.ensure_video(aweme_id)

    def on_response(self, response: Any) -> None:
        url = str(getattr(response, "url", "") or "")
        if "comment" not in url.lower():
            return
        try:
            if int(getattr(response, "status", 0) or 0) != 200:
                return
            content_type = str(
                (getattr(response, "headers", {}) or {}).get("content-type", "")
            ).lower()
            if content_type and "json" not in content_type:
                return
            payload = response.json()
            if not isinstance(payload, dict):
                return
            self.process_payload(url, payload)
        except Exception as exc:  # response bodies can disappear after navigation
            if len(self.errors) < 20:
                self.errors.append(f"{type(exc).__name__}: {exc}")

    def process_payload(self, url: str, payload: Dict[str, Any]) -> int:
        kind = classify_comment_payload(url, payload)
        if not kind:
            return 0
        query = parse_qs(urlsplit(url).query)
        aweme_id = (
            (query.get("aweme_id") or query.get("item_id") or [""])[0]
            or self.current_aweme_id
        )
        if not aweme_id:
            return 0
        self.store.ensure_video(aweme_id)
        items = find_list(
            payload,
            ("comments", "comment_list", "replies", "items"),
            max_depth=8,
        ) or []
        root_comment_id = (query.get("comment_id") or [""])[0]
        inserted = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if kind == "reply":
                inferred_root = root_comment_id or str(
                    pick(item, "reply_id", "root_comment_id", default="") or ""
                )
                if not inferred_root:
                    continue
                self.store.upsert_comment(
                    item,
                    aweme_id,
                    reply_level=1,
                    root_comment_id=inferred_root,
                    parent_comment_id=inferred_root,
                )
            else:
                self.dom_duplicates_replaced += remove_matching_dom_fallback(
                    self.store, item, aweme_id
                )
                self.store.upsert_comment(item, aweme_id, reply_level=0)
            inserted += 1

        cursor = find_scalar(payload, ("cursor", "max_cursor"), max_depth=8)
        has_more_raw = find_scalar(payload, ("has_more", "hasMore", "more"), max_depth=8)
        terminal_known = has_more_raw is not None
        done = terminal_known and not as_bool(has_more_raw)
        entity_id = aweme_id if kind == "comment" else f"{aweme_id}:{root_comment_id}"
        if kind == "comment" or root_comment_id:
            progress_kind = "comments" if kind == "comment" else "replies"
            previous_progress = self.store.get_progress(progress_kind, entity_id)
            if done or not previous_progress.get("done"):
                self.store.set_progress(
                    progress_kind,
                    entity_id,
                    cursor if cursor is not None else "",
                    done,
                    {
                        "done_reason": "exhausted" if done else "browser_response",
                        "route": PROVIDER,
                        "terminal_known": terminal_known,
                    },
                )
        self.store.log_request(
            urlsplit(url).path,
            safe_request_params(url),
            200,
            "",
            "observed_browser_response",
        )
        self.responses_observed += 1
        self.comment_responses += 1
        self.last_capture_at = time.monotonic()
        return inserted


def remove_matching_dom_fallback(
    store: CommentStore, item: Dict[str, Any], aweme_id: str
) -> int:
    """Remove a matching generated DOM row before storing its platform-ID version."""
    text = str(pick(item, "text", "content", "comment_text", default="") or "").strip()
    if not text:
        return 0
    user = pick(item, "user", "author", default={})
    user = user if isinstance(user, dict) else {}
    pseudonym, _ = store.pseudonymize(user)
    cursor = store.conn.execute(
        """
        DELETE FROM comments
        WHERE aweme_id=? AND reply_level=0 AND comment_id LIKE 'generated_%'
          AND text=? AND author_pseudonym=?
        """,
        (aweme_id, text, pseudonym),
    )
    if cursor.rowcount:
        store.conn.commit()
    return max(0, int(cursor.rowcount or 0))


def normalize_dom_comment(raw: Dict[str, Any], aweme_id: str) -> Optional[Dict[str, Any]]:
    """Convert a visible comment card into the shared evidence-store shape."""
    if not isinstance(raw, dict) or not aweme_id:
        return None
    nickname = str(raw.get("nickname") or "").strip()
    user_url = str(raw.get("user_url") or "").strip()
    user_match = re.search(r"/user/([^/?#]+)", user_url)
    sec_uid = user_match.group(1) if user_match else ""
    lines = []
    for value in raw.get("lines") or []:
        line = re.sub(r"\s+", " ", str(value or "")).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)

    create_time = ""
    ip_label = ""
    for line in lines:
        if RELATIVE_TIME_RE.search(line):
            parts = [part.strip() for part in re.split(r"[·•]", line, maxsplit=1)]
            create_time = parts[0]
            if len(parts) > 1:
                ip_label = parts[1]
            break

    text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
    if not text:
        for line in lines:
            if line == nickname or DOM_UI_RE.fullmatch(line) or RELATIVE_TIME_RE.search(line):
                continue
            if REPLY_COUNT_RE.search(line) or re.fullmatch(r"\d+", line):
                continue
            text = line
            break
    if not text:
        return None

    reply_count = as_int(raw.get("reply_count"), 0)
    if reply_count <= 0:
        for line in lines:
            match = REPLY_COUNT_RE.search(line)
            if match:
                reply_count = as_int(match.group(1), 0)
                break
    like_count = as_int(raw.get("like_count"), 0)
    comment_id = str(raw.get("comment_id") or "").strip()
    if not DOM_COMMENT_ID_RE.fullmatch(comment_id):
        comment_id = ""
    return {
        "cid": comment_id,
        "text": text,
        "create_time": create_time,
        "digg_count": like_count,
        "reply_comment_total": reply_count,
        "ip_label": ip_label,
        "user": {"nickname": nickname, "sec_uid": sec_uid},
    }


def extract_visible_dom_comments(page: Any, aweme_id: str) -> List[Dict[str, Any]]:
    """Read only visible top-level comment cards; network responses remain primary."""
    raw_rows = page.evaluate(
        """
        () => {
          const visible = (item) => {
            const rect = item.getBoundingClientRect();
            const style = getComputedStyle(item);
            return rect.bottom > 0 && rect.top < window.innerHeight
              && rect.width > 20 && rect.height > 20
              && style.display !== 'none' && style.visibility !== 'hidden';
          };
          return Array.from(document.querySelectorAll('[data-e2e="comment-item"]'))
          .filter((item) => !item.parentElement?.closest('[data-e2e="comment-item"]') && visible(item))
          .map((item) => {
            const userLink = item.querySelector('a[href*="/user/"]');
            const nickname = (userLink?.innerText || userLink?.getAttribute('title') ||
              userLink?.querySelector('img')?.getAttribute('alt') || '').trim();
            let text = '';
            for (const selector of ['[data-e2e="comment-content"]', '[data-e2e="comment-text"]', '.FduGc_lz']) {
              const node = item.querySelector(selector);
              if (node && !node.querySelector('[data-e2e="comment-item"]')) {
                text = (node.innerText || node.textContent || '').trim();
                if (text) break;
              }
            }
            const replyText = Array.from(item.querySelectorAll('button,[role="button"],span,div'))
              .map((node) => (node.innerText || '').trim())
              .find((value) => /(?:展开|查看|更多|继续)?\\s*\\d+\\s*条?回复/.test(value) && value.length < 30) || '';
            const replyMatch = replyText.match(/(\\d+)\\s*条?回复/);
            const likeNode = item.querySelector('[data-e2e*="like" i], [aria-label*="赞"], [aria-label*="like" i]');
            const likeText = (likeNode?.innerText || likeNode?.textContent || '').trim();
            const idValue = item.getAttribute('data-comment-id') || item.getAttribute('data-id') || '';
            return {
              comment_id: idValue,
              nickname,
              user_url: userLink?.href || userLink?.getAttribute('href') || '',
              text,
              lines: (item.innerText || '').split(/\\r?\\n/),
              reply_count: replyMatch ? Number(replyMatch[1]) : 0,
              like_count: /^\\d+$/.test(likeText) ? Number(likeText) : 0
            };
          });
        }
        """
    )
    output: List[Dict[str, Any]] = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        normalized = normalize_dom_comment(raw, aweme_id)
        if normalized:
            output.append(normalized)
    return output


def upsert_visible_dom_comments(page: Any, store: CommentStore, aweme_id: str) -> int:
    before = store.count_top_level_comments(aweme_id)
    for item in extract_visible_dom_comments(page, aweme_id):
        text = str(item.get("text") or "").strip()
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        pseudonym, _ = store.pseudonymize(user)
        existing = store.conn.execute(
            """
            SELECT 1 FROM comments
            WHERE aweme_id=? AND reply_level=0 AND text=? AND author_pseudonym=?
            LIMIT 1
            """,
            (aweme_id, text, pseudonym),
        ).fetchone()
        if existing:
            continue
        store.upsert_comment(item, aweme_id, reply_level=0)
    reconcile_dom_fallback_duplicates(store, aweme_id)
    return max(0, store.count_top_level_comments(aweme_id) - before)


def reconcile_dom_fallback_duplicates(store: CommentStore, aweme_id: str) -> int:
    """Remove exact and emoji-only DOM duplicates without merging ambiguous comments."""
    cursor = store.conn.execute(
        """
        DELETE FROM comments AS dom
        WHERE dom.aweme_id=? AND dom.reply_level=0 AND dom.comment_id LIKE 'generated_%'
          AND EXISTS (
            SELECT 1 FROM comments AS platform
            WHERE platform.aweme_id=dom.aweme_id AND platform.reply_level=0
              AND platform.comment_id NOT LIKE 'generated_%'
              AND platform.text=dom.text
              AND platform.author_pseudonym=dom.author_pseudonym
          )
        """,
        (aweme_id,),
    )
    removed = max(0, int(cursor.rowcount or 0))

    def comparable_text(value: Any) -> str:
        text = re.sub(r"\[[^\]\r\n]{1,24}\]", "", str(value or ""))
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE).lower()

    generated = list(
        store.conn.execute(
            """
            SELECT comment_id,text,reply_count FROM comments
            WHERE aweme_id=? AND reply_level=0 AND comment_id LIKE 'generated_%'
            """,
            (aweme_id,),
        )
    )
    platform = list(
        store.conn.execute(
            """
            SELECT comment_id,text,reply_count FROM comments
            WHERE aweme_id=? AND reply_level=0 AND comment_id NOT LIKE 'generated_%'
            """,
            (aweme_id,),
        )
    )
    platform_by_key: Dict[Tuple[str, int], List[str]] = {}
    for row in platform:
        key = (comparable_text(row["text"]), as_int(row["reply_count"], 0))
        if key[0]:
            platform_by_key.setdefault(key, []).append(str(row["comment_id"]))
    for row in generated:
        key = (comparable_text(row["text"]), as_int(row["reply_count"], 0))
        matches = platform_by_key.get(key, [])
        if len(matches) != 1:
            continue
        store.conn.execute(
            "DELETE FROM progress WHERE kind='replies' AND entity_id=?",
            (f"{aweme_id}:{row['comment_id']}",),
        )
        deleted = store.conn.execute(
            "DELETE FROM comments WHERE aweme_id=? AND comment_id=?",
            (aweme_id, row["comment_id"]),
        )
        removed += max(0, int(deleted.rowcount or 0))
    if removed:
        store.conn.commit()
    return removed


def comment_surface_state(page: Any) -> Dict[str, Any]:
    result = page.evaluate(
        """
        () => {
          const visible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return rect.bottom > 0 && rect.top < window.innerHeight
              && rect.right > 0 && rect.left < window.innerWidth
              && rect.width > 10 && rect.height > 8
              && style.display !== 'none' && style.visibility !== 'hidden';
          };
          return {
          dom_item_count: document.querySelectorAll('[data-e2e="comment-item"]').length,
          item_count: Array.from(document.querySelectorAll('[data-e2e="comment-item"]'))
            .filter(visible).length,
          list_count: Array.from(document.querySelectorAll('[data-e2e="comment-list"]'))
            .filter(visible).length,
          login_gate: Array.from(document.querySelectorAll('.video-comment-cover__btn,button'))
            .some((node) => {
              const text = (node.innerText || node.textContent || '').trim();
              return /^(?:立即登录|登录后查看|登录后展开|扫码登录)$/.test(text) && visible(node);
            }),
          title: document.title || '',
          url: location.href
          };
        }
        """
    )
    return result if isinstance(result, dict) else {}


def open_comment_panel(page: Any) -> bool:
    """Open the visible comment control when the current Douyin layout hides the panel."""
    marker = f"c{int(time.monotonic() * 1000) % 100000000}"
    try:
        found = page.evaluate(
            r"""
            (marker) => {
              for (const old of document.querySelectorAll('[data-brandbai-comment-tab]')) {
                old.removeAttribute('data-brandbai-comment-tab');
              }
              const visible = (node) => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return rect.bottom > 0 && rect.top < window.innerHeight
                  && rect.right > 0 && rect.left < window.innerWidth
                  && rect.width > 10 && rect.height > 8
                  && style.display !== 'none' && style.visibility !== 'hidden';
              };
              const nodes = Array.from(
                document.querySelectorAll('button,[role="tab"],[role="button"],a,div,span')
              ).filter(visible);
              const exact = nodes.filter((node) => {
                const text = (node.innerText || node.textContent || '').replace(/\s+/g, '').trim();
                return /^评论(?:[（(]?\d+[）)]?)?$/.test(text);
              });
              const minimal = exact.filter((node) => !Array.from(node.children).some((child) => exact.includes(child)));
              let target = minimal[0] || nodes.find((node) => {
                const text = [node.getAttribute('aria-label'), node.getAttribute('title')]
                  .filter(Boolean).join(' ').trim();
                return text.length <= 30 && /评论/.test(text);
              });
              if (!target) return false;
              target = target.closest('button,[role="tab"],[role="button"],a') || target;
              target.setAttribute('data-brandbai-comment-tab', marker);
              return true;
            }
            """,
            marker,
        )
        if not found:
            return False
        node = page.locator(f'[data-brandbai-comment-tab="{marker}"]')
        if not node.count() or not node.is_visible(timeout=300):
            return False
        node.click(timeout=1200)
        return True
    except Exception:
        return False


def wait_for_comment_surface(
    page: Any,
    capture: ResponseCapture,
    budget: ActionBudget,
    wait_seconds: float,
) -> Dict[str, Any]:
    """Allow a human to finish ordinary login/verification in the visible window."""
    deadline = time.monotonic() + max(0.0, wait_seconds)
    attempt = 0
    while True:
        state = comment_surface_state(page)
        if (
            not as_bool(state.get("login_gate"))
            and (
                as_int(state.get("item_count"), 0) > 0
                or as_int(state.get("list_count"), 0) > 0
            )
        ):
            return state
        if attempt % 3 == 0 and open_comment_panel(page):
            budget.take()
        if time.monotonic() >= deadline:
            return state
        attempt += 1
        page.wait_for_timeout(1000)


def extract_visible_video_links(page: Any) -> List[str]:
    values = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href*="/video/"],a[href*="/note/"]'))
          .map((node) => node.href || node.getAttribute('href') || '')
          .filter(Boolean)
        """
    )
    return normalize_video_urls(values if isinstance(values, list) else [])


def scroll_largest_container(page: Any, to_top: bool = False) -> Dict[str, Any]:
    """Move the primary comment surface and report whether the movement reached an edge."""
    result = page.evaluate(
        """
        (toTop) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 40 && r.height > 40 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          let target = document.querySelector('[data-brandbai-comment-scroll="1"]');
          if (target) {
            const style = getComputedStyle(target);
            if (!visible(target) || !/(auto|scroll)/.test(style.overflowY)
                || target.scrollHeight - target.clientHeight <= 80) {
              target.removeAttribute('data-brandbai-comment-scroll');
              target = null;
            }
          }
          if (!target) {
            const explicitCommentList = document.querySelector('[data-e2e="comment-list"]');
            if (explicitCommentList && visible(explicitCommentList)) {
              const style = getComputedStyle(explicitCommentList);
              const overflow = explicitCommentList.scrollHeight - explicitCommentList.clientHeight;
              if (/(auto|scroll)/.test(style.overflowY) && overflow > 80) {
                target = explicitCommentList;
                target.setAttribute('data-brandbai-comment-scroll', '1');
              }
            }
          }
          if (!target) {
            const commentItems = Array.from(document.querySelectorAll('[data-e2e="comment-item"]'))
              .filter((el) => visible(el));
            const commentRects = commentItems.map((el) => el.getBoundingClientRect());
            const candidates = Array.from(document.querySelectorAll('*'))
              .map((el) => {
                if (!visible(el)) return null;
                const style = getComputedStyle(el);
                const overflow = el.scrollHeight - el.clientHeight;
                if (!/(auto|scroll)/.test(style.overflowY) || overflow < 0) return null;
                if (el.matches('[data-e2e="douyin-navigation"]')
                    || el.closest('[data-e2e="douyin-navigation"]')
                    || el.querySelector('[data-e2e="douyin-navigation"]')) return null;
                const rect = el.getBoundingClientRect();
                const descendantComments = el.querySelectorAll('[data-e2e="comment-item"]').length;
                const overlap = commentRects.reduce((sum, itemRect) => {
                  const width = Math.max(0, Math.min(rect.right, itemRect.right) - Math.max(rect.left, itemRect.left));
                  const height = Math.max(0, Math.min(rect.bottom, itemRect.bottom) - Math.max(rect.top, itemRect.top));
                  return sum + width * height;
                }, 0);
                const rightSide = Math.max(0, rect.left) / Math.max(1, window.innerWidth);
                return {
                  el,
                  score: (overflow > 80 ? 1e15 : 0)
                    + descendantComments * 1e12 + overlap * 1e4 + rightSide * 1e6 + overflow
                };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score);
            target = candidates[0]?.el || null;
            if (target) target.setAttribute('data-brandbai-comment-scroll', '1');
          }
          if (target) {
            const before = target.scrollTop;
            target.scrollTop = toTop
              ? 0
              : Math.min(target.scrollTop + Math.max(700, target.clientHeight * 0.85), target.scrollHeight);
            target.dispatchEvent(new Event('scroll', {bubbles: true}));
            const after = target.scrollTop;
            const maxTop = Math.max(0, target.scrollHeight - target.clientHeight);
            return {
              kind: 'container', before, after, height: target.scrollHeight,
              class_name: String(target.className || '').slice(0, 120),
              moved: Math.abs(after - before) > 2,
              at_start: after <= 2,
              at_end: after >= maxTop - 2
            };
          }
          const before = window.scrollY;
          if (toTop) window.scrollTo(0, 0);
          else window.scrollBy(0, Math.max(800, window.innerHeight * 0.85));
          const after = window.scrollY;
          const height = document.documentElement.scrollHeight;
          const maxTop = Math.max(0, height - window.innerHeight);
          return {
            kind: 'window', before, after, height,
            moved: Math.abs(after - before) > 2,
            at_start: after <= 2,
            at_end: after >= maxTop - 2
          };
        }
        """,
        to_top,
    )
    return result if isinstance(result, dict) else {}


def click_reply_expanders(
    page: Any,
    limit: int = 20,
    seen_controls: Optional[Dict[str, int]] = None,
    generation: int = 0,
) -> int:
    # Locator.click dispatches real pointer input. DOM element.click() can be ignored by
    # sites that require trusted user interaction before loading a reply thread.
    seen_controls = seen_controls if seen_controls is not None else {}
    clicked = 0
    scan_deadline = time.monotonic() + max(4.0, min(10.0, limit * 1.2))
    try:
        token = f"b{generation}-{int(time.monotonic() * 1000) % 100000000}"
        controls = page.evaluate(
            r"""
            (token) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.bottom > 0 && r.top < window.innerHeight
                  && r.right > 0 && r.left < window.innerWidth
                  && r.width > 4 && r.height > 4
                  && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const pattern = /(?:(?:展开|查看|加载|继续).{0,22}(?:条)?回复|\d+\s*条回复|更多回复|回复\s*[（(]?\d+[）)]?)/;
              for (const old of document.querySelectorAll('[data-brandbai-reply-control]')) {
                old.removeAttribute('data-brandbai-reply-control');
              }
              const pool = Array.from(
                document.querySelectorAll('button,[role="button"],a,span,div')
              ).filter((el) => visible(el));
              const matches = pool
                .filter((el) => {
                  if (!visible(el)) return false;
                  const label = `${el.innerText || el.textContent || ''} ${el.getAttribute('aria-label') || ''}`
                    .replace(/\s+/g, ' ').trim();
                  return label.length > 0 && label.length <= 60 && pattern.test(label) && !/^收起/.test(label);
                });
              const minimal = matches.filter((el) => !Array.from(el.children).some((child) => matches.includes(child)));
              return minimal.slice(0, 60).map((el, index) => {
                const marker = `${token}-${index}`;
                el.setAttribute('data-brandbai-reply-control', marker);
                const label = `${el.innerText || el.textContent || ''} ${el.getAttribute('aria-label') || ''}`
                  .replace(/\s+/g, ' ').trim();
                const root = el.closest('[data-e2e="comment-item"]');
                const content = root?.querySelector(
                  '[data-e2e="comment-content"], [data-e2e="comment-text"], .FduGc_lz'
                );
                return {
                  marker,
                  label,
                  root_key: (content?.innerText || content?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160)
                };
              });
            }
            """,
            token,
        )
    except Exception:
        return 0
    controls = controls if isinstance(controls, list) else []
    for control in controls:
        if clicked >= limit or time.monotonic() >= scan_deadline:
            break
        try:
            text = re.sub(r"\s+", " ", str(control.get("label") or "")).strip()
            if not text or len(text) > 40 or not REPLY_EXPANDER_RE.search(text):
                continue
            root_key = re.sub(r"\s+", " ", str(control.get("root_key") or "")).strip()
            fingerprint = f"{root_key}|{text}"
            if seen_controls.get(fingerprint) == generation:
                continue
            marker = str(control.get("marker") or "")
            if not marker:
                continue
            node = page.locator(f'[data-brandbai-reply-control="{marker}"]')
            if not node.count() or not node.is_visible(timeout=150):
                continue
            node.scroll_into_view_if_needed(timeout=500)
            node.click(timeout=700)
            seen_controls[fingerprint] = generation
            clicked += 1
        except Exception:
            continue
    return clicked


def visible_reply_ui_samples(page: Any, limit: int = 20) -> List[Dict[str, str]]:
    """Return short visible control-like labels for schema diagnostics."""
    try:
        rows = page.evaluate(
            r"""
            (limit) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.bottom > 0 && r.top < window.innerHeight
                  && r.right > 0 && r.left < window.innerWidth
                  && r.width > 4 && r.height > 4
                  && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const seen = new Set();
              const output = [];
              for (const el of document.querySelectorAll('button,[role="button"],a,span,div')) {
                  if (!visible(el)) continue;
                  const label = `${el.innerText || el.textContent || ''} ${el.getAttribute('aria-label') || ''}`
                    .replace(/\s+/g, ' ').trim();
                  if (!label || label.length > 80 || !/(回复|展开|查看|更多|加载|继续)/.test(label)) continue;
                  const key = `${el.tagName}|${label}`;
                  if (seen.has(key)) continue;
                  seen.add(key);
                  output.push({
                    tag: el.tagName.toLowerCase(),
                    label,
                    role: el.getAttribute('role') || '',
                    data_e2e: el.getAttribute('data-e2e') || ''
                  });
                  if (output.length >= limit) return output;
              }
              return output;
            }
            """,
            limit,
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def visible_short_ui_samples(page: Any, limit: int = 40) -> List[Dict[str, str]]:
    """Capture compact visible labels for diagnosing an unfamiliar comment layout."""
    try:
        rows = page.evaluate(
            r"""
            (limit) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.bottom > 0 && r.top < window.innerHeight
                  && r.right > 0 && r.left < window.innerWidth
                  && r.width > 4 && r.height > 4
                  && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const seen = new Set();
              const output = [];
              for (const el of document.querySelectorAll('button,[role="button"],a,span')) {
                if (!visible(el)) continue;
                const label = `${el.innerText || el.textContent || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`
                  .replace(/\s+/g, ' ').trim();
                if (!label || label.length > 60 || seen.has(label)) continue;
                seen.add(label);
                output.push({
                  tag: el.tagName.toLowerCase(),
                  label,
                  role: el.getAttribute('role') || '',
                  data_e2e: el.getAttribute('data-e2e') || '',
                  class_name: String(el.className || '').slice(0, 100)
                });
                if (output.length >= limit) return output;
              }
              return output;
            }
            """,
            limit,
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def save_runtime_screenshot(page: Any, name: str) -> None:
    if not DIAGNOSTIC_TRACE_ENABLED or RUNTIME_TRACE_PATH is None:
        return
    try:
        page.screenshot(path=str(RUNTIME_TRACE_PATH.with_name(name)), full_page=False)
    except Exception:
        return


def scroll_surface_samples(page: Any, limit: int = 20) -> List[Dict[str, Any]]:
    """Inspect visible scrollable elements once during an explicit diagnostic run."""
    try:
        rows = page.evaluate(
            r"""
            (limit) => Array.from(document.querySelectorAll('*'))
              .map((el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                const overflow = el.scrollHeight - el.clientHeight;
                if (rect.width <= 40 || rect.height <= 40 || style.display === 'none' || style.visibility === 'hidden') return null;
                if (!/(auto|scroll)/.test(style.overflowY) || overflow <= 40) return null;
                return {
                  tag: el.tagName.toLowerCase(),
                  id: el.id || '',
                  class_name: String(el.className || '').slice(0, 180),
                  data_e2e: el.getAttribute('data-e2e') || '',
                  overflow_y: style.overflowY,
                  scroll_top: Math.round(el.scrollTop),
                  client_height: Math.round(el.clientHeight),
                  scroll_height: Math.round(el.scrollHeight),
                  comment_items: el.querySelectorAll('[data-e2e="comment-item"]').length
                };
              })
              .filter(Boolean)
              .sort((a, b) => (b.comment_items - a.comment_items) || (b.scroll_height - b.client_height) - (a.scroll_height - a.client_height))
              .slice(0, limit)
            """,
            limit,
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def discover_creator_videos(
    page: Any,
    creator_url: str,
    wanted: int,
    budget: ActionBudget,
    delay: float,
    idle_rounds: int,
    login_wait: float,
) -> List[str]:
    page.goto(creator_url, wait_until="domcontentloaded")
    discovered: List[str] = []
    seen = set()
    idle = 0
    wait_deadline = time.monotonic() + max(0.0, login_wait)
    while len(discovered) < wanted and (
        idle < idle_rounds or time.monotonic() < wait_deadline
    ):
        budget.take()
        before = len(discovered)
        for url in extract_visible_video_links(page):
            aweme_id = video_id_from(url)
            if aweme_id and aweme_id not in seen:
                seen.add(aweme_id)
                discovered.append(url)
                if len(discovered) >= wanted:
                    break
        if len(discovered) == before and time.monotonic() >= wait_deadline:
            idle += 1
        elif len(discovered) > before:
            idle = 0
        if len(discovered) < wanted:
            scroll_largest_container(page)
            page.wait_for_timeout(max(250, int(delay * 1000)))
    return discovered[:wanted]


def replies_complete(store: CommentStore, aweme_id: str) -> bool:
    for root in store.root_comments_with_replies(aweme_id):
        progress = store.get_progress("replies", f"{aweme_id}:{root['comment_id']}")
        if not progress.get("done"):
            return False
    return True


def reply_floor_snapshot(store: CommentStore, aweme_id: str) -> Dict[str, Any]:
    roots = store.root_comments_with_replies(aweme_id)
    pending_ids: List[str] = []
    terminal = 0
    for root in roots:
        root_id = str(root["comment_id"])
        progress = store.get_progress("replies", f"{aweme_id}:{root_id}")
        if progress.get("done"):
            terminal += 1
        else:
            pending_ids.append(root_id)
    saved_replies = int(
        store.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND reply_level>0",
            (aweme_id,),
        ).fetchone()[0]
    )
    return {
        "total_floors": len(roots),
        "terminal_floors": terminal,
        "pending_floors": len(pending_ids),
        "pending_ids": pending_ids,
        "saved_replies": saved_replies,
    }


def hydrate_comment_surface_for_replies(
    page: Any,
    store: CommentStore,
    aweme_id: str,
    budget: ActionBudget,
    delay: float,
    idle_rounds: int,
) -> Dict[str, Any]:
    """Reload the current page's comment surface before revisiting saved reply floors.

    A resumed database can already be terminal while a freshly opened browser tab only
    contains the first screen of comments.  Reply controls are UI-bound, so the tab must
    be hydrated independently of the historical database checkpoint.
    """
    database_count = store.count_top_level_comments(aweme_id)
    current_items = as_int(comment_surface_state(page).get("dom_item_count"), 0)
    if database_count <= max(40, current_items + 5):
        return {
            "needed": False,
            "database_comments": database_count,
            "page_items": current_items,
            "rounds": 0,
        }

    emit_runtime_event(
        {
            "event": "reply_surface_hydration_start",
            "aweme_id": aweme_id,
            "database_comments": database_count,
            "page_items": current_items,
        }
    )
    budget.take()
    scroll_largest_container(page, to_top=True)
    page.wait_for_timeout(max(500, int(delay * 1000)))
    stable_end_rounds = 0
    rounds = 0
    previous_state: Optional[Tuple[str, int, int, int]] = None
    max_rounds = max(16, idle_rounds * 12)
    while rounds < max_rounds and stable_end_rounds < 2:
        rounds += 1
        budget.take()
        scroll_state = scroll_largest_container(page)
        page.wait_for_timeout(max(400, int(delay * 1000)))
        surface = comment_surface_state(page)
        state = (
            str(scroll_state.get("kind") or ""),
            int(scroll_state.get("after") or 0),
            int(scroll_state.get("height") or 0),
            as_int(surface.get("dom_item_count"), 0),
        )
        at_end = as_bool(scroll_state.get("at_end"))
        unchanged = previous_state == state
        if str(scroll_state.get("kind") or "") == "container" and at_end and unchanged:
            stable_end_rounds += 1
        else:
            stable_end_rounds = 0
        previous_state = state

    final_items = as_int(comment_surface_state(page).get("dom_item_count"), 0)
    result = {
        "needed": True,
        "database_comments": database_count,
        "page_items": final_items,
        "rounds": rounds,
        "stable_end": stable_end_rounds >= 2,
    }
    emit_runtime_event(
        {"event": "reply_surface_hydration_end", "aweme_id": aweme_id, **result}
    )
    return result


def collect_reply_floors_ui(
    page: Any,
    store: CommentStore,
    aweme_id: str,
    budget: ActionBudget,
    delay: float,
    idle_rounds: int,
    reply_batch_size: int,
    reply_sweeps: int,
) -> Dict[str, Any]:
    """Revisit the whole comment surface until every visible reply floor terminates."""
    hydrate_comment_surface_for_replies(
        page,
        store,
        aweme_id,
        budget,
        delay,
        idle_rounds,
    )
    reconcile_dom_fallback_duplicates(store, aweme_id)
    total_clicked = 0
    sweeps_run = 0
    no_progress_sweeps = 0
    for sweep_index in range(max(1, reply_sweeps)):
        before_sweep = reply_floor_snapshot(store, aweme_id)
        if before_sweep["pending_floors"] == 0:
            break
        sweeps_run = sweep_index + 1
        emit_runtime_event(
            {
                "event": "reply_sweep_start",
                "aweme_id": aweme_id,
                "sweep": sweeps_run,
                "pending_floors": before_sweep["pending_floors"],
                "saved_replies": before_sweep["saved_replies"],
            }
        )
        budget.take()
        if DIAGNOSTIC_TRACE_ENABLED:
            emit_runtime_event(
                {
                    "event": "scroll_surface_samples",
                    "aweme_id": aweme_id,
                    "sweep": sweeps_run,
                    "samples": scroll_surface_samples(page),
                }
            )
        scroll_largest_container(page, to_top=True)
        page.wait_for_timeout(max(300, int(delay * 1000)))
        save_runtime_screenshot(page, f"reply_ui_{aweme_id}_top.png")
        if DIAGNOSTIC_TRACE_ENABLED:
            emit_runtime_event(
                {
                    "event": "reply_ui_samples",
                    "aweme_id": aweme_id,
                    "sweep": sweeps_run,
                    "samples": visible_reply_ui_samples(page),
                }
            )
        seen_controls: Dict[str, int] = {}
        idle = 0
        end_rounds = 0
        ui_round = 0
        previous_state: Optional[Tuple[int, int, int, int]] = None
        while idle < max(2, idle_rounds):
            ui_round += 1
            snapshot = reply_floor_snapshot(store, aweme_id)
            if snapshot["pending_floors"] == 0:
                return {
                    **snapshot,
                    "sweeps_run": sweeps_run,
                    "reply_controls_clicked": total_clicked,
                }
            generation = (
                int(snapshot["saved_replies"]) * 100000
                + int(snapshot["terminal_floors"])
            )
            budget.take()
            clicked = click_reply_expanders(
                page,
                reply_batch_size,
                seen_controls,
                generation,
            )
            if clicked:
                budget.take(clicked)
                total_clicked += clicked
            page.wait_for_timeout(max(300, int(delay * 1000)))
            upsert_visible_dom_comments(page, store, aweme_id)
            current = reply_floor_snapshot(store, aweme_id)
            scroll_state = scroll_largest_container(page)
            page.wait_for_timeout(max(250, int(delay * 700)))
            if DIAGNOSTIC_TRACE_ENABLED:
                samples = visible_reply_ui_samples(page)
                save_runtime_screenshot(page, f"reply_ui_{aweme_id}_latest.png")
                emit_runtime_event(
                    {
                        "event": "reply_ui_round",
                        "aweme_id": aweme_id,
                        "sweep": sweeps_run,
                        "round": ui_round,
                        "scroll": scroll_state,
                        "samples": samples,
                        "short_ui_samples": [] if samples else visible_short_ui_samples(page),
                    }
                )
            state = (
                int(current["terminal_floors"]),
                int(current["saved_replies"]),
                int(scroll_state.get("after") or 0),
                int(scroll_state.get("height") or 0),
            )
            if previous_state is None or state != previous_state or clicked:
                idle = 0
            else:
                idle += 1
            previous_state = state
            if as_bool(scroll_state.get("at_end")) and not clicked:
                end_rounds += 1
            else:
                end_rounds = 0
            if end_rounds >= 2:
                break

        after_sweep = reply_floor_snapshot(store, aweme_id)
        emit_runtime_event(
            {
                "event": "reply_sweep_end",
                "aweme_id": aweme_id,
                "sweep": sweeps_run,
                "pending_floors": after_sweep["pending_floors"],
                "terminal_floors": after_sweep["terminal_floors"],
                "saved_replies": after_sweep["saved_replies"],
                "reply_controls_clicked": total_clicked,
            }
        )
        improved = (
            int(after_sweep["terminal_floors"]) > int(before_sweep["terminal_floors"])
            or int(after_sweep["saved_replies"]) > int(before_sweep["saved_replies"])
        )
        no_progress_sweeps = 0 if improved else no_progress_sweeps + 1
        if no_progress_sweeps >= 2:
            break

    final = reply_floor_snapshot(store, aweme_id)
    for root_id in final["pending_ids"]:
        progress = store.get_progress("replies", f"{aweme_id}:{root_id}")
        if progress.get("done"):
            continue
        store.set_progress(
            "replies",
            f"{aweme_id}:{root_id}",
            progress.get("cursor", "0"),
            False,
            {
                "done_reason": "reply_ui_sweeps_incomplete",
                "route": PROVIDER,
                "terminal_known": False,
                "sweeps_run": sweeps_run,
            },
        )
    return {
        **final,
        "sweeps_run": sweeps_run,
        "reply_controls_clicked": total_clicked,
    }


def settle_content_navigation(
    page: Any,
    content_url: str,
    aweme_id: str,
    delay: float,
    settle_seconds: float = 6.0,
) -> str:
    """Accept Douyin's ordinary /video/ to /note/ redirect and wait for a stable route."""
    try:
        page.goto(content_url, wait_until="domcontentloaded")
    except Exception as exc:
        current_url = str(getattr(page, "url", "") or "")
        if not is_transient_navigation_error(exc) or video_id_from(current_url) != aweme_id:
            raise

    deadline = time.monotonic() + max(1.0, settle_seconds)
    last_url = ""
    stable_rounds = 0
    current_url = str(getattr(page, "url", "") or "")
    while time.monotonic() < deadline:
        page.wait_for_timeout(max(250, min(750, int(delay * 500))))
        current_url = str(getattr(page, "url", "") or "")
        if video_id_from(current_url) == aweme_id and current_url == last_url:
            stable_rounds += 1
            if stable_rounds >= 2:
                return current_url
        else:
            stable_rounds = 0
        last_url = current_url
    return current_url or content_url


def clean_page_title(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*-\s*[^-]{1,40}于\d{8}发布在抖音，.*$", "", text).strip()
    text = re.sub(r"\s*-\s*抖音(?:精选)?(?:\s*[-|].*)?$", "", text).strip()
    if text.lower() in {"", "抖音", "douyin", "抖音-记录美好生活"}:
        return ""
    return text


def safe_page_title(page: Any, delay: float) -> str:
    """Wait for the SPA caption and prefer visible/meta text over a transient blank title."""
    for _ in range(6):
        try:
            candidates = page.evaluate(
                """
                () => {
                  const visible = [
                    '[data-e2e="video-desc"]',
                    '[data-e2e="video-title"]',
                    '[data-e2e="note-desc"]',
                    'h1'
                  ].map((selector) => document.querySelector(selector)?.innerText || '');
                  const meta = [
                    document.querySelector('meta[property="og:title"]')?.content || '',
                    document.querySelector('meta[name="description"]')?.content || '',
                    document.querySelector('meta[name="title"]')?.content || ''
                  ];
                  return [...visible, ...meta, document.title || ''];
                }
                """
            )
            if not isinstance(candidates, list):
                candidates = []
            candidates.append(page.title() or "")
            for candidate in candidates:
                title = clean_page_title(candidate)
                if title:
                    return title
        except Exception as exc:
            if not is_transient_navigation_error(exc):
                raise
        page.wait_for_timeout(max(250, int(delay * 500)))
    return ""


def pause_page_media(page: Any) -> None:
    """Reduce video/audio decoding pressure without changing page data or identity."""
    try:
        page.evaluate(
            """
            () => {
              for (const media of document.querySelectorAll('video,audio')) {
                media.muted = true;
                media.pause();
              }
            }
            """
        )
    except Exception:
        # Media pausing is an optimization; collection correctness must not depend on it.
        return


def collect_video_ui(
    page: Any,
    video_url: str,
    capture: ResponseCapture,
    store: CommentStore,
    include_replies: bool,
    max_comments: int,
    budget: ActionBudget,
    delay: float,
    idle_rounds: int,
    login_wait: float,
    reply_batch_size: int,
    reply_sweeps: int,
) -> None:
    aweme_id = video_id_from(video_url)
    if not aweme_id:
        raise BrowserRouteError(f"Video URL lacks an aweme_id: {video_url}")
    capture.set_current_video(aweme_id)
    resolved_url = settle_content_navigation(page, video_url, aweme_id, delay)
    emit_runtime_event(
        {"event": "navigation_ready", "aweme_id": aweme_id, "resolved_url": resolved_url}
    )
    title = safe_page_title(page, delay)
    store.upsert_video(
        {"aweme_id": aweme_id, "description": title, "source_url": resolved_url},
        fallback_aweme_id=aweme_id,
    )
    pause_page_media(page)
    page.wait_for_timeout(max(500, int(delay * 1000)))
    surface_state = wait_for_comment_surface(page, capture, budget, login_wait)
    emit_runtime_event(
        {
            "event": "comment_surface_ready",
            "aweme_id": aweme_id,
            "item_count": as_int(surface_state.get("item_count"), 0),
            "list_count": as_int(surface_state.get("list_count"), 0),
            "login_gate": as_bool(surface_state.get("login_gate")),
        }
    )
    settled_title = safe_page_title(page, delay)
    if settled_title:
        store.upsert_video(
            {"aweme_id": aweme_id, "description": settled_title, "source_url": resolved_url},
            fallback_aweme_id=aweme_id,
        )
    if as_bool(surface_state.get("login_gate")):
        store.set_progress(
            "comments",
            aweme_id,
            "",
            False,
            {"done_reason": "login_required", "route": PROVIDER, "terminal_known": False},
        )
        return
    emit_runtime_event({"event": "dom_fallback_start", "aweme_id": aweme_id})
    upsert_visible_dom_comments(page, store, aweme_id)
    emit_runtime_event({"event": "dom_fallback_end", "aweme_id": aweme_id})
    idle = 0
    previous_evidence_count = -1
    stop_reason = "ui_idle_unverified"
    while idle < idle_rounds:
        top_count = store.count_top_level_comments(aweme_id)
        progress = store.get_progress("comments", aweme_id)
        limit_reached = max_comments > 0 and top_count >= max_comments
        if limit_reached:
            stop_reason = "limit"
            break
        if progress.get("done"):
            stop_reason = "exhausted"
            break
        budget.take()
        scroll_largest_container(page)
        page.wait_for_timeout(max(300, int(delay * 1000)))
        if as_bool(comment_surface_state(page).get("login_gate")):
            stop_reason = "login_required"
            break
        upsert_visible_dom_comments(page, store, aweme_id)
        current_evidence_count = int(
            store.conn.execute(
                "SELECT COUNT(*) FROM comments WHERE aweme_id=?", (aweme_id,)
            ).fetchone()[0]
        )
        if current_evidence_count == previous_evidence_count:
            idle += 1
        else:
            idle = 0
        previous_evidence_count = current_evidence_count

    progress = store.get_progress("comments", aweme_id)
    if stop_reason == "limit":
        store.set_progress(
            "comments", aweme_id, progress.get("cursor", ""), True,
            {"done_reason": "limit", "limit": max_comments, "route": PROVIDER},
        )
    elif stop_reason != "exhausted" and not progress.get("done"):
        store.set_progress(
            "comments", aweme_id, progress.get("cursor", ""), False,
            {"done_reason": stop_reason, "route": PROVIDER, "terminal_known": False},
        )

    progress = store.get_progress("comments", aweme_id)
    if include_replies and progress.get("done"):
        emit_runtime_event({"event": "reply_phase_start", "aweme_id": aweme_id})
        collect_reply_floors_ui(
            page,
            store,
            aweme_id,
            budget,
            delay,
            idle_rounds,
            reply_batch_size,
            reply_sweeps,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Douyin comments by observing a user-visible Chrome session"
    )
    parser.add_argument("--creator", help="Douyin creator profile URL")
    parser.add_argument("--videos", type=int, default=20, help="Number of visible creator videos")
    parser.add_argument("--video", action="append", default=[], help="Explicit video URL or ID")
    parser.add_argument("--works-json", help="works.json used to seed titles, URLs and platform counts")
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--max-comments-per-video", type=int, default=0)
    parser.add_argument("--max-ui-actions", type=int, default=2500)
    parser.add_argument("--idle-rounds", type=int, default=5)
    parser.add_argument("--scroll-delay", type=float, default=1.2)
    parser.add_argument(
        "--reply-batch-size",
        type=int,
        default=5,
        help="Visible reply controls clicked per UI round; keep small to limit page growth",
    )
    parser.add_argument(
        "--reply-sweeps",
        type=int,
        default=3,
        help="Full top-to-bottom passes used to finish visible reply floors",
    )
    parser.add_argument("--page-timeout", type=float, default=60.0)
    parser.add_argument(
        "--login-wait",
        type=float,
        default=0.0,
        help="Seconds to keep Chrome open for manual login/verification when comments are unavailable",
    )
    parser.add_argument("--chrome-path", default="")
    parser.add_argument("--profile-dir", required=True, help="Persistent Chrome profile; keep outside output bundle")
    parser.add_argument("--out", required=True)
    parser.add_argument("--privacy-mode", choices=("hash", "raw"), default="hash")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--diagnostic-trace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def dry_plan(args: argparse.Namespace, work_rows: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    return {
        "provider": PROVIDER,
        "creator": args.creator or "",
        "creator_videos": args.videos if args.creator else 0,
        "explicit_videos": len(args.video),
        "works_json_videos": len(work_rows),
        "include_replies": bool(args.include_replies),
        "max_comments_per_video": args.max_comments_per_video,
        "max_ui_actions": args.max_ui_actions,
        "reply_batch_size": args.reply_batch_size,
        "reply_sweeps": args.reply_sweeps,
        "privacy_mode": args.privacy_mode,
        "headless": bool(args.headless),
        "diagnostic_trace": bool(args.diagnostic_trace),
        "login_wait": args.login_wait,
        "cookies_exported": False,
        "signature_generation": False,
        "dom_fallback": "visible top-level cards only; replies remain response-derived",
        "completeness": "only terminal when the browser response explicitly reports no more pages",
        "output": str(Path(args.out).resolve()),
    }


def collect_with_context(
    context: Any,
    args: argparse.Namespace,
    work_rows: Sequence[Dict[str, Any]],
    store: CommentStore,
    budget: ActionBudget,
    capture: ResponseCapture,
    manifest: Dict[str, Any],
) -> int:
    controller_page = context.pages[0] if context.pages else context.new_page()
    controller_page.set_default_timeout(int(max(10, args.page_timeout) * 1000))
    video_urls = normalize_video_urls(
        [work_url(row) for row in work_rows if work_url(row)] + list(args.video)
    )
    if args.creator:
        discovered = discover_creator_videos(
            controller_page,
            args.creator,
            args.videos,
            budget,
            args.scroll_delay,
            args.idle_rounds,
            args.login_wait,
        )
        existing_ids = {video_id_from(url) for url in video_urls}
        for discovered_url in discovered:
            discovered_id = video_id_from(discovered_url)
            if discovered_id and discovered_id not in existing_ids:
                existing_ids.add(discovered_id)
                video_urls.append(discovered_url)
        if len(discovered) < args.videos:
            manifest["warnings"].append(
                f"Creator discovery found {len(discovered)}/{args.videos} visible videos"
            )
        pause_page_media(controller_page)
    manifest["selected_video_urls"] = video_urls
    if not video_urls:
        raise BrowserRouteError(
            "No visible video links were found. Complete any login/verification in Chrome and rerun."
        )
    worker_page = controller_page
    worker_page.on("response", capture.on_response)
    for video_url in video_urls:
        aweme_id = video_id_from(video_url)
        for attempt in range(2):
            if worker_page is None or worker_page.is_closed():
                worker_page = context.new_page()
                manifest["worker_pages_created"] += 1
                worker_page.set_default_timeout(int(max(10, args.page_timeout) * 1000))
                worker_page.on("response", capture.on_response)
            crash_seen = {"value": False}
            worker_page.on(
                "crash", lambda *_args, state=crash_seen: state.__setitem__("value", True)
            )
            try:
                collect_video_ui(
                    worker_page,
                    video_url,
                    capture,
                    store,
                    args.include_replies,
                    args.max_comments_per_video,
                    budget,
                    args.scroll_delay,
                    args.idle_rounds,
                    args.login_wait,
                    args.reply_batch_size,
                    args.reply_sweeps,
                )
                break
            except Exception as exc:
                page_crashed = crash_seen["value"] or is_page_crash_error(exc)
                recoverable = page_crashed or is_transient_navigation_error(exc)
                if not recoverable:
                    raise
                if page_crashed:
                    manifest["worker_page_crashes"] += 1
                if attempt == 0:
                    manifest["worker_page_retries"] += 1
                    reason = "page crash" if page_crashed else "transient navigation"
                    manifest["warnings"].append(
                        f"Recoverable {reason} while collecting {aweme_id}; "
                        "recreating the worker tab and retrying once"
                    )
                    try:
                        worker_page.close()
                    except Exception:
                        pass
                    worker_page = None
                    continue
                reason = "page crash" if page_crashed else "transient navigation"
                manifest["warnings"].append(
                    f"Recoverable {reason} persisted for {aweme_id}; "
                    "continuing with the saved checkpoint"
                )
                break
        progress = store.get_progress("comments", aweme_id)
        if progress.get("meta", {}).get("done_reason") == "login_required":
            manifest["warnings"].append(
                f"Login is required to expand all comments/replies for video {aweme_id}"
            )
    # The caller owns the browser context and its final page. Closing the last
    # persistent-context page here can close Chrome before the caller records
    # and performs the single session shutdown. Crash-recovery pages are still
    # closed above when they are replaced.
    manifest["status"] = "complete_source_visible"
    for video_url in video_urls:
        aweme_id = video_id_from(video_url)
        if not store.get_progress("comments", aweme_id).get("done"):
            manifest["status"] = "partial_browser_visibility"
            return 3
        if args.include_replies and not replies_complete(store, aweme_id):
            manifest["status"] = "partial_browser_visibility"
            return 3
    return 0


def run(args: argparse.Namespace, browser_context: Any = None) -> int:
    global RUNTIME_TRACE_PATH, DIAGNOSTIC_TRACE_ENABLED
    work_rows = load_work_rows(args.works_json) if args.works_json else []
    if not args.creator and not args.video and not work_rows:
        raise BrowserRouteError("Provide --creator, --works-json, or at least one --video")
    if args.videos < 1:
        raise BrowserRouteError("--videos must be positive")
    if args.max_comments_per_video < 0:
        raise BrowserRouteError("--max-comments-per-video cannot be negative")
    if args.login_wait < 0:
        raise BrowserRouteError("--login-wait cannot be negative")
    if args.reply_batch_size < 1:
        raise BrowserRouteError("--reply-batch-size must be positive")
    if args.reply_sweeps < 1:
        raise BrowserRouteError("--reply-sweeps must be positive")
    if args.dry_run:
        print(json.dumps(dry_plan(args, work_rows), ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    RUNTIME_TRACE_PATH = out_dir / "browser_runtime_trace.jsonl"
    DIAGNOSTIC_TRACE_ENABLED = bool(args.diagnostic_trace)
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    if out_dir == profile_dir or out_dir in profile_dir.parents:
        raise BrowserRouteError("Keep --profile-dir outside --out so login state is never delivered")
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = CommentStore(out_dir / "comments.sqlite3", args.privacy_mode)
    for row in work_rows:
        store.upsert_video(work_seed(row))
    budget = ActionBudget(args.max_ui_actions)
    capture = ResponseCapture(store)
    manifest: Dict[str, Any] = {
        "provider": PROVIDER,
        "status": "running",
        "started_at": utc_now(),
        "privacy_mode": args.privacy_mode,
        "include_replies": bool(args.include_replies),
        "creator": args.creator or "",
        "requested_creator_videos": args.videos if args.creator else 0,
        "works_json_videos": len(work_rows),
        "max_comments_per_video": args.max_comments_per_video,
        "max_ui_actions": args.max_ui_actions,
        "reply_batch_size": args.reply_batch_size,
        "reply_sweeps": args.reply_sweeps,
        "login_wait": args.login_wait,
        "requests_used": 0,
        "request_budget": 0,
        "cookies_exported": False,
        "signature_generation": False,
        "dom_fallback": "visible top-level cards only",
        "page_isolation": "one_reused_worker_tab_with_crash_recovery",
        "browser_context_mode": (
            "shared_all_context" if browser_context is not None else "standalone_context"
        ),
        "browser_launches_total": 1,
        "browser_launches_owned": 0 if browser_context is not None else 1,
        "runtime_trace": "browser_runtime_trace.jsonl",
        "worker_pages_created": 0,
        "worker_page_retries": 0,
        "worker_page_crashes": 0,
        "warnings": [],
    }
    emit_runtime_event(
        {
            "event": "collector_start",
            "browser_context_mode": manifest["browser_context_mode"],
            "works_json_videos": len(work_rows),
            "privacy_mode": args.privacy_mode,
        }
    )
    exit_code = 0
    try:
        if browser_context is not None:
            exit_code = collect_with_context(
                browser_context, args, work_rows, store, budget, capture, manifest
            )
        else:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise BrowserRouteError(
                    "Playwright is required for the browser route. Install it in an isolated "
                    "environment with: python -m pip install playwright"
                ) from exc
            chrome_path = find_chrome_path(args.chrome_path)
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    executable_path=chrome_path,
                    headless=bool(args.headless),
                    accept_downloads=False,
                    viewport=None,
                    args=["--start-maximized", "--no-first-run", "--no-default-browser-check"],
                )
                try:
                    exit_code = collect_with_context(
                        context, args, work_rows, store, budget, capture, manifest
                    )
                finally:
                    context.close()
    except ActionBudgetExceeded as exc:
        manifest["status"] = "partial_action_budget"
        manifest["warnings"].append(str(exc))
        exit_code = 3
    except Exception as exc:
        manifest["status"] = "partial_browser_error"
        manifest["warnings"].append(f"{type(exc).__name__}: {exc}")
        exit_code = 3
    finally:
        manifest["ui_actions_used"] = budget.used
        manifest["browser_responses_observed"] = capture.responses_observed
        manifest["comment_responses_observed"] = capture.comment_responses
        manifest["dom_duplicates_replaced"] = capture.dom_duplicates_replaced
        manifest["capture_errors"] = capture.errors
        export_bundle(store, out_dir, manifest, bool(args.include_replies))
        emit_runtime_event(
            {
                "event": "collector_end",
                "status": manifest.get("status"),
                "comments_exported": manifest.get("comments_exported", 0),
                "replies_exported": manifest.get("replies_exported", 0),
            }
        )
        store.close()
    return exit_code


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except BrowserRouteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
