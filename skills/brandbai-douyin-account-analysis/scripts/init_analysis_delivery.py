#!/usr/bin/env python3
"""Initialize the ordinary delivery templates after dataset preparation."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ASSET_TO_OUTPUT = {
    "01_账号深度分析模板.md": "01_账号深度分析.md",
    "02_D1评论语义证据包模板.xlsx": "02_D1评论语义证据包.xlsx",
    "03_分析说明与资料缺口模板.md": "03_分析说明与资料缺口.md",
}
INTERNAL_FILES = (
    "data/video_analysis.jsonl",
    "data/evidence_ledger.jsonl",
    "data/claim_cards.jsonl",
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--out", required=True, help="Existing analysis output directory")
    value.add_argument("--dry-run", action="store_true", help="Print the plan without writing files")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output_dir = Path(args.out).expanduser().resolve()
    prepared_manifest = output_dir / "data" / "analysis_manifest.json"
    if not prepared_manifest.is_file():
        print(json.dumps({
            "status": "invalid",
            "error": "Run build_analysis_dataset.py first; data/analysis_manifest.json is missing",
        }, ensure_ascii=False))
        return 2

    skill_dir = Path(__file__).resolve().parent.parent
    assets_dir = skill_dir / "assets"
    targets = [output_dir / name for name in ASSET_TO_OUTPUT.values()]
    targets.extend(output_dir / name for name in INTERNAL_FILES)
    targets.append(output_dir / "data" / "delivery_manifest.json")
    existing = [str(path.relative_to(output_dir)) for path in targets if path.exists()]
    if existing:
        print(json.dumps({
            "status": "invalid",
            "error": "Delivery files already exist; use a new output directory instead of overwriting",
            "existing": existing,
        }, ensure_ascii=False, indent=2))
        return 2

    missing_assets = [name for name in ASSET_TO_OUTPUT if not (assets_dir / name).is_file()]
    if missing_assets:
        print(json.dumps({
            "status": "invalid",
            "error": "Required delivery asset is missing",
            "missing_assets": missing_assets,
        }, ensure_ascii=False, indent=2))
        return 2

    plan = {
        "status": "ready_to_initialize",
        "output": str(output_dir),
        "ordinary_files": list(ASSET_TO_OUTPUT.values()),
        "internal_files": [*INTERNAL_FILES, "data/delivery_manifest.json"],
        "templates_are_final": False,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    for asset_name, output_name in ASSET_TO_OUTPUT.items():
        shutil.copyfile(assets_dir / asset_name, output_dir / output_name)
    data_dir = output_dir / "data"
    for relative in INTERNAL_FILES:
        (output_dir / relative).touch(exist_ok=False)
    delivery_manifest = {
        "schema_version": "1.0",
        "analysis_status": "draft",
        "analysis_mode": "lightweight_no_asr",
        "account_name": "",
        "analysis_time": "",
        "deep_review_video_ids": [],
        "limitations": [],
    }
    (data_dir / "delivery_manifest.json").write_text(
        json.dumps(delivery_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**plan, "status": "initialized"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
