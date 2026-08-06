#!/usr/bin/env python3
"""Validate a Douyin collection package for account analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis_common import MAX_RECENT_NON_PINNED, inspect_input


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input", required=True, help="Douyin collection package directory")
    value.add_argument(
        "--max-recent",
        type=int,
        default=MAX_RECENT_NON_PINNED,
        help=f"Recent non-pinned works to include, maximum {MAX_RECENT_NON_PINNED}",
    )
    value.add_argument("--json-out", help="Optional validation report path")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = inspect_input(Path(args.input), max_recent=args.max_recent)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    if report["status"] == "invalid":
        return 2
    if report["status"] == "partial":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
