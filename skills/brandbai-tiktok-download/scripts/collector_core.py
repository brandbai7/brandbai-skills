"""Deterministic contracts for BrandBAI TikTok collection."""

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


ALLOWED_HOSTS = {"www.tiktok.com", "tiktok.com"}
ALLOWED_MEDIA_HOST_SUFFIXES = (
    ".tiktokcdn.com", ".tiktokcdn-us.com", ".tiktokv.com", ".tiktokv.us", ".tiktok.com"
)


class CollectionError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parts(value: str) -> tuple[Any, list[str]]:
    parsed = urlparse(str(value or "").strip())
    if parsed.hostname and parsed.hostname.lower() not in ALLOWED_HOSTS:
        raise ValueError("Only tiktok.com URLs are accepted")
    return parsed, [part for part in parsed.path.split("/") if part]


def canonical_work_id(value: str) -> str:
    parsed, parts = _parts(value)
    for marker in ("video", "photo"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) and parts[index + 1].isdigit():
                return parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ("item_id", "aweme_id", "id"):
        if query.get(key) and str(query[key][0]).isdigit():
            return str(query[key][0])
    raw = str(value or "").strip()
    if not parsed.scheme and raw.isdigit():
        return raw
    raise ValueError("Cannot determine TikTok work ID")


def work_type_from_url(value: str, fallback: str = "video") -> str:
    _, parts = _parts(value)
    if "photo" in parts:
        return "photo"
    if "video" in parts:
        return "video"
    if fallback not in {"video", "photo"}:
        raise ValueError("work type must be video or photo")
    return fallback


def canonical_handle(value: str) -> str:
    parsed, parts = _parts(value)
    for part in parts:
        if part.startswith("@") and len(part) > 1:
            return part[1:]
    raw = str(value or "").strip().lstrip("@")
    if not parsed.scheme and raw and "/" not in raw and "?" not in raw:
        return raw
    raise ValueError("Cannot determine TikTok handle")


def canonical_profile_url(value: str) -> str:
    return f"https://www.tiktok.com/@{quote(canonical_handle(value), safe='._-')}"


def canonical_work_url(value: str, handle: str | None = None, work_type: str | None = None) -> str:
    work_id = canonical_work_id(value)
    parsed, parts = _parts(value)
    resolved_handle = handle
    if not resolved_handle:
        for part in parts:
            if part.startswith("@"):
                resolved_handle = part[1:]
                break
    if not resolved_handle:
        resolved_handle = "unknown"
    resolved_type = work_type or work_type_from_url(value)
    return f"https://www.tiktok.com/@{quote(resolved_handle.lstrip('@'), safe='._-')}/{resolved_type}/{work_id}"


def normalize_work_targets(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        target = str(value or "").strip()
        work_id = canonical_work_id(target)
        if work_id in seen:
            continue
        seen.add(work_id)
        output.append(target)
    if not output:
        raise ValueError("At least one TikTok work is required")
    return output


def safe_filename(value: str, fallback: str = "work", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:max_length].rstrip(" ._") or fallback


def sanitize_media_url(value: str) -> tuple[str, bool]:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    allowed = any(host == suffix[1:] or host.endswith(suffix) for suffix in ALLOWED_MEDIA_HOST_SUFFIXES)
    if parsed.scheme != "https" or not allowed:
        raise CollectionError("Unsupported TikTok media URL")
    clean = urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))
    return clean, bool(parsed.query or parsed.fragment)


def parse_metric(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMBkmb]?)", text)
    if not match:
        return None
    scale = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
    return int(float(match.group(1)) * scale)


def derived_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    return f"derived:{prefix}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def stable_pseudonym(author_key: str, salt: str = "brandbai-tiktok-v1") -> str:
    digest = hashlib.sha256(f"{salt}\x1f{author_key}".encode("utf-8")).hexdigest()[:12]
    return f"tiktok_user_{digest}"


def select_profile_works(records: Iterable[dict[str, Any]], recent: int) -> dict[str, Any]:
    if recent < 0:
        raise ValueError("recent must be zero or greater")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        work_id = str(record.get("work_id") or "").strip()
        if not work_id or work_id in seen:
            continue
        seen.add(work_id)
        deduped.append(dict(record))
    pinned = [row for row in deduped if bool(row.get("is_pinned"))]
    normal = [row for row in deduped if not bool(row.get("is_pinned"))]
    selected = [{**row, "selection_reason": "pinned"} for row in pinned]
    selected.extend({**row, "selection_reason": "recent_non_pinned"} for row in normal[:recent])
    return {
        "selected": selected,
        "pinned_count": len(pinned),
        "recent_requested": recent,
        "recent_selected": min(len(normal), recent),
        "state": "complete_visible_pinned_plus_recent_n" if len(normal) >= recent else "partial_selection_shortfall",
    }


def freeze_search_results(
    records: Iterable[dict[str, Any]], *, keyword: str, tab: str, filters: list[str], limit: int,
    captured_at: str | None = None,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("search limit must be positive")
    if tab not in {"general", "video", "photo"}:
        raise ValueError("search tab must be general, video or photo")
    captured = captured_at or utc_now()
    snapshot_id = derived_id("search", keyword, tab, json.dumps(filters, ensure_ascii=False), captured)
    ranked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_ranks: set[int] = set()
    for index, record in enumerate(records, start=1):
        if len(ranked) >= limit:
            break
        work_id = str(record.get("work_id") or "").strip()
        if not work_id or work_id in seen_ids:
            continue
        rank = int(record.get("rank") or index)
        if rank in seen_ranks:
            raise ValueError("duplicate search rank")
        seen_ids.add(work_id)
        seen_ranks.add(rank)
        ranked.append({**record, "search_snapshot_id": snapshot_id, "keyword": keyword, "tab": tab,
                       "filters": list(filters), "rank": rank, "captured_at": captured})
    return {
        "search_snapshot_id": snapshot_id, "keyword": keyword, "tab": tab, "filters": list(filters),
        "captured_at": captured, "results": ranked, "requested": limit, "saved": len(ranked),
        "state": "complete_first_n_visible_results" if len(ranked) >= limit else "partial_search_shortfall",
    }


def comment_completion_state(
    *, exhausted: bool, limit_reached: bool, replies_requested: bool,
    declared_reply_count: int = 0, saved_reply_count: int = 0,
) -> str:
    if limit_reached:
        return "partial_limit_sample"
    if not exhausted:
        return "partial_selector_drift"
    if replies_requested and saved_reply_count < declared_reply_count:
        return "partial_reply_not_expanded"
    return "complete_source_visible"


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


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    rows = [row for row in records if isinstance(row, dict)]
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(rows)
