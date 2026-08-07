"""Deterministic contracts for BrandBAI Xiaohongshu collection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse, urlunparse


ALLOWED_HOSTS = {"www.xiaohongshu.com", "xiaohongshu.com"}
ALLOWED_MEDIA_HOST_SUFFIXES = (".xhscdn.com", ".xiaohongshu.com")


class CollectionError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_note_id(value: str) -> str:
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.lower() not in ALLOWED_HOSTS:
        raise ValueError("Only xiaohongshu.com URLs are accepted")
    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("explore", "discovery", "item", "search_result"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) and parts[index + 1]:
                return parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ("note_id", "id"):
        if query.get(key):
            return query[key][0]
    if not parsed.scheme and value.strip() and "/" not in value.strip():
        return value.strip()
    raise ValueError("Cannot determine Xiaohongshu note ID")


def canonical_note_url(value: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{canonical_note_id(value)}"


def normalize_note_targets(values: Iterable[str]) -> list[str]:
    """Deduplicate targets by stable note id while keeping transient URLs in memory only."""
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        target = str(value or "").strip()
        note_id = canonical_note_id(target)
        if note_id in seen:
            continue
        seen.add(note_id)
        output.append(target if urlparse(target).scheme else canonical_note_url(target))
    if not output:
        raise ValueError("At least one Xiaohongshu note is required")
    return output


def safe_filename(value: str, fallback: str = "note", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:max_length].rstrip(" ._") or fallback


def sanitize_media_url(value: str) -> tuple[str, bool]:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not any(
        host == suffix[1:] or host.endswith(suffix) for suffix in ALLOWED_MEDIA_HOST_SUFFIXES
    ):
        raise CollectionError("Unsupported Xiaohongshu media URL")
    clean = urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))
    return clean, bool(parsed.query or parsed.fragment or parsed.scheme != "https")


def derived_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"derived:{prefix}:{digest}"


def stable_pseudonym(author_key: str, salt: str = "brandbai-xhs-v1") -> str:
    digest = hashlib.sha256(f"{salt}\x1f{author_key}".encode("utf-8")).hexdigest()[:12]
    return f"xhs_user_{digest}"


def select_profile_notes(records: Iterable[dict[str, Any]], recent: int) -> dict[str, Any]:
    if recent < 0:
        raise ValueError("recent must be zero or greater")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        note_id = str(record.get("note_id") or "").strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        deduped.append(dict(record))
    pinned = [row for row in deduped if bool(row.get("is_pinned"))]
    normal = [row for row in deduped if not bool(row.get("is_pinned"))]
    selected = pinned + normal[:recent]
    enough = len(normal) >= recent
    return {
        "selected": selected,
        "pinned_count": len(pinned),
        "recent_requested": recent,
        "recent_selected": min(len(normal), recent),
        "state": "complete_visible_pinned_plus_recent_n" if enough else "partial_selection_shortfall",
    }


def freeze_search_results(
    records: Iterable[dict[str, Any]], *, keyword: str, tab: str, filters: list[str], limit: int,
    related_queries: list[str] | None = None, captured_at: str | None = None,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("search limit must be positive")
    captured = captured_at or utc_now()
    snapshot_id = derived_id("search", keyword, tab, json.dumps(filters, ensure_ascii=False), captured)
    ranked: list[dict[str, Any]] = []
    seen_positions: set[int] = set()
    for index, record in enumerate(records, start=1):
        if len(ranked) >= limit:
            break
        rank = int(record.get("rank") or index)
        if rank in seen_positions:
            raise ValueError("duplicate search rank")
        seen_positions.add(rank)
        row = dict(record)
        row.update({
            "search_snapshot_id": snapshot_id,
            "keyword": keyword,
            "tab": tab,
            "filters": list(filters),
            "rank": rank,
            "captured_at": captured,
        })
        ranked.append(row)
    return {
        "search_snapshot_id": snapshot_id,
        "keyword": keyword,
        "tab": tab,
        "filters": list(filters),
        "captured_at": captured,
        "results": ranked,
        "related_queries": list(related_queries or []),
        "requested": limit,
        "saved": len(ranked),
        "state": "complete_first_n_visible_results" if len(ranked) >= limit else "partial_search_shortfall",
    }


def comment_completion_state(
    *, exhausted: bool, limit_reached: bool, declared_reply_count: int, saved_reply_count: int,
    replies_requested: bool,
) -> str:
    if limit_reached:
        return "partial_limit_sample"
    if not exhausted:
        return "partial_selector_drift"
    if replies_requested and saved_reply_count < declared_reply_count:
        return "partial_reply_not_expanded"
    return "complete_visible_panel_exhausted"


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
