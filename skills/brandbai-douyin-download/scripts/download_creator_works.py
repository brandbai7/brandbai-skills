"""Download pinned plus recent visible Douyin creator works through ordinary Chrome.

This is a clean-room browser route. It observes metadata returned by the normal
signed-in creator page, never exports cookies, never generates request
signatures, and never automates CAPTCHA or access-control bypasses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from package_delivery import package_directory
from selection_contract import (
    SelectionContractError,
    deduplicate as deduplicate_seeds,
    load_selection,
    seed_from_url,
)


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MULTISPACE = re.compile(r"\s+")
PROVIDER = "douyin_visible_chrome_page"
CHINA_TIMEZONE = timezone(timedelta(hours=8))
ASSET_KINDS = {"primary", "cover", "audio", "caption"}
RESPONSE_TOKENS = (
    "aweme/post",
    "aweme/listcollection",
    "aweme/detail",
    "search/item",
    "general/search",
    "/search/",
)


class WorkDownloadError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def optional_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "" or isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return None


def nested_get(value: Any, *path: str, default: Any = None) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def sanitize_name(value: Any, fallback: str = "未命名作品", max_length: int = 72) -> str:
    text = MULTISPACE.sub(" ", str(value or "")).strip().strip(".")
    text = INVALID_FILENAME.sub("_", text).strip(" ._")
    if not text:
        text = fallback
    return text[:max_length].rstrip(" ._") or fallback


def unique_urls(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        output.append(url)
    return output


def url_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return unique_urls([value])
    if isinstance(value, list):
        return unique_urls(value)
    if not isinstance(value, dict):
        return []
    candidates: list[Any] = []
    for key in ("url_list", "urlList", "download_url_list", "downloadUrlList"):
        item = value.get(key)
        if isinstance(item, list):
            candidates.extend(item)
    for key in ("url", "download_url", "downloadUrl"):
        item = value.get(key)
        if isinstance(item, str):
            candidates.append(item)
        elif isinstance(item, dict):
            candidates.extend(url_list(item))
    return unique_urls(candidates)


def pick_posts(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            aweme_id = str(value.get("aweme_id") or value.get("awemeId") or "")
            if aweme_id and aweme_id not in seen:
                seen.add(aweme_id)
                found.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def search_dom_work_ids(page: Any) -> list[str]:
    """Return work IDs exposed by ordinary visible search result cards.

    Douyin's search page can render usable cards even when the corresponding
    JSON response was delivered before the listener was attached or uses a new
    response envelope. The public ``data-e2e-vid`` marker is therefore a safe
    discovery fallback; detail pages are still opened through normal Chrome to
    obtain the actual work metadata.
    """

    try:
        values = page.locator("[data-e2e-vid]").evaluate_all(
            "nodes => nodes.map(node => node.getAttribute('data-e2e-vid') || '')"
        )
    except Exception:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        aweme_id = str(value or "").strip()
        if not re.fullmatch(r"\d{10,24}", aweme_id) or aweme_id in seen:
            continue
        seen.add(aweme_id)
        output.append(aweme_id)
    return output


def find_chrome_path(explicit: str = "") -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise WorkDownloadError(f"Chrome executable does not exist: {candidate}")
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if local:
        candidates.append(Path(local) / "Google/Chrome/Application/chrome.exe")
    if program_files:
        candidates.append(Path(program_files) / "Google/Chrome/Application/chrome.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Google/Chrome/Application/chrome.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise WorkDownloadError("Google Chrome was not found; pass --chrome-path")


def image_nodes(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [item.get("images"), nested_get(item, "image_post_info", "images")]
    for value in candidates:
        if isinstance(value, list) and value:
            return [node for node in value if isinstance(node, dict)]
    return []


def image_urls(node: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "download_url_list",
        "downloadUrlList",
        "download_url",
        "display_image",
        "displayImage",
        "origin_image",
        "originImage",
        "url_list",
    ):
        values.extend(url_list(node.get(key)))
    return unique_urls(values)


def video_urls(item: dict[str, Any]) -> list[str]:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    ranked: list[tuple[int, list[str]]] = []
    bit_rates = video.get("bit_rate") or video.get("bitRate") or []
    if isinstance(bit_rates, list):
        for entry in bit_rates:
            if not isinstance(entry, dict):
                continue
            score = max(
                as_int(entry.get("bit_rate")),
                as_int(entry.get("bitRate")),
                as_int(entry.get("data_size")),
                as_int(entry.get("dataSize")),
            )
            urls: list[str] = []
            for key in ("play_addr", "playAddr", "play_addr_265", "playAddr265"):
                urls.extend(url_list(entry.get(key)))
            if urls:
                ranked.append((score, unique_urls(urls)))
    candidates: list[str] = []
    for _score, urls in sorted(ranked, key=lambda pair: pair[0], reverse=True):
        candidates.extend(urls)
    for key in (
        "play_addr",
        "playAddr",
        "play_addr_h264",
        "playAddrH264",
        "download_addr",
        "downloadAddr",
    ):
        candidates.extend(url_list(video.get(key)))
    return unique_urls(candidates)


def cover_urls(item: dict[str, Any]) -> list[str]:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    candidates: list[str] = []
    for key in ("cover", "origin_cover", "originCover", "dynamic_cover", "dynamicCover"):
        candidates.extend(url_list(video.get(key)))
    if not candidates:
        for node in image_nodes(item)[:1]:
            candidates.extend(image_urls(node))
    return unique_urls(candidates)


def music_urls(item: dict[str, Any]) -> list[str]:
    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    candidates: list[str] = []
    for key in ("play_url", "playUrl", "preview_url", "previewUrl"):
        candidates.extend(url_list(music.get(key)))
    return unique_urls(candidates)


def normalize_work(item: dict[str, Any]) -> dict[str, Any]:
    aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
    if not aweme_id:
        raise WorkDownloadError("Creator work is missing aweme_id")
    statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    images = image_nodes(item)
    content_type = "图文" if images else "视频"
    content_route = "note" if images else "video"
    created = as_int(item.get("create_time") or item.get("createTime"))
    recommend_value = statistics.get("recommend_count")
    if recommend_value is None:
        recommend_value = statistics.get("recommendCount")
    account_id = str(
        author.get("unique_id") or author.get("uniqueId") or author.get("short_id") or author.get("shortId") or ""
    )
    stable_creator_id = str(author.get("sec_uid") or author.get("secUid") or author.get("uid") or "")
    creator_snapshot = {
        "nickname": str(author.get("nickname") or author.get("name") or ""),
        "platform_account": account_id,
        "stable_creator_id": stable_creator_id,
        "profile_url": f"https://www.douyin.com/user/{stable_creator_id}" if stable_creator_id else "",
        "bio": str(author.get("signature") or author.get("desc") or ""),
        "followers": optional_int(author.get("follower_count"), author.get("followerCount")),
        "total_likes": optional_int(author.get("total_favorited"), author.get("totalFavorited")),
        "snapshot_at": utc_now() if any((account_id, stable_creator_id, author.get("nickname"), author.get("name"))) else "",
        "source": "current_work_detail",
    }
    return {
        "aweme_id": aweme_id,
        "type": content_type,
        "author": str(author.get("nickname") or author.get("name") or ""),
        "title": str(item.get("desc") or item.get("description") or "").strip(),
        "create_time": created,
        "publish_time": datetime.fromtimestamp(created, CHINA_TIMEZONE).isoformat(timespec="seconds") if created else "",
        "digg_count": as_int(statistics.get("digg_count") or statistics.get("diggCount")),
        "share_count": as_int(statistics.get("share_count") or statistics.get("shareCount")),
        "comment_count": as_int(statistics.get("comment_count") or statistics.get("commentCount")),
        "collect_count": as_int(statistics.get("collect_count") or statistics.get("collectCount")),
        "recommend_count": None if recommend_value is None else as_int(recommend_value),
        "is_pinned": bool(item.get("is_top") or item.get("isTop")),
        "source_url": f"https://www.douyin.com/{content_route}/{aweme_id}",
        "cover_url": (cover_urls(item) or [""])[0],
        "music_title": str(music.get("title") or ""),
        "music_author": str(music.get("author") or ""),
        "music_unavailable_reason": str(music.get("offline_desc") or ""),
        "creator_snapshot": creator_snapshot,
        "_video_urls": video_urls(item),
        "_cover_urls": cover_urls(item),
        "_music_urls": music_urls(item),
        "_image_urls": [image_urls(node) for node in images],
    }


def select_pinned_and_recent(items: Iterable[dict[str, Any]], recent_n: int) -> list[dict[str, Any]]:
    normalized = [normalize_work(item) for item in items]
    pinned = sorted(
        (work for work in normalized if work["is_pinned"]),
        key=lambda work: (work["create_time"], work["aweme_id"]),
        reverse=True,
    )
    pinned_ids = {work["aweme_id"] for work in pinned}
    recent = sorted(
        (work for work in normalized if work["aweme_id"] not in pinned_ids),
        key=lambda work: (work["create_time"], work["aweme_id"]),
        reverse=True,
    )[:recent_n]
    for index, work in enumerate(pinned, 1):
        work["selection_reason"] = "置顶"
        work["selection_rank"] = index
    for index, work in enumerate(recent, 1):
        work["selection_reason"] = "最近"
        work["selection_rank"] = index
    return pinned + recent


def page_type(url: str) -> str:
    value = str(url or "").lower()
    if "/search/" in value or "search?" in value:
        return "search"
    if "/user/" in value:
        return "creator"
    if "/video/" in value or "/note/" in value:
        return "work"
    return "page"


def search_keyword(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("keyword", "query", "q"):
        if query.get(key):
            return str(query[key][0])
    match = re.search(r"/search/([^/?#]+)", parsed.path)
    return urllib.parse.unquote(match.group(1)) if match else ""


def select_visible(
    items: Iterable[dict[str, Any]],
    *,
    selected_ids: Iterable[str] = (),
    limit: int = 0,
    reason: str = "当前页面",
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized = [normalize_work(item) for item in items]
    by_id = {work["aweme_id"]: work for work in normalized}
    requested = [str(value or "").strip() for value in selected_ids if str(value or "").strip()]
    missing: list[str] = []
    if requested:
        selected = []
        for aweme_id in requested:
            if aweme_id in by_id:
                selected.append(by_id[aweme_id])
            else:
                missing.append(aweme_id)
    else:
        selected = normalized
        if limit > 0:
            selected = selected[:limit]
    for index, work in enumerate(selected, 1):
        work["selection_reason"] = reason
        work["selection_rank"] = index
    return selected, missing


def merge_seed_with_observed(seed: dict[str, Any], observed: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(observed or seed)
    for key, value in seed.items():
        if key.startswith("_"):
            if value and not merged.get(key):
                merged[key] = value
            continue
        if value not in (None, "", 0, False) or key in {
            "source_url", "selection_reason", "selection_rank", "source_page_type",
            "source_keyword", "source_rank",
        }:
            if merged.get(key) in (None, "", 0, False) or key.startswith(("source_", "selection_")):
                merged[key] = value
    merged["aweme_id"] = seed["aweme_id"]
    merged["source_url"] = seed["source_url"]
    merged["selection_reason"] = seed.get("selection_reason") or "手动选择"
    merged["selection_rank"] = seed.get("selection_rank") or 1
    for key in ("_video_urls", "_cover_urls", "_music_urls", "_image_urls"):
        merged.setdefault(key, [])
    return merged


def parse_assets(value: str) -> set[str]:
    text = str(value or "").strip().lower()
    if text in {"", "all"}:
        return set(ASSET_KINDS)
    if text in {"none", "data", "metadata"}:
        return set()
    aliases = {"video": "primary", "image": "primary", "music": "audio", "text": "caption"}
    selected = {aliases.get(part.strip(), part.strip()) for part in text.split(",") if part.strip()}
    invalid = selected - ASSET_KINDS
    if invalid:
        raise WorkDownloadError(f"Unsupported --assets values: {', '.join(sorted(invalid))}")
    return selected


def work_file_base(work: dict[str, Any], index: int) -> str:
    publish = str(work.get("publish_time") or "")[:10].replace("-", "") or "日期未知"
    author = sanitize_name(work.get("author"), "作者未知", 24)
    title = sanitize_name(work.get("title"), "未命名作品", 46)
    return sanitize_name(
        f"{index:03d}_{publish}_{author}_{title}_{work['aweme_id']}",
        max_length=128,
    )


def write_caption(folder: Path, work: dict[str, Any]) -> dict[str, Any]:
    title = str(work.get("title") or "").strip()
    if not title:
        return {"status": "not_available", "file": "", "bytes": 0}
    target = folder / "发布文案.txt"
    if target.is_file() and target.stat().st_size > 0:
        return {"status": "skipped_existing", "file": target.name, "bytes": target.stat().st_size}
    target.write_text(title + "\n", encoding="utf-8")
    return {"status": "created", "file": target.name, "bytes": target.stat().st_size}


def discovery_scroll_budget(recent_n: int, requested_scrolls: int) -> int:
    """Return a bounded discovery budget that grows with the requested sample."""
    adaptive = max(5, max(0, recent_n) * 2)
    return max(1, requested_scrolls, min(120, adaptive))


def final_works_status(has_download_errors: bool, recent_selected: int, recent_requested: int) -> str:
    selection_shortfall = recent_selected < recent_requested
    if selection_shortfall and has_download_errors:
        return "partial_selection_and_download_errors"
    if selection_shortfall:
        return "partial_selection_shortfall"
    if has_download_errors:
        return "partial_download_errors"
    return "complete"


def public_work_record(work: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in work.items() if not key.startswith("_")}


def signature_kind(header: bytes) -> str:
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"ID3") or header.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "mp3"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return "unknown"


def file_signature_kind(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return "unknown"
    return signature_kind(header)


def normalize_audio_target(target: Path) -> Path:
    if target.suffix.lower() == ".mp3" and file_signature_kind(target) == "mp4":
        corrected = target.with_suffix(".m4a")
        if corrected.exists() and corrected.stat().st_size > 0:
            target.unlink(missing_ok=True)
        else:
            target.replace(corrected)
        return corrected
    return target


def download_from_candidates(
    candidates: Iterable[str],
    target: Path,
    referer: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if target.suffix.lower() == ".mp3":
        alternate = target.with_suffix(".m4a")
        if alternate.is_file() and alternate.stat().st_size > 0:
            return {"status": "skipped_existing", "file": alternate.name, "bytes": alternate.stat().st_size}
    if target.is_file() and target.stat().st_size > 0:
        normalized_target = normalize_audio_target(target)
        return {"status": "skipped_existing", "file": normalized_target.name, "bytes": normalized_target.stat().st_size}
    normalized_candidates = unique_urls(candidates)
    if not normalized_candidates:
        return {"status": "not_available", "file": "", "bytes": 0}
    target.parent.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    partial = target.with_suffix(target.suffix + ".part")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "*/*",
    }
    for candidate in normalized_candidates:
        try:
            request = urllib.request.Request(candidate, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            size = partial.stat().st_size if partial.exists() else 0
            if size <= 0:
                raise WorkDownloadError("empty response body")
            partial.replace(target)
            target = normalize_audio_target(target)
            return {
                "status": "downloaded",
                "file": target.name,
                "bytes": size,
                "host": urllib.parse.urlparse(candidate).netloc,
            }
        except Exception as exc:  # noqa: BLE001 - preserve bounded candidate failures
            failures.append(f"{type(exc).__name__}: {exc}")
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "status": "failed",
        "file": target.name,
        "bytes": 0,
        "errors": failures[-3:],
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download selected public Douyin works through visible signed-in Chrome."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--creator", help="Douyin creator profile URL")
    source.add_argument("--source-page", help="Douyin creator or search result page URL")
    source.add_argument("--selection-file", help="BrandBAI selection JSON or plugin works Excel")
    source.add_argument("--video", action="append", help="Explicit video/note URL; repeat for multiple works")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned works to add")
    parser.add_argument("--limit", type=int, default=0, help="Maximum works from a generic/search page; 0 keeps all observed")
    parser.add_argument("--selected-id", action="append", default=[], help="Explicit work ID to keep from --source-page")
    parser.add_argument(
        "--assets",
        default="primary,cover,audio,caption",
        help="Comma list: primary,cover,audio,caption; use none for metadata only",
    )
    parser.add_argument("--profile-dir", required=True, help="Persistent Chrome profile outside output")
    parser.add_argument("--out", required=True, help="New or resumable output directory")
    parser.add_argument(
        "--media-dir",
        default="",
        help="Optional media directory; defaults to <out>/media",
    )
    parser.add_argument(
        "--media-label",
        default="",
        help="Relative folder label written into works.json when --media-dir is external",
    )
    parser.add_argument("--chrome-path", default="")
    parser.add_argument(
        "--scrolls",
        type=int,
        default=5,
        help="Minimum discovery scroll rounds; automatically expands with --recent",
    )
    parser.add_argument("--login-wait", type=float, default=30.0)
    parser.add_argument("--download-timeout", type=float, default=180.0)
    parser.add_argument("--zip", action="store_true", help="Create a sibling ZIP after the works task finishes")
    parser.add_argument("--zip-path", default="", help="Optional ZIP path; must be outside --out")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def input_mode(args: argparse.Namespace) -> str:
    if getattr(args, "selection_file", ""):
        return "selection_file"
    if getattr(args, "video", None):
        return "explicit_works"
    if getattr(args, "source_page", ""):
        return "visible_page"
    return "creator_pinned_recent"


def source_page_url(args: argparse.Namespace) -> str:
    return str(getattr(args, "creator", "") or getattr(args, "source_page", "") or "").strip()


def selection_description(args: argparse.Namespace) -> str:
    mode = input_mode(args)
    if mode == "creator_pinned_recent":
        return f"all visible pinned works plus latest {args.recent} non-pinned works"
    if mode == "visible_page":
        if getattr(args, "selected_id", []):
            return f"{len(args.selected_id)} selected work IDs from the visible page"
        return f"up to {args.limit} observed works" if args.limit > 0 else "all observed works from the visible page"
    if mode == "selection_file":
        return "works listed in the BrandBAI selection file"
    return f"{len(args.video or [])} explicit work URLs"


def input_identity(args: argparse.Namespace) -> dict[str, Any]:
    selection_file = str(getattr(args, "selection_file", "") or "")
    selection_identity: dict[str, str] | str = ""
    if selection_file:
        path = Path(selection_file).expanduser().resolve()
        selection_identity = {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing",
        }
    return {
        "mode": input_mode(args),
        "creator": str(getattr(args, "creator", "") or ""),
        "source_page": str(getattr(args, "source_page", "") or ""),
        "selection_file": selection_identity,
        "videos": [str(value) for value in getattr(args, "video", []) or []],
        "recent": int(getattr(args, "recent", 0) or 0),
        "limit": int(getattr(args, "limit", 0) or 0),
        "selected_ids": [str(value) for value in getattr(args, "selected_id", []) or []],
        "assets": str(getattr(args, "assets", "")),
    }


def resolve_zip_path(args: argparse.Namespace) -> Path:
    return (
        Path(args.zip_path).expanduser().resolve()
        if getattr(args, "zip_path", "")
        else Path(args.out).expanduser().resolve().with_suffix(".zip")
    )


def dry_plan(args: argparse.Namespace) -> dict[str, Any]:
    source_value = args.creator or args.source_page or args.selection_file or list(args.video or [])
    return {
        "provider": PROVIDER,
        "source": source_value,
        "selection_mode": input_mode(args),
        "selection": selection_description(args),
        "recent_non_pinned": args.recent,
        "assets": sorted(parse_assets(args.assets)),
        "browser": "one visible persistent Chrome context",
        "cookies_exported": False,
        "signature_generation": False,
        "output": str(Path(args.out).resolve()),
        "media_output": str(
            Path(args.media_dir).expanduser().resolve()
            if args.media_dir
            else Path(args.out).resolve() / "media"
        ),
        "zip_output": str(resolve_zip_path(args)) if args.zip else "",
    }


def collect_visible_works(context: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    raw_items: dict[str, dict[str, Any]] = {}
    response_count = 0
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60_000)
    target_url = source_page_url(args)
    target_type = page_type(target_url)
    target_count = max(
        1,
        int(getattr(args, "limit", 0) or 0),
        int(getattr(args, "recent", 0) or 0),
        len(getattr(args, "selected_id", []) or []),
    )

    def on_response(response: Any) -> None:
        nonlocal response_count
        url = str(response.url or "").lower()
        if not any(token in url for token in RESPONSE_TOKENS):
            return
        try:
            if response.status != 200:
                return
            posts = pick_posts(response.json())
            if posts:
                response_count += 1
            for item in posts:
                aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
                if aweme_id:
                    raw_items[aweme_id] = item
        except Exception:
            return

    page.on("response", on_response)
    page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(max(1_500, int(args.login_wait * 1000)))

    # A login or verification completed during the wait may not replay the first
    # creator response. Reload once when the observed first page cannot satisfy N.
    if len(raw_items) < target_count:
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)

    idle = 0
    for _ in range(discovery_scroll_budget(target_count, args.scrolls)):
        before = len(raw_items)
        page.mouse.wheel(0, 1_800)
        page.wait_for_timeout(1_200)
        idle = idle + 1 if len(raw_items) == before else 0
        if idle >= 2 and len(raw_items) >= target_count:
            break
    page.wait_for_timeout(1_500)
    if target_type == "search":
        for aweme_id in search_dom_work_ids(page):
            raw_items.setdefault(
                aweme_id,
                {"aweme_id": aweme_id, "__brandbai_dom_seed": True},
            )
    visible_candidate_ids = list(raw_items)
    if input_mode(args) == "creator_pinned_recent":
        selected = select_pinned_and_recent(raw_items.values(), args.recent)
        missing_ids: list[str] = []
    else:
        reason = "搜索结果" if target_type == "search" else "页面选择"
        selected, missing_ids = select_visible(
            raw_items.values(),
            selected_ids=getattr(args, "selected_id", []) or [],
            limit=int(getattr(args, "limit", 0) or 0),
            reason=reason,
        )
    # Search cards expose stable work IDs but not always the full JSON payload.
    # Enrich only the selected cards through their ordinary visible detail page.
    if target_type == "search":
        selected_ids = [work["aweme_id"] for work in selected]
        for aweme_id in selected_ids:
            item = raw_items.get(aweme_id, {})
            if not item.get("__brandbai_dom_seed"):
                continue
            page.goto(
                f"https://www.douyin.com/video/{aweme_id}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(1_500)
        candidates = [raw_items[aweme_id] for aweme_id in visible_candidate_ids if aweme_id in raw_items]
        selected, missing_ids = select_visible(
            candidates,
            selected_ids=getattr(args, "selected_id", []) or [],
            limit=int(getattr(args, "limit", 0) or 0),
            reason="搜索结果",
        )
        missing_metadata = []
        for work in selected:
            observed = not bool(raw_items[work["aweme_id"]].get("__brandbai_dom_seed"))
            work["_metadata_observed"] = observed
            if not observed:
                missing_metadata.append(work["aweme_id"])
        args._missing_metadata_ids = missing_metadata
    keyword = search_keyword(target_url) if target_type == "search" else ""
    for index, work in enumerate(selected, 1):
        work["source_page_type"] = target_type
        work["source_keyword"] = keyword
        work["source_rank"] = index
    args._missing_selected_ids = missing_ids
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass
    return selected, response_count, len(visible_candidate_ids)


def selection_seeds(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if getattr(args, "selection_file", ""):
        try:
            return load_selection(args.selection_file)
        except SelectionContractError as exc:
            raise WorkDownloadError(str(exc)) from exc
    seeds: list[dict[str, Any]] = []
    for index, url in enumerate(getattr(args, "video", []) or [], 1):
        try:
            seeds.append(seed_from_url(url, index))
        except SelectionContractError as exc:
            raise WorkDownloadError(str(exc)) from exc
    seeds = deduplicate_seeds(seeds)
    if not seeds:
        raise WorkDownloadError("No usable explicit works were provided")
    return seeds, {
        "contract": "brandbai.douyin.selection/v1",
        "page_type": "explicit",
        "selection_mode": "explicit_urls",
        "selection_reason": "明确作品",
        "download": {},
    }


def collect_seeded_works(context: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    seeds, metadata = selection_seeds(args)
    requested_assets = parse_assets(getattr(args, "assets", "all"))
    observed: dict[str, dict[str, Any]] = {}
    response_count = 0
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60_000)

    def on_response(response: Any) -> None:
        nonlocal response_count
        url = str(response.url or "").lower()
        if not any(token in url for token in RESPONSE_TOKENS):
            return
        try:
            if response.status != 200:
                return
            posts = pick_posts(response.json())
            if posts:
                response_count += 1
            for item in posts:
                aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
                if aweme_id:
                    observed[aweme_id] = item
        except Exception:
            return

    page.on("response", on_response)
    try:
        navigated = 0
        for seed in seeds:
            primary_ready = bool(seed.get("_image_urls")) if seed.get("type") == "图文" else bool(seed.get("_video_urls"))
            metadata_ready = bool(
                seed.get("author")
                and seed.get("title")
                and (seed.get("publish_time") or seed.get("create_time"))
            )
            needs_enrichment = (
                not metadata_ready
                or ("primary" in requested_assets and not primary_ready)
                or ("cover" in requested_assets and not seed.get("_cover_urls"))
                or ("audio" in requested_assets and not seed.get("_music_urls"))
            )
            if not needs_enrichment:
                continue
            page.goto(seed["source_url"], wait_until="domcontentloaded", timeout=60_000)
            wait_ms = max(1_500, int(args.login_wait * 1000)) if navigated == 0 else 1_500
            page.wait_for_timeout(wait_ms)
            navigated += 1
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    selected: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    for seed in seeds:
        raw = observed.get(seed["aweme_id"])
        rich = normalize_work(raw) if raw else None
        metadata_ready = bool(
            seed.get("author")
            and seed.get("title")
            and (seed.get("publish_time") or seed.get("create_time"))
        )
        primary_ready = bool(seed.get("_image_urls")) if seed.get("type") == "图文" else bool(seed.get("_video_urls"))
        requested_ready = all((
            kind == "caption"
            or kind == "primary" and primary_ready
            or kind == "cover" and bool(seed.get("_cover_urls"))
            or kind == "audio" and bool(seed.get("_music_urls"))
        ) for kind in requested_assets)
        if rich is None and not (requested_ready and metadata_ready):
            missing_metadata.append(seed["aweme_id"])
        merged = merge_seed_with_observed(seed, rich)
        merged["_metadata_observed"] = raw is not None or metadata_ready
        selected.append(merged)
    args._missing_selected_ids = []
    args._missing_metadata_ids = missing_metadata
    args._selection_metadata = metadata
    return selected, response_count, len(observed)


def run(args: argparse.Namespace, browser_context: Any = None) -> int:
    if args.recent < 0:
        raise WorkDownloadError("--recent cannot be negative")
    if args.scrolls < 1:
        raise WorkDownloadError("--scrolls must be positive")
    if int(getattr(args, "limit", 0) or 0) < 0:
        raise WorkDownloadError("--limit cannot be negative")
    requested_assets = parse_assets(getattr(args, "assets", "all"))
    if args.dry_run:
        print(json.dumps(dry_plan(args), ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out).resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    media_dir = (
        Path(args.media_dir).expanduser().resolve()
        if args.media_dir
        else out_dir / "media"
    )
    for target in (out_dir, media_dir):
        if target == profile_dir or target in profile_dir.parents or profile_dir in target.parents:
            raise WorkDownloadError("Keep --profile-dir and all outputs in separate directory trees")
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    media_label = Path(args.media_label.strip()) if args.media_label.strip() else (
        Path(media_dir.name) if args.media_dir else Path("media")
    )
    manifest_path = out_dir / "download_manifest.json"
    works_path = out_dir / "works.json"
    manifest: dict[str, Any] = {
        "provider": PROVIDER,
        "status": "running",
        "started_at": utc_now(),
        "creator": str(getattr(args, "creator", "") or ""),
        "source_page": source_page_url(args),
        "selection_file": Path(args.selection_file).name if getattr(args, "selection_file", "") else "",
        "selection": input_mode(args),
        "selection_description": selection_description(args),
        "requested_recent_non_pinned": args.recent,
        "requested_limit": int(getattr(args, "limit", 0) or 0),
        "requested_work_ids": list(getattr(args, "selected_id", []) or []),
        "requested_assets": sorted(requested_assets),
        "input_identity": input_identity(args),
        "zip_requested": bool(getattr(args, "zip", False)),
        "cookies_exported": False,
        "signature_generation": False,
        "warnings": [],
        "works": [],
    }
    write_json(manifest_path, manifest)
    if browser_context is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise WorkDownloadError("Playwright is required for the browser route") from exc
        chrome_path = find_chrome_path(args.chrome_path)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=chrome_path,
                headless=False,
                accept_downloads=False,
                viewport=None,
                args=["--start-maximized", "--no-first-run", "--no-default-browser-check"],
            )
            try:
                collector = collect_seeded_works if input_mode(args) in {"selection_file", "explicit_works"} else collect_visible_works
                selected, response_count, visible_work_count = collector(context, args)
            finally:
                context.close()
    else:
        collector = collect_seeded_works if input_mode(args) in {"selection_file", "explicit_works"} else collect_visible_works
        selected, response_count, visible_work_count = collector(browser_context, args)

    manifest["browser_context_mode"] = (
        "shared_all_context" if browser_context is not None else "standalone_context"
    )
    manifest["browser_launches_total"] = 1
    manifest["browser_launches_owned"] = 0 if browser_context is not None else 1

    if input_mode(args) == "creator_pinned_recent" and len([work for work in selected if work["selection_reason"] == "最近"]) < args.recent:
        manifest["warnings"].append(
            f"Only {len([work for work in selected if work['selection_reason'] == '最近'])}/"
            f"{args.recent} recent non-pinned works were visible"
        )
    missing_selected_ids = list(getattr(args, "_missing_selected_ids", []) or [])
    missing_metadata_ids = list(getattr(args, "_missing_metadata_ids", []) or [])
    if missing_selected_ids:
        manifest["warnings"].append(
            f"{len(missing_selected_ids)} requested work IDs were not observed on the page"
        )
    if missing_metadata_ids:
        manifest["warnings"].append(
            f"{len(missing_metadata_ids)} selected works had no retrievable media metadata"
        )
    if not selected:
        manifest["status"] = "failed_no_visible_works"
        manifest["finished_at"] = utc_now()
        manifest["profile_responses_observed"] = response_count
        write_json(manifest_path, manifest)
        raise WorkDownloadError("No visible creator work metadata was observed; check login or verification")

    selected_recent_count = len(
        [work for work in selected if work["selection_reason"] == "最近"]
    )
    manifest.update(
        {
            "status": "downloading",
            "profile_responses_observed": response_count,
            "visible_works_observed": visible_work_count,
            "requested_scroll_rounds": args.scrolls,
            "effective_scroll_budget": discovery_scroll_budget(
                max(args.recent, int(getattr(args, "limit", 0) or 0), 1), args.scrolls
            ),
            "pinned_selected": len(
                [work for work in selected if work["selection_reason"] == "置顶"]
            ),
            "recent_selected": selected_recent_count,
            "selection_complete": not missing_selected_ids and (
                selected_recent_count >= args.recent
                if input_mode(args) == "creator_pinned_recent"
                else len(selected) > 0
            ),
            "works_selected": len(selected),
            "selected_work_ids": [work["aweme_id"] for work in selected],
            "missing_selected_work_ids": missing_selected_ids,
            "missing_metadata_work_ids": missing_metadata_ids,
            "selection_metadata": getattr(args, "_selection_metadata", {}),
        }
    )
    write_json(manifest_path, manifest)

    public_works: list[dict[str, Any]] = []
    for overall_index, work in enumerate(selected, 1):
        reason_label = str(work.get("selection_reason") or "选择")
        if reason_label == "最近":
            reason_label = f"最近{work['selection_rank']:02d}"
        folder_name = work_file_base(work, overall_index)
        folder = media_dir / folder_name
        if requested_assets:
            folder.mkdir(parents=True, exist_ok=True)
            work["local_folder"] = str(media_label / folder_name)
        else:
            work["local_folder"] = ""
        downloads: dict[str, Any] = {}
        if "primary" not in requested_assets:
            downloads["images" if work["type"] == "图文" else "video"] = {
                "status": "not_requested", "file": "", "bytes": 0
            }
        elif work["type"] == "图文":
            image_results: list[dict[str, Any]] = []
            for image_index, candidates in enumerate(work["_image_urls"], 1):
                image_results.append(
                    download_from_candidates(
                        candidates,
                        folder / f"图文_{image_index:02d}.webp",
                        work["source_url"],
                        args.download_timeout,
                    )
                )
            downloads["images"] = image_results
        else:
            downloads["video"] = download_from_candidates(
                work["_video_urls"],
                folder / "视频.mp4",
                work["source_url"],
                args.download_timeout,
            )
        downloads["cover"] = (
            download_from_candidates(
                work["_cover_urls"], folder / "封面.jpg", work["source_url"], args.download_timeout
            )
            if "cover" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        downloads["music"] = (
            download_from_candidates(
                work["_music_urls"], folder / "原声.mp3", work["source_url"], args.download_timeout
            )
            if "audio" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        downloads["caption"] = (
            write_caption(folder, work)
            if "caption" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        work["downloads"] = downloads
        flat_results: list[dict[str, Any]] = []
        for value in downloads.values():
            flat_results.extend(value if isinstance(value, list) else [value])
        failed = [result for result in flat_results if result.get("status") == "failed"]
        metadata_shortfall = (
            not bool(work.get("_metadata_observed", True))
            and bool(requested_assets & {"primary", "cover", "audio"})
        )
        work["download_status"] = "完成" if not failed and not metadata_shortfall else "部分完成"
        public = public_work_record(work)
        public_works.append(public)
        manifest["works"] = public_works
        write_json(works_path, public_works)
        write_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "event": "work_downloaded",
                    "index": overall_index,
                    "total": len(selected),
                    "aweme_id": work["aweme_id"],
                    "selection": reason_label,
                    "status": work["download_status"],
                },
                ensure_ascii=False,
            )
        )

    partial = [work for work in public_works if work.get("download_status") != "完成"]
    recent_selected = len([work for work in public_works if work["selection_reason"] == "最近"])
    if input_mode(args) == "creator_pinned_recent":
        status = final_works_status(bool(partial), recent_selected, args.recent)
    elif missing_selected_ids:
        status = "partial_selection_and_download_errors" if partial else "partial_selection_shortfall"
    elif missing_metadata_ids and requested_assets & {"primary", "cover", "audio"}:
        status = "partial_metadata_unavailable"
    else:
        status = "partial_download_errors" if partial else "complete"
    manifest.update(
        {
            "status": status,
            "finished_at": utc_now(),
            "profile_responses_observed": response_count,
            "visible_works_observed": visible_work_count,
            "requested_scroll_rounds": args.scrolls,
            "effective_scroll_budget": discovery_scroll_budget(
                max(args.recent, int(getattr(args, "limit", 0) or 0), 1), args.scrolls
            ),
            "pinned_selected": len([work for work in public_works if work["selection_reason"] == "置顶"]),
            "recent_selected": recent_selected,
            "selection_complete": not missing_selected_ids and (
                recent_selected >= args.recent
                if input_mode(args) == "creator_pinned_recent"
                else len(public_works) > 0
            ),
            "works_selected": len(public_works),
            "works_complete": len(public_works) - len(partial),
            "works_partial": len(partial),
            "works": public_works,
        }
    )
    write_json(works_path, public_works)
    write_json(manifest_path, manifest)
    if getattr(args, "zip", False):
        package_result = package_directory(out_dir, resolve_zip_path(args))
        manifest["package"] = {**package_result, "zip": Path(package_result["zip"]).name}
        write_json(manifest_path, manifest)
    print(json.dumps({key: manifest[key] for key in (
        "status", "visible_works_observed", "pinned_selected", "recent_selected",
        "works_selected", "works_complete", "works_partial",
    )}, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "complete" else 3


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(parse_args())
    except WorkDownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
