"""Explicit check/install entry point for the private recorder runtime."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from runtime_support import (
    RuntimeSetupError,
    activate_existing_streamget_runtime,
    ensure_streamget_runtime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the private StreamGet runtime.")
    parser.add_argument("action", choices=("check", "install"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        status = (
            activate_existing_streamget_runtime()
            if args.action == "check"
            else ensure_streamget_runtime(auto_install=True)
        )
        print(json.dumps(status.public_summary(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if status.ready else 2
    except RuntimeSetupError as exc:
        print(
            json.dumps(
                {
                    "ready": False,
                    "reason_code": exc.reason_code,
                    "message": str(exc),
                    "path_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
