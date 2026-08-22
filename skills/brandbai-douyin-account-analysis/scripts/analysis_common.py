#!/usr/bin/env python3
"""Shared input normalization for the BrandBAI Douyin account analysis skill."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


MAX_RECENT_NON_PINNED = 30

WORKS_CANDIDATES = (
    "data/作品采集/works.json",
    "works.json",
)
COMMENTS_CANDIDATES = (
    "data/评论采集/comments.csv",
    "comments.csv",
)
WORKS_MANIFEST_CANDIDATES = (
    "data/作品采集/download_manifest.json",
    "download_manifest.json",
)
COMMENTS_MANIFEST_CANDIDATES = (
    "data/评论采集/run_manifest.json",
    "run_manifest.json",
)


class AnalysisInputError(RuntimeError):
    """Raised when an analysis package cannot be normalized."""


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "是", "置顶", "pinned",
    }


def as_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def locate(root: Path, candidates: Iterable[str]) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.is_file():
            return path
    return None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisInputError(f"Cannot read JSON: {path}") from exc


def load_works(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, dict):
        payload = payload.get("works")
    if not isinstance(payload, list):
        raise AnalysisInputError("works.json must be a list or contain a works list")
    return [row for row in payload if isinstance(row, dict)]


def work_id(row: dict[str, Any]) -> str:
    return str(
        row.get("aweme_id")
        or row.get("video_id")
        or row.get("item_id")
        or ""
    ).strip()


def timestamp(row: dict[str, Any]) -> float:
    raw_numeric = row.get("create_time")
    if raw_numeric not in (None, ""):
        try:
            value = float(raw_numeric)
            return value / 1000 if value > 10_000_000_000 else value
        except (TypeError, ValueError):
            pass
    raw_text = str(row.get("publish_time") or "").strip()
    if not raw_text:
        return 0.0
    try:
        return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def normalize_work(row: dict[str, Any], source_index: int) -> dict[str, Any] | None:
    video_id = work_id(row)
    if not video_id:
        return None
    statistics = row.get("statistics") if isinstance(row.get("statistics"), dict) else {}
    pinned = as_bool(row.get("is_pinned")) or str(row.get("selection_reason") or "") == "置顶"
    return {
        "video_id": video_id,
        "aweme_id": video_id,
        "content_type": str(row.get("type") or row.get("content_type") or ""),
        "author": str(row.get("author") or ""),
        "title": str(row.get("title") or row.get("description") or row.get("desc") or "").strip(),
        "create_time": row.get("create_time") or "",
        "publish_time": str(row.get("publish_time") or ""),
        "digg_count": as_int(row.get("digg_count") or statistics.get("digg_count")),
        "comment_count": as_int(row.get("comment_count") or statistics.get("comment_count")),
        "collect_count": as_int(row.get("collect_count") or statistics.get("collect_count")),
        "share_count": as_int(row.get("share_count") or statistics.get("share_count")),
        "is_pinned": pinned,
        "source_url": str(row.get("source_url") or ""),
        "local_folder": str(row.get("local_folder") or ""),
        "download_status": str(row.get("download_status") or ""),
        "_sort_time": timestamp(row),
        "_source_index": source_index,
    }


def merge_duplicate(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["is_pinned"] = bool(existing["is_pinned"] or incoming["is_pinned"])
    if incoming["_sort_time"] > existing["_sort_time"]:
        existing["_sort_time"] = incoming["_sort_time"]
        existing["create_time"] = incoming["create_time"]
        existing["publish_time"] = incoming["publish_time"]
    for key in ("digg_count", "comment_count", "collect_count", "share_count"):
        existing[key] = max(as_int(existing.get(key)), as_int(incoming.get(key)))
    for key in ("content_type", "author", "title", "source_url", "local_folder", "download_status"):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]


def select_works(rows: list[dict[str, Any]], max_recent: int = MAX_RECENT_NON_PINNED) -> tuple[list[dict[str, Any]], list[str]]:
    if not 1 <= max_recent <= MAX_RECENT_NON_PINNED:
        raise AnalysisInputError(f"max_recent must be between 1 and {MAX_RECENT_NON_PINNED}")
    by_id: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for index, row in enumerate(rows):
        normalized = normalize_work(row, index)
        if normalized is None:
            warnings.append(f"Skipped work at source index {index}: missing video ID")
            continue
        current = by_id.get(normalized["video_id"])
        if current is None:
            by_id[normalized["video_id"]] = normalized
        else:
            merge_duplicate(current, normalized)

    pinned = sorted(
        (row for row in by_id.values() if row["is_pinned"]),
        key=lambda row: (row["_sort_time"], row["video_id"]),
        reverse=True,
    )
    recent = sorted(
        (row for row in by_id.values() if not row["is_pinned"]),
        key=lambda row: (row["_sort_time"], row["video_id"]),
        reverse=True,
    )[:max_recent]

    for rank, row in enumerate(pinned, 1):
        row["sample_role"] = "pinned"
        row["sample_rank"] = rank
    for rank, row in enumerate(recent, 1):
        row["sample_role"] = "recent_non_pinned"
        row["sample_rank"] = rank

    selected: list[dict[str, Any]] = []
    for row in pinned + recent:
        selected.append({key: value for key, value in row.items() if not key.startswith("_")})
    return selected, warnings


def read_comments(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as exc:
        raise AnalysisInputError(f"Cannot read comments CSV: {path}") from exc


def comment_video_id(row: dict[str, Any]) -> str:
    return str(row.get("aweme_id") or row.get("video_id") or "").strip()


def build_comment_inventory(comments: list[dict[str, Any]], selected_ids: set[str]) -> list[dict[str, Any]]:
    counters: dict[str, dict[str, int]] = defaultdict(lambda: {
        "comments_total": 0,
        "top_level_comments": 0,
        "replies": 0,
        "declared_replies": 0,
        "platform_ids": 0,
        "dom_fallback_ids": 0,
    })
    for row in comments:
        video_id = comment_video_id(row)
        if video_id not in selected_ids:
            continue
        current = counters[video_id]
        current["comments_total"] += 1
        reply_level = as_int(row.get("reply_level"))
        if reply_level <= 0:
            current["top_level_comments"] += 1
            current["declared_replies"] += as_int(row.get("reply_count"))
        else:
            current["replies"] += 1
        source = str(row.get("id_source") or "").strip().lower()
        if source == "platform":
            current["platform_ids"] += 1
        elif source == "dom_fallback":
            current["dom_fallback_ids"] += 1

    return [
        {"video_id": video_id, **counters[video_id]}
        for video_id in sorted(selected_ids)
    ]


def normalized_relative(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def media_exists(root: Path, works_path: Path, work: dict[str, Any]) -> bool:
    local_folder = str(work.get("local_folder") or "").strip().replace("\\", "/")
    candidates: list[Path] = []
    if local_folder:
        candidates.extend((root / local_folder, works_path.parent / local_folder))
    video_id = str(work.get("video_id") or "")
    for media_root in (root / "03_作品素材", works_path.parent / "media"):
        if media_root.is_dir() and any(video_id in child.name for child in media_root.iterdir()):
            return True
    return any(path.exists() for path in candidates)


def inspect_input(input_dir: Path, max_recent: int = MAX_RECENT_NON_PINNED) -> dict[str, Any]:
    root = input_dir.expanduser().resolve()
    if not root.is_dir():
        return {
            "status": "invalid",
            "errors": [f"Input directory does not exist: {root}"],
            "warnings": [],
        }

    works_path = locate(root, WORKS_CANDIDATES)
    comments_path = locate(root, COMMENTS_CANDIDATES)
    works_manifest_path = locate(root, WORKS_MANIFEST_CANDIDATES)
    comments_manifest_path = locate(root, COMMENTS_MANIFEST_CANDIDATES)
    if works_path is None:
        return {
            "status": "invalid",
            "errors": ["works.json was not found in the supported locations"],
            "warnings": [],
        }

    try:
        selected, selection_warnings = select_works(load_works(works_path), max_recent=max_recent)
        comments = read_comments(comments_path)
    except AnalysisInputError as exc:
        return {"status": "invalid", "errors": [str(exc)], "warnings": []}
    if not selected:
        return {
            "status": "invalid",
            "errors": ["No valid works with a video ID were found"],
            "warnings": selection_warnings,
        }

    warnings = list(selection_warnings)
    works_manifest: dict[str, Any] = {}
    if works_manifest_path is None:
        warnings.append("Works completeness manifest is missing")
    else:
        try:
            payload = read_json(works_manifest_path)
            works_manifest = payload if isinstance(payload, dict) else {}
        except AnalysisInputError:
            warnings.append("Works completeness manifest cannot be read")
    if comments_path is None:
        warnings.append("Comments CSV is missing; only the works baseline can be prepared")
    if comments_manifest_path is None:
        warnings.append("Comments completeness manifest is missing")

    missing_media_ids = [
        row["video_id"] for row in selected if not media_exists(root, works_path, row)
    ]
    if missing_media_ids:
        warnings.append(f"Media is missing or not locatable for {len(missing_media_ids)} selected work(s)")

    selected_ids = {row["video_id"] for row in selected}
    inventory = build_comment_inventory(comments, selected_ids)
    requested_recent = as_int(works_manifest.get("requested_recent_non_pinned"))
    visible_works_observed = as_int(works_manifest.get("visible_works_observed"))
    recent_selected = sum(1 for row in selected if row["sample_role"] == "recent_non_pinned")
    if (
        requested_recent
        and requested_recent < max_recent
        and visible_works_observed > len(selected)
    ):
        warnings.append(
            "Collection package requested only "
            f"{requested_recent} recent non-pinned work(s), while the default analysis window is "
            f"up to {max_recent} and {visible_works_observed} visible work(s) were observed"
        )
        analysis_window_status = "partial"
    elif requested_recent >= max_recent or (
        visible_works_observed and visible_works_observed <= len(selected)
    ):
        analysis_window_status = "complete_observed_scope"
    else:
        analysis_window_status = "unknown"
    status = "ready" if not warnings else "partial"
    return {
        "status": status,
        "errors": [],
        "warnings": warnings,
        "source_paths": {
            "works": normalized_relative(works_path, root),
            "comments": normalized_relative(comments_path, root),
            "works_manifest": normalized_relative(works_manifest_path, root),
            "comments_manifest": normalized_relative(comments_manifest_path, root),
        },
        "sample_rule": {
            "all_visible_pinned": True,
            "max_recent_non_pinned": max_recent,
            "pinned_counted_inside_recent_limit": False,
            "baseline": "recent_non_pinned_only",
        },
        "sample_counts": {
            "pinned": sum(1 for row in selected if row["sample_role"] == "pinned"),
            "recent_non_pinned": sum(1 for row in selected if row["sample_role"] == "recent_non_pinned"),
            "selected_total": len(selected),
            "comments_loaded": len(comments),
            "missing_media": len(missing_media_ids),
        },
        "analysis_window": {
            "status": analysis_window_status,
            "requested_recent_non_pinned": requested_recent,
            "selected_recent_non_pinned": recent_selected,
            "visible_works_observed": visible_works_observed,
            "default_recent_non_pinned": max_recent,
        },
        "selected_works": selected,
        "comment_inventory": inventory,
        "missing_media_ids": missing_media_ids,
    }
