#!/usr/bin/env python3
"""Build verified classified-median baselines for a Douyin account analysis."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


REQUIRED_FIELDS = {
    "video_id",
    "content_task",
    "content_type",
    "commercial_status",
    "account_window",
    "comparison_group",
    "classification_status",
    "excluded_reason",
}
COMMERCIAL_STATUS = {"natural", "commercial", "activity", "live_preview", "unknown"}
CLASSIFICATION_STATUS = {"included", "excluded"}
METRIC_FIELDS = ("digg_count", "comment_count", "collect_count", "share_count")


class BaselineError(RuntimeError):
    """Raised when the baseline source contract is incomplete or inconsistent."""


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--delivery", required=True, help="Prepared account-analysis directory")
    value.add_argument("--dry-run", action="store_true", help="Validate and print the plan only")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"Cannot read JSON: {path.name}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise BaselineError(f"Cannot read JSONL: {path.name}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BaselineError(
                f"{path.name} line {line_number} is invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise BaselineError(f"{path.name} line {line_number} must be an object")
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            raise BaselineError(
                f"{path.name} line {line_number} is missing fields: {', '.join(missing)}"
            )
        rows.append(row)
    return rows


def integer(value: Any) -> int:
    try:
        return max(0, int(float(str(value or 0).replace(",", "").strip())))
    except (TypeError, ValueError):
        return 0


def clean_median(values: list[int]) -> int | float:
    value = median(values)
    return int(value) if float(value).is_integer() else float(value)


def build_rows(works: list[dict[str, Any]], classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recent = {
        str(row.get("video_id") or row.get("aweme_id") or "").strip(): row
        for row in works
        if isinstance(row, dict) and row.get("sample_role") == "recent_non_pinned"
    }
    recent.pop("", None)
    if not recent:
        raise BaselineError("No recent non-pinned works are available for a baseline")

    classification_ids = [str(row.get("video_id") or "").strip() for row in classifications]
    empty_rows = [index for index, value in enumerate(classification_ids, 1) if not value]
    if empty_rows:
        raise BaselineError(f"Classification rows have empty video_id: {empty_rows}")
    duplicates = sorted(value for value, count in Counter(classification_ids).items() if count > 1)
    if duplicates:
        raise BaselineError(f"Duplicate classification video_id: {', '.join(duplicates)}")
    unknown = sorted(set(classification_ids) - set(recent))
    missing = sorted(set(recent) - set(classification_ids))
    if unknown:
        raise BaselineError(f"Classifications reference non-baseline works: {', '.join(unknown)}")
    if missing:
        raise BaselineError(f"Recent non-pinned works are not classified: {', '.join(missing)}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(classifications, 1):
        commercial_status = row.get("commercial_status")
        classification_status = row.get("classification_status")
        if commercial_status not in COMMERCIAL_STATUS:
            raise BaselineError(
                f"Classification row {index} has invalid commercial_status: {commercial_status!r}"
            )
        if classification_status not in CLASSIFICATION_STATUS:
            raise BaselineError(
                f"Classification row {index} has invalid classification_status: {classification_status!r}"
            )
        if classification_status == "excluded":
            if not str(row.get("excluded_reason") or "").strip():
                raise BaselineError(f"Excluded classification row {index} needs excluded_reason")
            continue
        for field in ("content_task", "content_type", "account_window", "comparison_group"):
            if not str(row.get(field) or "").strip():
                raise BaselineError(f"Included classification row {index} has empty {field}")
        grouped[str(row["comparison_group"]).strip()].append(row)

    if not grouped:
        raise BaselineError("No included comparison group remains after classification")

    output: list[dict[str, Any]] = []
    for baseline_index, group_name in enumerate(sorted(grouped), 1):
        rows = grouped[group_name]
        identity_fields = ("content_task", "content_type", "commercial_status", "account_window")
        identity: dict[str, str] = {}
        for field in identity_fields:
            values = {str(row.get(field) or "").strip() for row in rows}
            if len(values) != 1:
                raise BaselineError(
                    f"Comparison group {group_name!r} mixes multiple {field} values"
                )
            identity[field] = values.pop()
        video_ids = [str(row["video_id"]) for row in rows]
        metrics = {
            f"{field.removesuffix('_count')}_median": clean_median(
                [integer(recent[video_id].get(field)) for video_id in video_ids]
            )
            for field in METRIC_FIELDS
        }
        output.append({
            "baseline_id": f"BSL-{baseline_index:03d}",
            "comparison_group": group_name,
            **identity,
            "video_ids": video_ids,
            "sample_size": len(video_ids),
            "comparable_status": "comparable" if len(video_ids) >= 2 else "conditional",
            **metrics,
            "boundary": "只描述本轮近期非置顶同组作品的可见中位数；不等于播放效率、自然流量或因果效果。",
        })
    return output


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.delivery).expanduser().resolve()
    works_path = root / "data" / "works_sample.json"
    classifications_path = root / "data" / "work_classification.jsonl"
    target = root / "data" / "baseline_ledger.jsonl"
    if not works_path.is_file() or not classifications_path.is_file():
        print(json.dumps({
            "status": "invalid",
            "error": "Run dataset preparation and delivery initialization first",
        }, ensure_ascii=False))
        return 2
    try:
        payload = read_json(works_path)
        works = payload.get("works") if isinstance(payload, dict) else None
        if not isinstance(works, list):
            raise BaselineError("works_sample.json must contain a works array")
        rows = build_rows(works, read_jsonl(classifications_path))
    except BaselineError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    plan = {
        "status": "ready_to_build",
        "classification_rows": sum(1 for _ in classifications_path.read_text(encoding="utf-8-sig").splitlines() if _.strip()),
        "baseline_groups": len(rows),
        "output": "data/baseline_ledger.jsonl",
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({**plan, "status": "built"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
