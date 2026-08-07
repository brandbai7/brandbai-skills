"""Unified BrandBAI Tmall collection entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_collect_tmall import collect, normalize_assets
from build_delivery import DeliveryError, build_delivery
from collector_core import CollectionError, canonical_item_url, extract_item_id, normalize_item_targets
from package_delivery import PackageError, package_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Tmall product evidence into a BrandBAI ordinary delivery")
    parser.add_argument("mode", choices=["product", "reviews", "all"])
    parser.add_argument("--item", action="append", required=True, help="Repeat for more products")
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assets", default="main_images,detail_images")
    parser.add_argument("--review-limit", type=int, default=0)
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--retain-masked-author", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        urls = normalize_item_targets(args.item)
        assets = normalize_assets(args.assets)
        profile = args.profile_dir.expanduser().resolve()
        out = args.out.expanduser().resolve()
        if profile == out or profile in out.parents or out in profile.parents:
            raise CollectionError("The private Chrome profile and delivery directory must be separate")
        plan = {
            "mode": args.mode,
            "items": [{
                "item_id": extract_item_id(url),
                "canonical_url": canonical_item_url(url),
                "navigation_url": url,
            } for url in urls],
            "assets": assets,
            "review_limit": max(0, args.review_limit),
            "privacy_mode": "masked_author_retained" if args.retain_masked_author else "pseudonymized",
            "profile_dir": str(profile),
            "out": str(out),
            "zip": args.zip,
            "resume": args.resume,
            "dry_run": args.dry_run,
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        result = collect(
            item_urls=urls,
            profile_dir=profile,
            out=out,
            mode=args.mode,
            assets=assets,
            review_limit=max(0, args.review_limit),
            max_scroll_actions=max(1, args.max_scroll_actions),
            login_wait=max(0, args.login_wait),
            retain_masked_author=args.retain_masked_author,
            resume=args.resume,
            chrome_path=args.chrome_path,
            max_asset_mb=max(1, args.max_asset_mb),
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
