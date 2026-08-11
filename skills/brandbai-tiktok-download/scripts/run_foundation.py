"""Unified TikTok work, profile or search entry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_collect_tiktok import collect, normalize_assets, search_url
from build_delivery import DeliveryError, build_delivery
from collector_core import (
    CollectionError, canonical_handle, canonical_profile_url, canonical_work_id,
    canonical_work_url, normalize_work_targets, work_type_from_url,
)
from package_delivery import PackageError, package_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect TikTok works into a BrandBAI ordinary delivery")
    parser.add_argument("mode", choices=["work", "comments", "all", "batch"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--work", action="append", help="Repeat for more TikTok video or photo URLs")
    source.add_argument("--profile", help="One TikTok creator profile URL or @handle")
    source.add_argument("--search", help="One TikTok search keyword")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned works; visible pinned works are additional")
    parser.add_argument("--search-limit", type=int, default=10)
    parser.add_argument("--search-tab", choices=["general", "video", "photo"], default="general")
    parser.add_argument("--search-filter", action="append", default=None)
    parser.add_argument("--business-preset", choices=[
        "market-scan", "influence-shortlist", "creative-benchmark", "campaign-reception",
        "shop-affiliate-evidence",
    ])
    parser.add_argument("--market-scope", help="Business-defined country or region; never inferred")
    parser.add_argument("--source-locale", help="Visible page locale or user-provided locale")
    parser.add_argument("--search-language", help="Language of the original search query")
    parser.add_argument("--observation-timezone", help="Timezone used for this observation, for example America/New_York")
    parser.add_argument("--downstream-use", choices=[
        "influence-intelligence", "content-diagnosis", "user-semantics", "product-fit",
        "campaign-review", "growth-planning",
    ])
    parser.add_argument("--max-list-scroll-actions", type=int, default=80)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assets", default="media,cover,audio")
    parser.add_argument("--comment-limit", type=int, default=0)
    parser.add_argument("--max-comment-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--retain-author-display", action="store_true")
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=300)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def build_plan(args: argparse.Namespace) -> dict[str, object]:
    targets = normalize_work_targets(args.work) if args.work else []
    if (args.profile or args.search) and args.mode != "batch":
        raise CollectionError("Profile and search collection require mode=batch")
    if targets and args.mode == "batch":
        raise CollectionError("mode=batch is for profile or search; use work/comments/all for explicit works")
    assets = normalize_assets(args.assets)
    profile_dir = args.profile_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if profile_dir == out or profile_dir in out.parents or out in profile_dir.parents:
        raise CollectionError("The private Chrome profile and delivery directory must be separate")
    business_context = {
        "business_preset": args.business_preset or "",
        "market_scope": args.market_scope or "",
        "source_surface": "public_tiktok",
        "source_locale": args.source_locale or "",
        "search_query_original": args.search or "",
        "search_language": args.search_language or "",
        "observation_timezone": args.observation_timezone or "",
        "authorization_mode": "public_visible",
        "downstream_use": args.downstream_use or "",
    }
    return {
        "platform": "tiktok", "mode": args.mode,
        "works": [{"work_id": canonical_work_id(value), "work_type": work_type_from_url(value),
                   "canonical_url": canonical_work_url(value)} for value in targets],
        "profile": ({"handle": canonical_handle(args.profile), "canonical_url": canonical_profile_url(args.profile),
                     "recent_non_pinned": max(0, args.recent), "pinned_policy": "all_currently_visible_additional"}
                    if args.profile else None),
        "search": ({"keyword": args.search, "tab": args.search_tab,
                    "filters": args.search_filter or ["relevance"], "url": search_url(args.search, args.search_tab),
                    "first_visible_results": max(1, args.search_limit)} if args.search else None),
        "assets": assets, "comment_limit": max(0, args.comment_limit),
        "include_replies": bool(args.include_replies),
        "privacy_mode": "comment_display_authors_retained" if args.retain_author_display else "comment_authors_pseudonymized",
        "profile_dir": str(profile_dir), "out": str(out), "resume": bool(args.resume),
        "zip": bool(args.zip), "dry_run": bool(args.dry_run),
        "business_context": business_context,
        "paid_features": {"speech_to_text": "disabled_coming_soon", "translation": "disabled_coming_soon"},
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(args)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        result = collect(
            work_targets=list(args.work or []), profile_target=args.profile, search_query=args.search,
            recent=max(0, args.recent), search_limit=max(1, args.search_limit), search_tab=args.search_tab,
            search_filters=args.search_filter or ["relevance"], max_list_scroll_actions=max(0, args.max_list_scroll_actions),
            profile_dir=Path(plan["profile_dir"]), out=Path(plan["out"]), mode=args.mode,
            assets=list(plan["assets"]), comment_limit=max(0, args.comment_limit),
            max_comment_scroll_actions=max(1, args.max_comment_scroll_actions), include_replies=args.include_replies,
            retain_author_display=args.retain_author_display, login_wait=max(0, args.login_wait), resume=args.resume,
            chrome_path=args.chrome_path, max_asset_mb=max(1, args.max_asset_mb),
            business_context=dict(plan["business_context"]),
        )
        delivery = build_delivery(Path(plan["out"]))
        package = package_directory(Path(plan["out"])) if args.zip else None
        print(json.dumps({"collection": result, "delivery": delivery, "package": package}, ensure_ascii=False, indent=2))
        return 0 if result.get("state") == "complete" else 3
    except (CollectionError, DeliveryError, PackageError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
