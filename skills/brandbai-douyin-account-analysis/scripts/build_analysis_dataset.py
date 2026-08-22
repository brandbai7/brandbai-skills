#!/usr/bin/env python3
"""Build the deterministic input dataset for BrandBAI Douyin account analysis."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from analysis_common import MAX_RECENT_NON_PINNED, inspect_input


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input", required=True, help="Douyin collection package directory")
    value.add_argument("--out", required=True, help="New account-analysis output directory")
    value.add_argument(
        "--max-recent",
        type=int,
        default=MAX_RECENT_NON_PINNED,
        help=f"Recent non-pinned works to include, maximum {MAX_RECENT_NON_PINNED}",
    )
    value.add_argument("--dry-run", action="store_true", help="Print the plan without writing files")
    return value


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.out).expanduser().resolve()
    if output_dir == input_dir:
        print(json.dumps({"status": "invalid", "error": "Output directory must differ from input"}))
        return 2
    if output_dir.exists():
        if not output_dir.is_dir():
            print(json.dumps({"status": "invalid", "error": "Output path exists and is not a directory"}))
            return 2
        if any(output_dir.iterdir()):
            print(json.dumps({"status": "invalid", "error": "Output directory already exists and is not empty"}))
            return 2

    report = inspect_input(input_dir, max_recent=args.max_recent)
    if report["status"] == "invalid":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    plan = {
        "capability": "prepare-account-analysis-dataset",
        "input_status": report["status"],
        "sample_rule": report["sample_rule"],
        "sample_counts": report["sample_counts"],
        "analysis_window": report["analysis_window"],
        "outputs": [
            "data/analysis_manifest.json",
            "data/works_sample.json",
            "data/comment_inventory.json",
        ],
        "semantic_analysis_included": False,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ready" else 3

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "ready_for_analysis" if report["status"] == "ready" else "partial_input",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_status": report["status"],
        "source_paths": report["source_paths"],
        "sample_rule": report["sample_rule"],
        "sample_counts": report["sample_counts"],
        "analysis_window": report["analysis_window"],
        "warnings": report["warnings"],
        "semantic_analysis_included": False,
        "product_matching_included": False,
    }
    works_payload = {
        "sample_rule": report["sample_rule"],
        "works": report["selected_works"],
    }
    write_json(data_dir / "analysis_manifest.json", manifest)
    write_json(data_dir / "works_sample.json", works_payload)
    write_json(data_dir / "comment_inventory.json", report["comment_inventory"])
    print(json.dumps({**plan, "delivery": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
