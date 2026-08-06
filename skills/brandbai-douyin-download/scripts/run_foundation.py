"""Unified entry point for BrandBAI Douyin works and comment collection.

This launcher deliberately stops at collection. It delegates to the existing
browser collectors and does not prepare semantic batches or analysis outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from package_delivery import package_directory


AWEME_ID_RE = re.compile(r"(?:/video/|/note/)(\d{10,})")


class FoundationError(RuntimeError):
    pass


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_runtime_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": utc_now(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def unique_work_urls(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        match = AWEME_ID_RE.search(value)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        modal_id = str((query.get("modal_id") or [""])[0]).strip()
        key = match.group(1) if match else modal_id if modal_id.isdigit() else value
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def load_work_urls(path: str | Path) -> list[str]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FoundationError(f"works.json not found: {source}")
    try:
        payload: Any = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundationError(f"Cannot read works.json: {source}") from exc

    rows = payload.get("works") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise FoundationError("works.json must be a list, or an object containing a works list")

    urls: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_url = str(row.get("source_url") or "").strip()
        if source_url:
            urls.append(source_url)
            continue
        aweme_id = str(row.get("aweme_id") or "").strip()
        if not aweme_id:
            continue
        route = "note" if str(row.get("type") or "").strip() in {"图文", "note"} else "video"
        urls.append(f"https://www.douyin.com/{route}/{aweme_id}")
    urls = unique_work_urls(urls)
    if not urls:
        raise FoundationError(f"No usable work URLs found in: {source}")
    return urls


def add_common_browser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile-dir", required=True, help="Persistent Chrome profile outside output")
    parser.add_argument("--out", required=True, help="New or resumable output directory")
    parser.add_argument("--chrome-path", default="")
    parser.add_argument("--login-wait", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")


def add_work_source_args(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--creator", help="Douyin creator profile URL")
    source.add_argument("--source-page", help="Douyin creator or search result page URL")
    source.add_argument("--selection-file", help="BrandBAI selection JSON or plugin works Excel")
    source.add_argument("--video", action="append", help="Explicit video/note URL; repeat for multiple works")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned works to add for --creator")
    parser.add_argument("--limit", type=int, default=0, help="Maximum observed works from --source-page; 0 keeps all")
    parser.add_argument("--selected-id", action="append", default=[], help="Work ID to keep from --source-page")
    parser.add_argument(
        "--assets",
        default="primary,cover,audio,caption",
        help="Comma list: primary,cover,audio,caption; use none for metadata only",
    )


def add_package_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--zip", action="store_true", help="Create a sibling ZIP after successful delivery build")
    parser.add_argument("--zip-path", default="", help="Optional ZIP path outside the delivery directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BrandBAI foundation collector: creator works or work comments"
    )
    subparsers = parser.add_subparsers(dest="capability", required=True)

    works = subparsers.add_parser(
        "works", help="Download creator, search-selected, or explicit Douyin works"
    )
    add_work_source_args(works)
    works.add_argument("--scrolls", type=int, default=5)
    works.add_argument("--download-timeout", type=float, default=180.0)
    works.add_argument("--media-dir", default="")
    works.add_argument("--media-label", default="")
    add_package_args(works)
    add_common_browser_args(works)

    comments = subparsers.add_parser(
        "comments", help="Collect comments for explicit works or works selected by the works collector"
    )
    comments.add_argument("--works-json", help="works.json created by the works collector")
    comments.add_argument("--video", action="append", default=[], help="Explicit video/note URL or ID")
    comments.add_argument("--creator", help="Creator profile URL for direct visible-link discovery")
    comments.add_argument("--videos", type=int, default=20, help="Visible works to discover from creator page")
    comments.add_argument(
        "--include-replies",
        action="store_true",
        help="Experimental: also expand second-level replies; not part of the stable completion promise",
    )
    comments.add_argument("--max-comments-per-video", type=int, default=0)
    comments.add_argument("--max-ui-actions", type=int, default=2500)
    comments.add_argument("--idle-rounds", type=int, default=5)
    comments.add_argument("--scroll-delay", type=float, default=1.2)
    comments.add_argument("--reply-batch-size", type=int, default=5)
    comments.add_argument("--reply-sweeps", type=int, default=3)
    comments.add_argument("--page-timeout", type=float, default=60.0)
    comments.add_argument("--privacy-mode", choices=("hash", "raw"), default="hash")
    comments.add_argument("--diagnostic-trace", action="store_true")
    add_common_browser_args(comments)

    all_in_one = subparsers.add_parser(
        "all",
        help="Collect works and top-level comments, then build the ordinary Excel delivery",
    )
    add_work_source_args(all_in_one)
    all_in_one.add_argument("--scrolls", type=int, default=5)
    all_in_one.add_argument("--download-timeout", type=float, default=180.0)
    all_in_one.add_argument("--include-replies", action="store_true")
    all_in_one.add_argument(
        "--skip-comments",
        action="store_true",
        help="Build a works/data delivery without collecting comments",
    )
    all_in_one.add_argument("--max-comments-per-video", type=int, default=0)
    all_in_one.add_argument("--max-ui-actions", type=int, default=2500)
    all_in_one.add_argument("--idle-rounds", type=int, default=5)
    all_in_one.add_argument("--scroll-delay", type=float, default=1.2)
    all_in_one.add_argument("--reply-batch-size", type=int, default=5)
    all_in_one.add_argument("--reply-sweeps", type=int, default=3)
    all_in_one.add_argument("--page-timeout", type=float, default=60.0)
    all_in_one.add_argument(
        "--comment-login-wait",
        type=float,
        default=60.0,
        help="Comment-surface wait per work; independent from the creator-page login wait",
    )
    all_in_one.add_argument("--privacy-mode", choices=("hash", "raw"), default="hash")
    all_in_one.add_argument("--diagnostic-trace", action="store_true")
    all_in_one.add_argument(
        "--resume",
        action="store_true",
        help="Reuse a matching complete works stage and the existing comment checkpoint",
    )
    all_in_one.add_argument(
        "--preview-dir",
        default="",
        help="Optional workbook QA directory; defaults to sibling <delivery>_QA",
    )
    add_package_args(all_in_one)
    add_common_browser_args(all_in_one)
    return parser


def child_command(args: argparse.Namespace, scripts_dir: Path | None = None) -> list[str]:
    scripts_dir = scripts_dir or Path(__file__).resolve().parent
    if args.capability == "works":
        command = [
            sys.executable,
            str(scripts_dir / "download_creator_works.py"),
            "--recent", str(args.recent),
            "--profile-dir", args.profile_dir,
            "--out", args.out,
            "--scrolls", str(args.scrolls),
            "--login-wait", str(args.login_wait),
            "--download-timeout", str(args.download_timeout),
            "--limit", str(args.limit),
            "--assets", args.assets,
        ]
        if args.creator:
            command.extend(["--creator", args.creator])
        elif args.source_page:
            command.extend(["--source-page", args.source_page])
        elif args.selection_file:
            command.extend(["--selection-file", args.selection_file])
        else:
            for url in args.video or []:
                command.extend(["--video", url])
        for aweme_id in args.selected_id:
            command.extend(["--selected-id", aweme_id])
        if args.media_dir:
            command.extend(["--media-dir", args.media_dir])
        if args.media_label:
            command.extend(["--media-label", args.media_label])
        if args.zip:
            command.append("--zip")
        if args.zip_path:
            command.extend(["--zip-path", args.zip_path])
    elif args.capability == "comments":
        explicit_urls = unique_work_urls(list(args.video))
        if not explicit_urls and not args.creator:
            if not args.works_json:
                raise FoundationError("Provide --works-json, at least one --video, or --creator")

        command = [
            sys.executable,
            str(scripts_dir / "browser_collect_comments.py"),
            "--profile-dir", args.profile_dir,
            "--out", args.out,
            "--videos", str(args.videos),
            "--max-comments-per-video", str(args.max_comments_per_video),
            "--max-ui-actions", str(args.max_ui_actions),
            "--idle-rounds", str(args.idle_rounds),
            "--scroll-delay", str(args.scroll_delay),
            "--reply-batch-size", str(args.reply_batch_size),
            "--reply-sweeps", str(args.reply_sweeps),
            "--page-timeout", str(args.page_timeout),
            "--login-wait", str(args.login_wait),
            "--privacy-mode", args.privacy_mode,
        ]
        if args.creator:
            command.extend(["--creator", args.creator])
        if args.works_json:
            command.extend(["--works-json", args.works_json])
        for url in explicit_urls:
            command.extend(["--video", url])
        if args.include_replies:
            command.append("--include-replies")
        if args.diagnostic_trace:
            command.append("--diagnostic-trace")
    else:
        raise FoundationError(f"Unsupported capability: {args.capability}")

    if args.chrome_path:
        command.extend(["--chrome-path", args.chrome_path])
    if args.dry_run:
        command.append("--dry-run")
    return command


def work_input_mode(args: argparse.Namespace) -> str:
    if getattr(args, "selection_file", ""):
        return "selection_file"
    if getattr(args, "video", None):
        return "explicit_works"
    if getattr(args, "source_page", ""):
        return "visible_page"
    return "creator_pinned_recent"


def work_selection_description(args: argparse.Namespace) -> str:
    mode = work_input_mode(args)
    if mode == "creator_pinned_recent":
        return f"all visible pinned works plus latest {args.recent} non-pinned works"
    if mode == "visible_page":
        if args.selected_id:
            return f"{len(args.selected_id)} selected work IDs from the visible page"
        return f"up to {args.limit} observed works" if args.limit > 0 else "all observed works from the visible page"
    if mode == "selection_file":
        return "works listed in the BrandBAI selection JSON or plugin Excel"
    return f"{len(args.video or [])} explicit work URLs"


def work_input_identity(args: argparse.Namespace) -> dict[str, Any]:
    selection_file = str(getattr(args, "selection_file", "") or "")
    selection_identity: dict[str, str] | str = ""
    if selection_file:
        path = Path(selection_file).expanduser().resolve()
        selection_identity = {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing",
        }
    return {
        "mode": work_input_mode(args),
        "creator": str(getattr(args, "creator", "") or ""),
        "source_page": str(getattr(args, "source_page", "") or ""),
        "selection_file": selection_identity,
        "videos": unique_work_urls(getattr(args, "video", []) or []),
        "recent": int(getattr(args, "recent", 0) or 0),
        "limit": int(getattr(args, "limit", 0) or 0),
        "selected_ids": [str(value) for value in getattr(args, "selected_id", []) or []],
        "assets": str(getattr(args, "assets", "")),
    }


def delivery_zip_path(args: argparse.Namespace) -> Path:
    delivery = Path(args.out).expanduser().resolve()
    return Path(args.zip_path).expanduser().resolve() if args.zip_path else delivery.with_suffix(".zip")


def all_plan(args: argparse.Namespace) -> dict[str, Any]:
    delivery_dir = Path(args.out).expanduser().resolve()
    preview_dir = (
        Path(args.preview_dir).expanduser().resolve()
        if args.preview_dir
        else delivery_dir.parent / f"{delivery_dir.name}_QA"
    )
    return {
        "capability": "all",
        "source": args.creator or args.source_page or args.selection_file or list(args.video or []),
        "selection_mode": work_input_mode(args),
        "recent_non_pinned": args.recent,
        "selection": work_selection_description(args),
        "assets": args.assets,
        "comments": (
            "not requested"
            if args.skip_comments
            else "top-level plus replies" if args.include_replies else "top-level only"
        ),
        "max_comments_per_video": args.max_comments_per_video,
        "privacy_mode": args.privacy_mode,
        "works_login_wait": args.login_wait,
        "comment_login_wait": args.comment_login_wait,
        "resume": bool(args.resume),
        "browser_session": (
            "one visible Chrome context for resumed comments; complete works stage skipped"
            if args.resume
            else "one shared visible Chrome context for works and comments"
        ),
        "delivery": str(delivery_dir),
        "ordinary_files": ["01_作品清单.xlsx", "02_评论明细.xlsx", "03_作品素材", "04_采集说明.md"],
        "raw_data": ["data/作品采集", "data/评论采集"],
        "preview_dir": str(preview_dir),
        "runtime_trace": "data/browser_session_trace.jsonl and data/评论采集/browser_runtime_trace.jsonl",
        "analysis_included": False,
        "zip_output": str(delivery_zip_path(args)) if args.zip else "",
    }


def validate_resume_works(
    manifest_path: Path,
    works_json: Path,
    creator: str,
    recent: int,
    expected_identity: dict[str, Any] | None = None,
) -> None:
    if not manifest_path.is_file() or not works_json.is_file():
        raise FoundationError(
            "--resume requires existing complete works.json and download_manifest.json"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundationError(f"Cannot read resume manifest: {manifest_path}") from exc
    if manifest.get("status") != "complete":
        raise FoundationError("--resume requires download_manifest.status=complete")
    recorded_identity = manifest.get("input_identity")
    if expected_identity is not None and isinstance(recorded_identity, dict):
        if recorded_identity != expected_identity:
            raise FoundationError("--resume input selection or asset options do not match the existing works manifest")
    else:
        if str(manifest.get("creator") or "").strip() != str(creator or "").strip():
            raise FoundationError("--resume creator does not match the existing works manifest")
        if int(manifest.get("requested_recent_non_pinned", -1)) != int(recent):
            raise FoundationError("--resume recent count does not match the existing works manifest")
    if int(manifest.get("works_selected", 0)) < 1:
        raise FoundationError("--resume works manifest contains no selected works")


def run_shared_browser_stages(
    works_args: argparse.Namespace,
    comments_args: argparse.Namespace,
    trace_path: Path,
    playwright_factory: Any = None,
    works_runner: Any = None,
    comments_runner: Any = None,
    chrome_finder: Any = None,
    skip_works: bool = False,
    skip_comments: bool = False,
) -> tuple[int, int]:
    if any(value is None for value in (
        playwright_factory, works_runner, comments_runner, chrome_finder
    )):
        try:
            from playwright.sync_api import sync_playwright
            from browser_collect_comments import find_chrome_path, run as run_comments
            from download_creator_works import run as run_works
        except ImportError as exc:
            raise FoundationError(
                "Playwright and the bundled collectors are required for the shared browser route"
            ) from exc
        playwright_factory = playwright_factory or sync_playwright
        works_runner = works_runner or run_works
        comments_runner = comments_runner or run_comments
        chrome_finder = chrome_finder or find_chrome_path

    profile_dir = Path(works_args.profile_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_path = chrome_finder(works_args.chrome_path)
    works_code = 2
    comments_code = 2
    session_id = uuid.uuid4().hex
    append_runtime_event(
        trace_path,
        {
            "event": "browser_session_start",
            "session_id": session_id,
            "resume": bool(skip_works),
            "browser_context_mode": "shared_all_context",
            "browser_launches_total": 1,
        },
    )
    with playwright_factory() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=chrome_path,
                headless=False,
                accept_downloads=False,
                viewport=None,
                args=["--start-maximized", "--no-first-run", "--no-default-browser-check"],
            )
        except Exception as exc:
            append_runtime_event(
                trace_path,
                {
                    "event": "browser_session_launch_error",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                },
            )
            append_runtime_event(
                trace_path,
                {
                    "event": "browser_session_end",
                    "session_id": session_id,
                    "works_exit_code": works_code,
                    "comments_exit_code": comments_code,
                    "close_error_type": "",
                    "launch_error_type": type(exc).__name__,
                },
            )
            raise FoundationError(f"Browser launch failed: {exc}") from exc
        try:
            if skip_works:
                works_code = 0
                append_runtime_event(
                    trace_path,
                    {
                        "event": "works_stage_skipped",
                        "session_id": session_id,
                        "reason": "existing_complete_manifest",
                    },
                )
            else:
                append_runtime_event(
                    trace_path, {"event": "works_stage_start", "session_id": session_id}
                )
                try:
                    works_code = int(works_runner(works_args, browser_context=context))
                except Exception as exc:
                    append_runtime_event(
                        trace_path,
                        {
                            "event": "works_stage_error",
                            "session_id": session_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise FoundationError(f"Works stage failed: {exc}") from exc
                append_runtime_event(
                    trace_path,
                    {
                        "event": "works_stage_end",
                        "session_id": session_id,
                        "exit_code": works_code,
                    },
                )
            if works_code not in (0, 3):
                return works_code, comments_code
            if skip_comments:
                comments_code = 0
                append_runtime_event(
                    trace_path,
                    {"event": "comments_stage_skipped", "session_id": session_id, "reason": "not_requested"},
                )
            else:
                append_runtime_event(
                    trace_path, {"event": "comments_stage_start", "session_id": session_id}
                )
                try:
                    comments_code = int(comments_runner(comments_args, browser_context=context))
                except Exception as exc:
                    append_runtime_event(
                        trace_path,
                        {
                            "event": "comments_stage_error",
                            "session_id": session_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise FoundationError(f"Comments stage failed: {exc}") from exc
                append_runtime_event(
                    trace_path,
                    {
                        "event": "comments_stage_end",
                        "session_id": session_id,
                        "exit_code": comments_code,
                    },
                )
        finally:
            close_error = ""
            try:
                context.close()
            except Exception as exc:
                close_error = type(exc).__name__
            finally:
                append_runtime_event(
                    trace_path,
                    {
                        "event": "browser_session_end",
                        "session_id": session_id,
                        "works_exit_code": works_code,
                        "comments_exit_code": comments_code,
                        "close_error_type": close_error,
                    },
                )
    return works_code, comments_code


def run_all(
    args: argparse.Namespace,
    scripts_dir: Path | None = None,
    runner: Any = subprocess.run,
    browser_stage_runner: Any = run_shared_browser_stages,
) -> int:
    configure_output()
    scripts_dir = scripts_dir or Path(__file__).resolve().parent
    if args.recent < 0:
        raise FoundationError("--recent cannot be negative")
    if args.comment_login_wait < 0:
        raise FoundationError("--comment-login-wait cannot be negative")
    if args.dry_run:
        print(json.dumps(all_plan(args), ensure_ascii=False, indent=2))
        return 0

    delivery_dir = Path(args.out).expanduser().resolve()
    works_out = delivery_dir / "data" / "作品采集"
    comments_out = delivery_dir / "data" / "评论采集"
    media_dir = delivery_dir / "03_作品素材"
    works_json = works_out / "works.json"
    preview_dir = (
        Path(args.preview_dir).expanduser().resolve()
        if args.preview_dir
        else delivery_dir.parent / f"{delivery_dir.name}_QA"
    )

    delivery_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    works_args = argparse.Namespace(
        capability="works",
        creator=args.creator,
        source_page=args.source_page,
        selection_file=args.selection_file,
        video=list(args.video or []),
        recent=args.recent,
        limit=args.limit,
        selected_id=list(args.selected_id),
        assets=args.assets,
        profile_dir=args.profile_dir,
        out=str(works_out),
        media_dir=str(media_dir),
        media_label="03_作品素材",
        chrome_path=args.chrome_path,
        scrolls=args.scrolls,
        login_wait=args.login_wait,
        download_timeout=args.download_timeout,
        zip=False,
        zip_path="",
        dry_run=False,
    )
    comments_args = argparse.Namespace(
        capability="comments",
        works_json=str(works_json),
        video=[],
        creator=None,
        videos=max(args.recent, args.limit, len(args.video or []), 1),
        include_replies=args.include_replies,
        max_comments_per_video=args.max_comments_per_video,
        max_ui_actions=args.max_ui_actions,
        idle_rounds=args.idle_rounds,
        scroll_delay=args.scroll_delay,
        reply_batch_size=args.reply_batch_size,
        reply_sweeps=args.reply_sweeps,
        page_timeout=args.page_timeout,
        profile_dir=args.profile_dir,
        out=str(comments_out),
        chrome_path=args.chrome_path,
        login_wait=args.comment_login_wait,
        privacy_mode=args.privacy_mode,
        diagnostic_trace=args.diagnostic_trace,
        dry_run=False,
    )
    skip_works = False
    if args.resume:
        validate_resume_works(
            works_out / "download_manifest.json",
            works_json,
            args.creator or "",
            args.recent,
            work_input_identity(args),
        )
        skip_works = True
    if skip_works:
        if args.skip_comments:
            works_code, comments_code = browser_stage_runner(
                works_args,
                comments_args,
                delivery_dir / "data" / "browser_session_trace.jsonl",
                skip_works=True,
                skip_comments=True,
            )
        else:
            works_code, comments_code = browser_stage_runner(
                works_args,
                comments_args,
                delivery_dir / "data" / "browser_session_trace.jsonl",
                skip_works=True,
            )
    else:
        if args.skip_comments:
            works_code, comments_code = browser_stage_runner(
                works_args,
                comments_args,
                delivery_dir / "data" / "browser_session_trace.jsonl",
                skip_comments=True,
            )
        else:
            works_code, comments_code = browser_stage_runner(
                works_args,
                comments_args,
                delivery_dir / "data" / "browser_session_trace.jsonl",
            )
    if works_code not in (0, 3):
        return int(works_code)
    if not works_json.is_file():
        raise FoundationError(f"Works stage did not create: {works_json}")
    if args.skip_comments:
        comments_out.mkdir(parents=True, exist_ok=True)
        (comments_out / "comments.csv").write_text(
            "aweme_id,comment_id,root_comment_id,parent_comment_id,reply_level,text,author_pseudonym,create_time,digg_count,reply_count,source_role,source_url,ip_label,is_pinned,is_creator_reply\n",
            encoding="utf-8-sig",
        )
        (comments_out / "run_manifest.json").write_text(
            json.dumps(
                {
                    "status": "not_requested",
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                    "privacy_mode": args.privacy_mode,
                    "videos": [],
                    "comments_exported": 0,
                    "replies_exported": 0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (comments_out / "collection_report.md").write_text(
            "# 评论采集说明\n\n本次任务未请求评论采集。\n",
            encoding="utf-8",
        )
    if comments_code not in (0, 3):
        return int(comments_code)

    builder_source = scripts_dir / "build_foundation_workbooks.py"
    if not builder_source.is_file():
        raise FoundationError(f"Workbook builder not found: {builder_source}")
    workbook_command = [
        sys.executable,
        str(builder_source),
        str(works_json),
        str(works_out / "download_manifest.json"),
        str(comments_out / "comments.csv"),
        str(comments_out / "run_manifest.json"),
        str(delivery_dir),
        "--qa-dir",
        str(preview_dir),
    ]
    workbook_result = runner(workbook_command, check=False)
    expected_files = [
        delivery_dir / "01_作品清单.xlsx",
        delivery_dir / "02_评论明细.xlsx",
        delivery_dir / "04_采集说明.md",
        preview_dir / "workbook_qa.json",
    ]
    if not all(path.is_file() for path in expected_files):
        return int(workbook_result.returncode or 1)
    if workbook_result.returncode:
        print(
            "提示：Excel 构建程序返回了非零状态，但普通版文件与质检记录均已完整落盘。",
            file=sys.stderr,
        )
    if args.zip:
        package_result = package_directory(delivery_dir, delivery_zip_path(args))
        print(json.dumps({"event": "delivery_packaged", **package_result}, ensure_ascii=False))
    return 3 if 3 in (works_code, comments_code) else 0


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.capability == "comments" and args.include_replies:
            print(
                "提示：二级回复采集仍为实验能力；当前稳定完成标准只承诺一级评论。",
                file=sys.stderr,
            )
        if args.capability == "all":
            return run_all(args)
        return subprocess.run(child_command(args), check=False).returncode
    except FoundationError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
