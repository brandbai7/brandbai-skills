"""Unified Weibo collection and ordinary-delivery entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_collect_weibo import collect, normalize_assets
from build_delivery import DeliveryError, build_delivery
from collector_core import (
    CollectionError,
    canonical_hotlist_url,
    canonical_post_id,
    canonical_post_url,
    canonical_profile_id,
    canonical_profile_url,
    canonical_supertopic_id,
    canonical_supertopic_url,
    normalize_hotlist_category,
    normalize_post_targets,
    normalize_supertopic_tab,
    normalize_topic_query,
)
from package_delivery import PackageError, package_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Weibo evidence into a BrandBAI ordinary delivery")
    parser.add_argument("mode", choices=["posts", "comments", "reposts", "all"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--post", action="append", help="Repeat for more Weibo post URLs or ids")
    source.add_argument("--profile", help="One Weibo account URL or UID")
    source.add_argument("--search", help="One Weibo keyword query")
    source.add_argument("--topic", help="One Weibo hashtag topic")
    source.add_argument("--supertopic", help="One Weibo supertopic /p/100808... URL or ID")
    source.add_argument("--hotlist", help="One Weibo hotlist category, such as 热搜 or 文娱")
    parser.add_argument("--supertopic-tab", default="热门", help="Visible supertopic tab, such as 热门, 最新 or 精华")
    parser.add_argument("--hotlist-limit", type=int, default=50, help="Ranked rows to retain; pinned and special visible rows are additional")
    parser.add_argument("--recent", type=int, default=5)
    parser.add_argument("--max-profile-scroll-actions", type=int, default=80)
    parser.add_argument("--search-limit", type=int, default=10)
    parser.add_argument("--max-search-scroll-actions", type=int, default=80)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assets", default="images,cover")
    parser.add_argument("--comment-limit", type=int, default=0)
    parser.add_argument("--repost-limit", type=int, default=0)
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--retain-author-display", action="store_true")
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = normalize_post_targets(args.post) if args.post else []
        assets = normalize_assets(args.assets)
        profile = args.profile_dir.expanduser().resolve()
        out = args.out.expanduser().resolve()
        if profile == out or profile in out.parents or out in profile.parents:
            raise CollectionError("The private Chrome profile and delivery directory must be separate")
        topic = normalize_topic_query(args.topic) if args.topic else None
        supertopic_tab = normalize_supertopic_tab(args.supertopic_tab)
        hotlist = normalize_hotlist_category(args.hotlist) if args.hotlist else None
        if hotlist and args.mode != "posts":
            raise CollectionError("Hotlist snapshot collection currently supports mode=posts only")
        plan = {
            "mode": args.mode,
            "posts": [{"post_id": canonical_post_id(value), "canonical_url": canonical_post_url(value)} for value in targets],
            "profile": ({
                "profile_id": canonical_profile_id(args.profile), "canonical_url": canonical_profile_url(args.profile),
                "recent_non_pinned": max(0, args.recent), "pinned_policy": "all_currently_visible_pinned_additional",
            } if args.profile else None),
            "search": ({"query": args.search, "query_kind": "keyword", "first_visible_results": max(1, args.search_limit)} if args.search else None),
            "topic": ({"query": topic, "query_kind": "topic", "first_visible_results": max(1, args.search_limit)} if topic else None),
            "supertopic": ({
                "supertopic_id": canonical_supertopic_id(args.supertopic),
                "canonical_url": canonical_supertopic_url(args.supertopic),
                "selected_tab": supertopic_tab,
                "first_visible_results": max(1, args.search_limit),
            } if args.supertopic else None),
            "hotlist": ({
                "category_code": hotlist[0],
                "category_name": hotlist[1],
                "canonical_url": canonical_hotlist_url(hotlist[0]),
                "ranked_limit": max(1, args.hotlist_limit),
                "visible_pinned_and_special_rows": "additional",
            } if hotlist else None),
            "assets": assets, "comment_limit": max(0, args.comment_limit), "repost_limit": max(0, args.repost_limit),
            "include_replies": bool(args.include_replies),
            "privacy_mode": "interaction_display_authors_retained" if args.retain_author_display else "interaction_authors_pseudonymized",
            "profile_dir": str(profile), "out": str(out), "resume": bool(args.resume), "zip": bool(args.zip), "dry_run": bool(args.dry_run),
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        result = collect(
            post_targets=targets, profile_target=args.profile, search_query=args.search, topic_query=topic,
            supertopic_target=args.supertopic, supertopic_tab=supertopic_tab,
            hotlist_category=args.hotlist, hotlist_limit=max(1, args.hotlist_limit),
            recent=max(0, args.recent), max_profile_scroll_actions=max(0, args.max_profile_scroll_actions),
            search_limit=max(1, args.search_limit), max_search_scroll_actions=max(0, args.max_search_scroll_actions),
            profile_dir=profile, out=out, mode=args.mode, assets=assets,
            comment_limit=max(0, args.comment_limit), repost_limit=max(0, args.repost_limit),
            max_scroll_actions=max(1, args.max_scroll_actions), include_replies=args.include_replies,
            retain_author_display=args.retain_author_display, login_wait=max(0, args.login_wait),
            resume=args.resume, chrome_path=args.chrome_path, max_asset_mb=max(1, args.max_asset_mb),
        )
        delivery = build_delivery(out)
        package = package_directory(out) if args.zip else None
        print(json.dumps({"collection": result, "delivery": delivery, "package": package}, ensure_ascii=False, indent=2))
        return 0 if result.get("state") == "complete" else 3
    except (CollectionError, DeliveryError, PackageError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
