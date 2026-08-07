"""Unified note or profile entry for BrandBAI Xiaohongshu collection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_collect_xiaohongshu import collect, normalize_assets
from build_delivery import DeliveryError, build_delivery
from collector_core import (
    CollectionError,
    canonical_note_id,
    canonical_note_url,
    canonical_profile_id,
    canonical_profile_url,
    normalize_note_targets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Xiaohongshu notes into a BrandBAI ordinary delivery")
    parser.add_argument("mode", choices=["note", "comments", "all"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--note", action="append", help="Repeat for more note URLs or note ids")
    source.add_argument("--profile", help="One Xiaohongshu profile URL or profile id")
    source.add_argument("--search", help="One Xiaohongshu search keyword")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned notes; pinned notes are additional")
    parser.add_argument("--max-profile-scroll-actions", type=int, default=80)
    parser.add_argument("--search-limit", type=int, default=10, help="First N source-visible search-result notes")
    parser.add_argument("--search-tab", choices=["全部", "图文", "视频"], default="全部")
    parser.add_argument("--search-filter", action="append", default=None, help="v0.3.0 supports 综合 only")
    parser.add_argument("--max-search-scroll-actions", type=int, default=80)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assets", default="images,cover")
    parser.add_argument("--comment-limit", type=int, default=0)
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--retain-author-display", action="store_true")
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = normalize_note_targets(args.note) if args.note else []
        assets = normalize_assets(args.assets)
        profile = args.profile_dir.expanduser().resolve()
        out = args.out.expanduser().resolve()
        if profile == out or profile in out.parents or out in profile.parents:
            raise CollectionError("The private Chrome profile and delivery directory must be separate")
        plan = {
            "mode": args.mode,
            "notes": [{"note_id": canonical_note_id(value), "canonical_url": canonical_note_url(value)} for value in targets],
            "profile": ({
                "profile_id": canonical_profile_id(args.profile),
                "canonical_url": canonical_profile_url(args.profile),
                "recent_non_pinned": max(0, args.recent),
                "pinned_policy": "all_currently_visible_pinned_additional",
            } if args.profile else None),
            "search": ({
                "keyword": args.search,
                "tab": args.search_tab,
                "filters": args.search_filter or ["综合"],
                "first_visible_results": max(1, args.search_limit),
            } if args.search else None),
            "navigation_context": "used_in_memory_only" if any("xsec_" in value for value in targets + ([args.profile] if args.profile else [])) else "canonical_url",
            "assets": assets,
            "comment_limit": max(0, args.comment_limit),
            "include_replies": bool(args.include_replies),
            "privacy_mode": "comment_display_authors_retained" if args.retain_author_display else "comment_authors_pseudonymized",
            "profile_dir": str(profile),
            "out": str(out),
            "resume": bool(args.resume),
            "dry_run": bool(args.dry_run),
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        result = collect(
            note_targets=targets,
            profile_target=args.profile,
            search_query=args.search,
            recent=max(0, args.recent),
            max_profile_scroll_actions=max(0, args.max_profile_scroll_actions),
            search_limit=max(1, args.search_limit),
            search_tab=args.search_tab,
            search_filters=args.search_filter or ["综合"],
            max_search_scroll_actions=max(0, args.max_search_scroll_actions),
            profile_dir=profile,
            out=out,
            mode=args.mode,
            assets=assets,
            comment_limit=max(0, args.comment_limit),
            max_scroll_actions=max(1, args.max_scroll_actions),
            include_replies=args.include_replies,
            retain_author_display=args.retain_author_display,
            login_wait=max(0, args.login_wait),
            resume=args.resume,
            chrome_path=args.chrome_path,
            max_asset_mb=max(1, args.max_asset_mb),
        )
        delivery = build_delivery(out)
        print(json.dumps({"collection": result, "delivery": delivery}, ensure_ascii=False, indent=2))
        return 0 if result.get("state") == "complete" else 3
    except (CollectionError, DeliveryError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
