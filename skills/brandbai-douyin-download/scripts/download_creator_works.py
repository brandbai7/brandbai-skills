"""Download pinned plus recent visible Douyin creator works through ordinary Chrome.

This is a clean-room browser route. It observes metadata returned by the normal
signed-in creator page, never exports cookies, never generates request
signatures, and never automates CAPTCHA or access-control bypasses.
"""

from __future__ import annotations

import argparse
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


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MULTISPACE = re.compile(r"\s+")
PROVIDER = "douyin_web_creator_page"
CHINA_TIMEZONE = timezone(timedelta(hours=8))


class WorkDownloadError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


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
    if not isinstance(payload, dict):
        return []
    for key in ("aweme_list", "awemeList", "items"):
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if value[0].get("aweme_id") or value[0].get("awemeId"):
                return value
    for value in payload.values():
        if isinstance(value, dict):
            found = pick_posts(value)
            if found:
                return found
    return []


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
        description="Download all visible pinned works plus the latest N non-pinned works."
    )
    parser.add_argument("--creator", required=True, help="Douyin creator profile URL")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned works to add")
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
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def dry_plan(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "creator": args.creator,
        "selection": "all visible pinned works plus latest non-pinned works",
        "recent_non_pinned": args.recent,
        "media": ["video_or_all_images", "cover", "music"],
        "browser": "one visible persistent Chrome context",
        "cookies_exported": False,
        "signature_generation": False,
        "output": str(Path(args.out).resolve()),
        "media_output": str(
            Path(args.media_dir).expanduser().resolve()
            if args.media_dir
            else Path(args.out).resolve() / "media"
        ),
    }


def collect_visible_works(context: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    raw_items: dict[str, dict[str, Any]] = {}
    response_count = 0
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60_000)

    def on_response(response: Any) -> None:
        nonlocal response_count
        url = str(response.url or "").lower()
        if "aweme/post" not in url and "aweme/listcollection" not in url:
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
    page.goto(args.creator, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(max(1_500, int(args.login_wait * 1000)))

    # A login or verification completed during the wait may not replay the first
    # creator response. Reload once when the observed first page cannot satisfy N.
    if len(raw_items) < args.recent:
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)

    idle = 0
    for _ in range(discovery_scroll_budget(args.recent, args.scrolls)):
        before = len(raw_items)
        page.mouse.wheel(0, 1_800)
        page.wait_for_timeout(1_200)
        idle = idle + 1 if len(raw_items) == before else 0
        if idle >= 2 and len(raw_items) >= args.recent:
            break
    page.wait_for_timeout(1_500)
    selected = select_pinned_and_recent(raw_items.values(), args.recent)
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass
    return selected, response_count, len(raw_items)


def run(args: argparse.Namespace, browser_context: Any = None) -> int:
    if args.recent < 0:
        raise WorkDownloadError("--recent cannot be negative")
    if args.scrolls < 1:
        raise WorkDownloadError("--scrolls must be positive")
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
        "creator": args.creator,
        "selection": "all_visible_pinned_plus_recent_non_pinned",
        "requested_recent_non_pinned": args.recent,
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
                selected, response_count, visible_work_count = collect_visible_works(context, args)
            finally:
                context.close()
    else:
        selected, response_count, visible_work_count = collect_visible_works(browser_context, args)

    manifest["browser_context_mode"] = (
        "shared_all_context" if browser_context is not None else "standalone_context"
    )
    manifest["browser_launches_total"] = 1
    manifest["browser_launches_owned"] = 0 if browser_context is not None else 1

    if len([work for work in selected if work["selection_reason"] == "最近"]) < args.recent:
        manifest["warnings"].append(
            f"Only {len([work for work in selected if work['selection_reason'] == '最近'])}/"
            f"{args.recent} recent non-pinned works were visible"
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
            "effective_scroll_budget": discovery_scroll_budget(args.recent, args.scrolls),
            "pinned_selected": len(
                [work for work in selected if work["selection_reason"] == "置顶"]
            ),
            "recent_selected": selected_recent_count,
            "selection_complete": selected_recent_count >= args.recent,
            "works_selected": len(selected),
            "selected_work_ids": [work["aweme_id"] for work in selected],
        }
    )
    write_json(manifest_path, manifest)

    public_works: list[dict[str, Any]] = []
    for overall_index, work in enumerate(selected, 1):
        reason_label = "置顶" if work["selection_reason"] == "置顶" else f"最近{work['selection_rank']:02d}"
        title_part = sanitize_name(work["title"], fallback=work["aweme_id"], max_length=46)
        folder_name = sanitize_name(
            f"{overall_index:02d}_{reason_label}_{work['aweme_id']}_{title_part}",
            max_length=96,
        )
        folder = media_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        work["local_folder"] = str(media_label / folder_name)
        downloads: dict[str, Any] = {}
        if work["type"] == "图文":
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
        downloads["cover"] = download_from_candidates(
            work["_cover_urls"],
            folder / "封面.jpg",
            work["source_url"],
            args.download_timeout,
        )
        downloads["music"] = download_from_candidates(
            work["_music_urls"],
            folder / "原声.mp3",
            work["source_url"],
            args.download_timeout,
        )
        work["downloads"] = downloads
        flat_results: list[dict[str, Any]] = []
        for value in downloads.values():
            flat_results.extend(value if isinstance(value, list) else [value])
        failed = [result for result in flat_results if result.get("status") == "failed"]
        work["download_status"] = "完成" if not failed else "部分完成"
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
    status = final_works_status(bool(partial), recent_selected, args.recent)
    manifest.update(
        {
            "status": status,
            "finished_at": utc_now(),
            "profile_responses_observed": response_count,
            "visible_works_observed": visible_work_count,
            "requested_scroll_rounds": args.scrolls,
            "effective_scroll_budget": discovery_scroll_budget(args.recent, args.scrolls),
            "pinned_selected": len([work for work in public_works if work["selection_reason"] == "置顶"]),
            "recent_selected": recent_selected,
            "selection_complete": recent_selected >= args.recent,
            "works_selected": len(public_works),
            "works_complete": len(public_works) - len(partial),
            "works_partial": len(partial),
            "works": public_works,
        }
    )
    write_json(works_path, public_works)
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
