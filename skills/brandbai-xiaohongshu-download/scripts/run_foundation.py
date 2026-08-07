"""Unified single-note entry for BrandBAI Xiaohongshu collection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_collect_xiaohongshu import collect, normalize_assets
from build_delivery import DeliveryError, build_delivery
from collector_core import CollectionError, canonical_note_id, canonical_note_url, normalize_note_targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Xiaohongshu notes into a BrandBAI ordinary delivery")
    parser.add_argument("mode", choices=["note", "comments", "all"])
    parser.add_argument("--note", action="append", required=True, help="Repeat for more note URLs or note ids")
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
        targets = normalize_note_targets(args.note)
        assets = normalize_assets(args.assets)
        profile = args.profile_dir.expanduser().resolve()
        out = args.out.expanduser().resolve()
        if profile == out or profile in out.parents or out in profile.parents:
            raise CollectionError("The private Chrome profile and delivery directory must be separate")
        plan = {
            "mode": args.mode,
            "notes": [{"note_id": canonical_note_id(value), "canonical_url": canonical_note_url(value)} for value in targets],
            "navigation_context": "used_in_memory_only" if any("xsec_" in value for value in targets) else "canonical_url",
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
