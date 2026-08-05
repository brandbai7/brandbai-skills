"""Unified entry point for BrandBAI Douyin works and comment collection.

This launcher deliberately stops at collection. It delegates to the existing
browser collectors and does not prepare semantic batches or analysis outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


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


def unique_work_urls(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        match = AWEME_ID_RE.search(value)
        key = match.group(1) if match else value
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BrandBAI foundation collector: creator works or work comments"
    )
    subparsers = parser.add_subparsers(dest="capability", required=True)

    works = subparsers.add_parser(
        "works", help="Download all visible pinned works plus latest N non-pinned works"
    )
    works.add_argument("--creator", required=True, help="Douyin creator profile URL")
    works.add_argument("--recent", type=int, default=5, help="Recent non-pinned works to add")
    works.add_argument("--scrolls", type=int, default=5)
    works.add_argument("--download-timeout", type=float, default=180.0)
    works.add_argument("--media-dir", default="")
    works.add_argument("--media-label", default="")
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
    all_in_one.add_argument("--creator", required=True, help="Douyin creator profile URL")
    all_in_one.add_argument("--recent", type=int, default=5)
    all_in_one.add_argument("--scrolls", type=int, default=5)
    all_in_one.add_argument("--download-timeout", type=float, default=180.0)
    all_in_one.add_argument("--include-replies", action="store_true")
    all_in_one.add_argument("--max-comments-per-video", type=int, default=0)
    all_in_one.add_argument("--max-ui-actions", type=int, default=2500)
    all_in_one.add_argument("--idle-rounds", type=int, default=5)
    all_in_one.add_argument("--scroll-delay", type=float, default=1.2)
    all_in_one.add_argument("--reply-batch-size", type=int, default=5)
    all_in_one.add_argument("--reply-sweeps", type=int, default=3)
    all_in_one.add_argument("--page-timeout", type=float, default=60.0)
    all_in_one.add_argument("--privacy-mode", choices=("hash", "raw"), default="hash")
    all_in_one.add_argument("--diagnostic-trace", action="store_true")
    all_in_one.add_argument(
        "--preview-dir",
        default="",
        help="Optional workbook QA directory; defaults to sibling <delivery>_QA",
    )
    add_common_browser_args(all_in_one)
    return parser


def child_command(args: argparse.Namespace, scripts_dir: Path | None = None) -> list[str]:
    scripts_dir = scripts_dir or Path(__file__).resolve().parent
    if args.capability == "works":
        command = [
            sys.executable,
            str(scripts_dir / "download_creator_works.py"),
            "--creator", args.creator,
            "--recent", str(args.recent),
            "--profile-dir", args.profile_dir,
            "--out", args.out,
            "--scrolls", str(args.scrolls),
            "--login-wait", str(args.login_wait),
            "--download-timeout", str(args.download_timeout),
        ]
        if args.media_dir:
            command.extend(["--media-dir", args.media_dir])
        if args.media_label:
            command.extend(["--media-label", args.media_label])
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


def all_plan(args: argparse.Namespace) -> dict[str, Any]:
    delivery_dir = Path(args.out).expanduser().resolve()
    preview_dir = (
        Path(args.preview_dir).expanduser().resolve()
        if args.preview_dir
        else delivery_dir.parent / f"{delivery_dir.name}_QA"
    )
    return {
        "capability": "all",
        "creator": args.creator,
        "selection": f"all visible pinned works plus latest {args.recent} non-pinned works",
        "comments": "top-level plus replies" if args.include_replies else "top-level only",
        "delivery": str(delivery_dir),
        "ordinary_files": ["01_作品清单.xlsx", "02_评论明细.xlsx", "03_作品素材", "04_采集说明.md"],
        "raw_data": ["data/作品采集", "data/评论采集"],
        "preview_dir": str(preview_dir),
        "analysis_included": False,
    }


def run_all(
    args: argparse.Namespace,
    scripts_dir: Path | None = None,
    runner: Any = subprocess.run,
) -> int:
    configure_output()
    scripts_dir = scripts_dir or Path(__file__).resolve().parent
    if args.recent < 0:
        raise FoundationError("--recent cannot be negative")
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
        recent=args.recent,
        profile_dir=args.profile_dir,
        out=str(works_out),
        media_dir=str(media_dir),
        media_label="03_作品素材",
        chrome_path=args.chrome_path,
        scrolls=args.scrolls,
        login_wait=args.login_wait,
        download_timeout=args.download_timeout,
        dry_run=False,
    )
    works_result = runner(child_command(works_args, scripts_dir), check=False)
    if works_result.returncode not in (0, 3):
        return int(works_result.returncode)
    if not works_json.is_file():
        raise FoundationError(f"Works stage did not create: {works_json}")

    comments_args = argparse.Namespace(
        capability="comments",
        works_json=str(works_json),
        video=[],
        creator=None,
        videos=max(args.recent, 1),
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
        login_wait=args.login_wait,
        privacy_mode=args.privacy_mode,
        diagnostic_trace=args.diagnostic_trace,
        dry_run=False,
    )
    comments_result = runner(child_command(comments_args, scripts_dir), check=False)
    if comments_result.returncode not in (0, 3):
        return int(comments_result.returncode)

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
    return 3 if 3 in (works_result.returncode, comments_result.returncode) else 0


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
