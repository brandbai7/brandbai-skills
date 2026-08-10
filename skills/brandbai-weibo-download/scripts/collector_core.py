"""Deterministic contracts for BrandBAI Weibo collection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote, urlparse, urlunparse


ALLOWED_PAGE_HOSTS = {
    "weibo.com",
    "www.weibo.com",
    "m.weibo.cn",
    "s.weibo.com",
    "huati.weibo.com",
    "video.weibo.com",
}
ALLOWED_MEDIA_HOST_SUFFIXES = (
    ".sinaimg.cn",
    ".sinajs.cn",
    ".weibocdn.com",
    ".weibo.com",
    ".sina.com.cn",
)
POST_ID_RE = re.compile(r"^[A-Za-z0-9]{5,32}$")
UID_RE = re.compile(r"^\d{5,24}$")
SUPERTOPIC_ID_RE = re.compile(r"^100808[A-Za-z0-9]{8,80}$")

HOTLIST_CATEGORIES = {
    "realtimehot": "热搜",
    "entrank": "文娱",
    "socialevent": "社会",
    "tech": "科技",
    "life": "生活",
    "sport": "体育",
    "game": "ACG",
}


class CollectionError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_host(value: str) -> Any:
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.lower() not in ALLOWED_PAGE_HOSTS:
        raise ValueError("Only public Weibo URLs are accepted")
    return parsed


def canonical_post_parts(value: str) -> tuple[str, str]:
    """Return ``(author_uid, post_id)`` from a supported Weibo post reference."""
    target = str(value or "").strip()
    parsed = _validate_host(target)
    parts = [part for part in parsed.path.split("/") if part]

    if len(parts) >= 2 and UID_RE.fullmatch(parts[0]) and POST_ID_RE.fullmatch(parts[1]):
        return parts[0], parts[1]
    if len(parts) >= 3 and parts[0] == "u" and UID_RE.fullmatch(parts[1]) and POST_ID_RE.fullmatch(parts[2]):
        return parts[1], parts[2]
    for marker in ("detail", "status"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) and POST_ID_RE.fullmatch(parts[index + 1]):
                return "", parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ("mid", "id", "mblogid"):
        if query.get(key) and POST_ID_RE.fullmatch(query[key][0]):
            return "", query[key][0]
    if not parsed.scheme:
        simple = [part for part in target.split("/") if part]
        if len(simple) == 2 and UID_RE.fullmatch(simple[0]) and POST_ID_RE.fullmatch(simple[1]):
            return simple[0], simple[1]
        if len(simple) == 1 and POST_ID_RE.fullmatch(simple[0]):
            return "", simple[0]
    raise ValueError("Cannot determine Weibo post ID")


def canonical_post_id(value: str) -> str:
    return canonical_post_parts(value)[1]


def canonical_post_url(value: str, author_uid: str = "") -> str:
    uid, post_id = canonical_post_parts(value)
    uid = str(author_uid or uid).strip()
    if uid and UID_RE.fullmatch(uid):
        return f"https://weibo.com/{uid}/{post_id}"
    return f"https://m.weibo.cn/detail/{post_id}"


def canonical_profile_id(value: str) -> str:
    target = str(value or "").strip()
    parsed = _validate_host(target)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "u" and UID_RE.fullmatch(parts[1]):
        return parts[1]
    if parts and UID_RE.fullmatch(parts[0]):
        return parts[0]
    query = parse_qs(parsed.query)
    for key in ("uid", "id"):
        if query.get(key) and UID_RE.fullmatch(query[key][0]):
            return query[key][0]
    if not parsed.scheme and UID_RE.fullmatch(target):
        return target
    raise ValueError("Cannot determine Weibo account UID")


def canonical_profile_url(value: str) -> str:
    return f"https://weibo.com/u/{canonical_profile_id(value)}"


def normalize_post_targets(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        target = str(value or "").strip()
        post_id = canonical_post_id(target)
        if post_id in seen:
            continue
        seen.add(post_id)
        output.append(target if urlparse(target).scheme else canonical_post_url(target))
    if not output:
        raise ValueError("At least one Weibo post is required")
    return output


def normalize_topic_query(value: str) -> str:
    query = str(value or "").strip()
    query = re.sub(r"^#+|#+$", "", query).strip()
    if not query:
        raise ValueError("Topic must not be empty")
    return query


def canonical_search_url(query: str, *, topic: bool = False) -> str:
    value = normalize_topic_query(query) if topic else str(query or "").strip()
    if not value:
        raise ValueError("Search query must not be empty")
    normalized = f"#{value}#" if topic else value
    return f"https://s.weibo.com/weibo?q={quote(normalized)}"


def canonical_supertopic_id(value: str) -> str:
    target = str(value or "").strip()
    parsed = _validate_host(target)
    parts = [part for part in parsed.path.split("/") if part]
    for part in parts:
        if SUPERTOPIC_ID_RE.fullmatch(part):
            return part
    if not parsed.scheme and SUPERTOPIC_ID_RE.fullmatch(target):
        return target
    raise ValueError("Cannot determine Weibo supertopic ID; provide a /p/100808... link or ID")


def canonical_supertopic_url(value: str) -> str:
    return f"https://weibo.com/p/{canonical_supertopic_id(value)}/super_index?mod=TAB"


def normalize_supertopic_tab(value: str) -> str:
    tab = str(value or "热门").strip()
    aliases = {
        "hot": "热门", "热门": "热门",
        "latest": "最新", "最新": "最新",
        "featured": "精华", "essence": "精华", "精华": "精华",
    }
    normalized = aliases.get(tab.lower(), aliases.get(tab, tab))
    if not normalized or len(normalized) > 20:
        raise ValueError("Supertopic tab must be a short visible tab name")
    return normalized


def normalize_hotlist_category(value: str) -> tuple[str, str]:
    raw = str(value or "热搜").strip()
    aliases = {
        "hot": "realtimehot", "realtimehot": "realtimehot", "热搜": "realtimehot", "主榜": "realtimehot",
        "entertainment": "entrank", "ent": "entrank", "entrank": "entrank", "文娱": "entrank",
        "social": "socialevent", "socialevent": "socialevent", "社会": "socialevent",
        "technology": "tech", "tech": "tech", "科技": "tech",
        "life": "life", "生活": "life",
        "sports": "sport", "sport": "sport", "体育": "sport",
        "acg": "game", "game": "game", "游戏": "game", "动漫": "game",
    }
    code = aliases.get(raw.lower(), aliases.get(raw))
    if not code:
        supported = "、".join(HOTLIST_CATEGORIES.values())
        raise ValueError(f"Unsupported Weibo hotlist category; use one of: {supported}")
    return code, HOTLIST_CATEGORIES[code]


def canonical_hotlist_url(value: str) -> str:
    code, _ = normalize_hotlist_category(value)
    if code == "realtimehot":
        return "https://s.weibo.com/top/summary"
    return f"https://s.weibo.com/top/summary?cate={code}"


def freeze_hotlist_snapshot(
    entries: Iterable[dict[str, Any]], *, category: str, ranked_limit: int,
    captured_at: str | None = None,
) -> dict[str, Any]:
    if ranked_limit <= 0:
        raise ValueError("hotlist ranked limit must be positive")
    code, name = normalize_hotlist_category(category)
    captured = captured_at or utc_now()
    snapshot_id = derived_id("hotlist", code, captured)
    selected: list[dict[str, Any]] = []
    seen_positions: set[int] = set()
    seen_ranked: set[int] = set()
    for index, entry in enumerate(entries, start=1):
        keyword = str(entry.get("keyword") or "").strip()
        if not keyword:
            continue
        observed_position = int(entry.get("observed_position") or index)
        if observed_position in seen_positions:
            raise ValueError("duplicate hotlist observed position")
        rank_numeric = max(0, int(entry.get("rank_numeric") or 0))
        is_extra = bool(entry.get("is_pinned") or entry.get("is_special") or rank_numeric == 0)
        if rank_numeric > ranked_limit and not is_extra:
            continue
        if rank_numeric:
            if rank_numeric in seen_ranked:
                raise ValueError("duplicate hotlist numeric rank")
            seen_ranked.add(rank_numeric)
        seen_positions.add(observed_position)
        row = dict(entry)
        row.update({
            "hotlist_snapshot_id": snapshot_id,
            "category_code": code,
            "category_name": name,
            "observed_position": observed_position,
            "rank_numeric": rank_numeric,
            "captured_at": captured,
        })
        selected.append(row)
    ranked_saved = len([row for row in selected if int(row.get("rank_numeric") or 0) > 0])
    extra_saved = len(selected) - ranked_saved
    state = "complete_ranked_hotlist_plus_visible_extras" if ranked_saved >= ranked_limit else "partial_hotlist_rank_shortfall"
    return {
        "schema_version": "1.0",
        "hotlist_snapshot_id": snapshot_id,
        "category_code": code,
        "category_name": name,
        "canonical_url": canonical_hotlist_url(code),
        "captured_at": captured,
        "requested_ranked": ranked_limit,
        "saved_ranked": ranked_saved,
        "saved_extras": extra_saved,
        "saved_total": len(selected),
        "entries": selected,
        "state": state,
    }


def safe_filename(value: str, fallback: str = "weibo", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:max_length].rstrip(" ._") or fallback


def sanitize_media_url(value: str) -> tuple[str, bool]:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not any(
        host == suffix[1:] or host.endswith(suffix) for suffix in ALLOWED_MEDIA_HOST_SUFFIXES
    ):
        raise CollectionError("Unsupported Weibo media URL")
    clean = urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))
    return clean, bool(parsed.query or parsed.fragment or parsed.scheme != "https")


def derived_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"derived:{prefix}:{digest}"


def stable_pseudonym(author_key: str, salt: str = "brandbai-weibo-v1") -> str:
    digest = hashlib.sha256(f"{salt}\x1f{author_key}".encode("utf-8")).hexdigest()[:12]
    return f"wb_user_{digest}"


def select_profile_posts(records: Iterable[dict[str, Any]], recent: int) -> dict[str, Any]:
    if recent < 0:
        raise ValueError("recent must be zero or greater")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        post_id = str(record.get("post_id") or "").strip()
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        deduped.append(dict(record))
    pinned = [row for row in deduped if bool(row.get("is_pinned"))]
    normal = [row for row in deduped if not bool(row.get("is_pinned"))]
    selected = [{**row, "selection_reason": "pinned"} for row in pinned]
    selected.extend({**row, "selection_reason": "recent_non_pinned"} for row in normal[:recent])
    enough = len(normal) >= recent
    return {
        "selected": selected,
        "pinned_count": len(pinned),
        "recent_requested": recent,
        "recent_selected": min(len(normal), recent),
        "state": "complete_visible_pinned_plus_recent_n" if enough else "partial_selection_shortfall",
    }


def freeze_search_results(
    records: Iterable[dict[str, Any]], *, query: str, query_kind: str, sort: str,
    filters: list[str], limit: int, captured_at: str | None = None,
    topic_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("search limit must be positive")
    if query_kind not in {"keyword", "topic", "supertopic"}:
        raise ValueError("query_kind must be keyword, topic or supertopic")
    captured = captured_at or utc_now()
    snapshot_id = derived_id(
        "search", query_kind, query, sort, json.dumps(filters, ensure_ascii=False), captured
    )
    ranked: list[dict[str, Any]] = []
    seen_posts: set[str] = set()
    seen_ranks: set[int] = set()
    for index, record in enumerate(records, start=1):
        if len(ranked) >= limit:
            break
        post_id = str(record.get("post_id") or "").strip()
        if not post_id or post_id in seen_posts:
            continue
        rank = int(record.get("rank") or index)
        if rank in seen_ranks:
            raise ValueError("duplicate search rank")
        seen_posts.add(post_id)
        seen_ranks.add(rank)
        row = dict(record)
        row.update({
            "search_snapshot_id": snapshot_id,
            "query": query,
            "query_kind": query_kind,
            "sort": sort,
            "filters": list(filters),
            "rank": rank,
            "captured_at": captured,
        })
        ranked.append(row)
    return {
        "search_snapshot_id": snapshot_id,
        "query": query,
        "query_kind": query_kind,
        "sort": sort,
        "filters": list(filters),
        "captured_at": captured,
        "results": ranked,
        "topic_context": dict(topic_context or {}),
        "requested": limit,
        "saved": len(ranked),
        "state": "complete_first_n_visible_results" if len(ranked) >= limit else "partial_search_shortfall",
    }


def comment_completion_state(
    *, exhausted: bool, limit_reached: bool, declared_reply_count: int,
    saved_reply_count: int, replies_requested: bool,
    login_limited: bool = False, scroll_budget_exhausted: bool = False,
    sort_activation_failed: bool = False,
    sort_modes_available: Iterable[str] = (),
    sort_modes_exhausted: Iterable[str] = (),
) -> str:
    if limit_reached:
        return "partial_limit_sample"
    if login_limited:
        return "partial_login_required"
    if sort_activation_failed:
        return "partial_sort_not_available"
    if scroll_budget_exhausted:
        return "partial_scroll_budget_exhausted"
    if not exhausted:
        return "partial_selector_drift"
    if replies_requested and saved_reply_count < declared_reply_count:
        return "partial_reply_not_expanded"
    available = set(sort_modes_available)
    exhausted_sorts = set(sort_modes_exhausted)
    if {"按热度", "按时间"}.issubset(available) and available.issubset(exhausted_sorts):
        return "complete_visible_both_sorts_exhausted"
    return "complete_visible_comments_exhausted"


def repost_completion_state(*, exhausted: bool, limit_reached: bool, available: bool) -> str:
    if not available:
        return "partial_reposts_not_available"
    if limit_reached:
        return "partial_limit_sample"
    if not exhausted:
        return "partial_repost_chain_not_expanded"
    return "complete_visible_reposts_exhausted"


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
