"""Local synthetic load and recovery test for BrandBAI Weibo project delivery.

This script never opens Chrome or contacts Weibo. It exercises project planning,
task-state persistence, deduplication, workbook delivery, ZIP packaging, checksum
generation, and resumable recovery with synthetic records only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from collector_core import atomic_write_json
from package_delivery import package_directory, sha256_file
from project_delivery import finalize_project_delivery
from project_plan import build_project_dry_run
from project_runner import project_state_dir, run_project_tasks


PRESETS = {
    "quick": {"campaigns": 5, "comments": 500, "reposts": 250, "asset_mb": 8},
    "standard": {"campaigns": 25, "comments": 2000, "reposts": 1000, "asset_mb": 100},
    "full": {"campaigns": 50, "comments": 10000, "reposts": 5000, "asset_mb": 512},
}


class SyntheticSessionFactory:
    """Context manager matching the visible browser-session interface."""

    def __init__(self) -> None:
        self.opens = 0

    @contextmanager
    def __call__(self, **_: Any) -> Iterator[tuple[object, object]]:
        self.opens += 1
        yield object(), object()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _distributed_total(total: int, buckets: int, index: int) -> int:
    base, remainder = divmod(max(0, total), max(1, buckets))
    return base + (1 if index < remainder else 0)


def _synthetic_ids(index: int) -> tuple[str, str, str]:
    celebrity_uid = str(1100000000 + index * 2)
    brand_uid = str(1100000001 + index * 2)
    post_id = f"S{index:09d}"
    return celebrity_uid, brand_uid, post_id


def build_synthetic_plan(campaigns: int) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    if campaigns < 1 or campaigns > 100:
        raise ValueError("campaigns must be between 1 and 100")
    rows: list[dict[str, Any]] = []
    lookup: dict[str, dict[str, str]] = {}
    for index in range(campaigns):
        campaign_id = f"synthetic-{index + 1:03d}"
        celebrity_uid, brand_uid, post_id = _synthetic_ids(index)
        lookup[campaign_id] = {
            "celebrity_uid": celebrity_uid,
            "brand_uid": brand_uid,
            "post_id": post_id,
        }
        rows.append({
            "campaign_id": campaign_id,
            "campaign_name": f"合成项目{index + 1:03d}",
            "actors": [
                {"role": "celebrity", "profile_uid": celebrity_uid, "display_name": f"合成明星{index + 1:03d}"},
                {"role": "brand", "profile_uid": brand_uid, "display_name": f"合成品牌{index + 1:03d}"},
            ],
            "queries": [f"合成明星{index + 1:03d} 合成品牌{index + 1:03d}"],
            "seed_posts": [f"https://weibo.com/{celebrity_uid}/{post_id}"],
            "profile_recent_n": 5,
            "search_limit": 20,
        })
    return ({
        "schema_version": "brandbai.weibo.project.v1",
        "project_id": f"WB-STRESS-{campaigns:03d}",
        "project_name": "BrandBAI微博Skill合成本地压力测试",
        "preset": "celebrity_announcement",
        "capture_depth": "standard",
        "time_window": {"start": "2026-08-01", "end": "2026-08-14"},
        "campaigns": rows,
        "deep_capture": {
            "selection_rule": "seed_only",
            "max_deep_posts_per_campaign": 1,
            "comment_limit_per_post": 100000,
            "repost_limit_per_post": 100000,
            "expand_replies": True,
            "download_assets": True,
        },
    }, lookup)


def _deterministic_bytes(label: str, size: int) -> bytes:
    return hashlib.shake_256(label.encode("utf-8")).digest(max(0, size))


def build_synthetic_executor(
    *, lookup: dict[str, dict[str, str]], total_comments: int,
    total_reposts: int, total_asset_bytes: int,
):
    campaign_ids = sorted(lookup)
    campaign_index = {campaign_id: index for index, campaign_id in enumerate(campaign_ids)}
    campaigns = len(campaign_ids)

    def execute(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        task_out = Path(kwargs["task_out"])
        data = task_out / "data"
        data.mkdir(parents=True, exist_ok=True)
        campaign_id = str(task["campaign_id"])
        index = campaign_index[campaign_id]
        ids = lookup[campaign_id]
        post_id = ids["post_id"]
        post_url = f"https://weibo.com/{ids['celebrity_uid']}/{post_id}"
        source_type = str(task["source_type"])

        if source_type == "profile":
            uid = str(task["target_key"])
            _write_jsonl(data / "accounts.jsonl", [{
                "uid": uid,
                "display_name": f"合成账号{uid[-4:]}",
                "canonical_url": task["canonical_url"],
                "collected_at": "2026-08-14T00:00:00Z",
                "completion_state": "complete_visible_account",
            }])
            atomic_write_json(data / "profile_selection.json", {
                "profile_selection_id": f"selection-{campaign_id}-{uid}",
                "profile_id": uid,
                "captured_at": "2026-08-14T00:00:00Z",
                "state": "complete_visible_pinned_plus_recent_n",
                "selected": [{
                    "post_id": post_id,
                    "author_uid": ids["celebrity_uid"],
                    "author_name": f"合成明星{index + 1:03d}",
                    "rank": 1,
                    "is_pinned": uid == ids["celebrity_uid"],
                    "selection_reason": "pinned" if uid == ids["celebrity_uid"] else "recent_non_pinned",
                    "body_preview": "合成业务场景微博",
                    "published_at_text": "2026-08-14 10:00",
                    "canonical_url": post_url,
                }],
            })
            return {"state": "complete_visible_pinned_plus_recent_n", "saved_accounts": 1, "saved_visible_post_refs": 1}

        if source_type == "search":
            _write_jsonl(data / "search_snapshots.jsonl", [{
                "search_snapshot_id": f"search-{campaign_id}",
                "query_kind": "keyword",
                "query": task["target_key"],
                "sort": "综合",
                "filters": ["全部"],
                "captured_at": "2026-08-14T00:01:00Z",
                "state": "complete_first_n_visible_results",
                "results": [{
                    "rank": 1,
                    "post_id": post_id,
                    "author_uid": ids["celebrity_uid"],
                    "author_name": f"合成明星{index + 1:03d}",
                    "body_preview": "合成业务场景微博",
                    "canonical_url": post_url,
                }],
            }])
            return {"state": "complete_first_n_visible_results", "saved_visible_post_refs": 1}

        if source_type != "post":
            raise AssertionError(f"unexpected synthetic source type: {source_type}")

        _write_jsonl(data / "posts.jsonl", [{
            "post_id": post_id,
            "author_uid": ids["celebrity_uid"],
            "author_name": f"合成明星{index + 1:03d}",
            "body": f"合成业务场景微博正文 #{campaign_id}#",
            "topics": [f"#{campaign_id}#"],
            "mentions": [f"@合成品牌{index + 1:03d}"],
            "post_type": "image",
            "published_at_text": "2026-08-14 10:00",
            "metrics": {"reposts": "synthetic", "comments": "synthetic", "likes": "synthetic"},
            "canonical_url": post_url,
            "collected_at": "2026-08-14T00:02:00Z",
            "completion_state": "complete_visible_post",
            "completion_note": "合成本地压力测试记录",
        }])

        comment_count = _distributed_total(total_comments, campaigns, index)
        comments = [{
            "comment_id": f"comment-{index:03d}-{row:06d}",
            "comment_id_type": "synthetic",
            "post_id": post_id,
            "root_comment_id": f"comment-{index:03d}-{row:06d}",
            "level": 1,
            "author_id": f"wb_user_{index:03d}_{row:06d}",
            "content": f"合成评论{row:06d}",
            "declared_reply_count": 0,
            "saved_reply_count": 0,
            "reply_expansion_status": "not_applicable",
            "observed_sorts": ["time"],
            "collected_at": "2026-08-14T00:03:00Z",
        } for row in range(comment_count)]
        if comments:
            _write_jsonl(data / "comments.jsonl", comments)

        repost_count = _distributed_total(total_reposts, campaigns, index)
        reposts = [{
            "repost_id": f"repost-{index:03d}-{row:06d}",
            "repost_id_type": "synthetic",
            "source_post_id": post_id,
            "author_id": f"wb_reposter_{index:03d}_{row:06d}",
            "content": f"合成转发{row:06d}",
            "chain_status": "one_hop_visible",
            "collected_at": "2026-08-14T00:04:00Z",
        } for row in range(repost_count)]
        if reposts:
            _write_jsonl(data / "reposts.jsonl", reposts)

        asset_bytes = _distributed_total(total_asset_bytes, campaigns, index)
        if asset_bytes:
            local = Path("06_微博素材") / post_id / "001_image.bin"
            target = task_out / local
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_deterministic_bytes(f"{campaign_id}-asset", asset_bytes))
            _write_jsonl(data / "assets.jsonl", [{
                "asset_id": f"weibo:{post_id}:image:001",
                "post_id": post_id,
                "kind": "image",
                "order": 1,
                "requested": True,
                "status": "downloaded",
                "local_file": local.as_posix(),
                "source_url": f"https://example.invalid/{campaign_id}.bin",
                "bytes": asset_bytes,
                "sha256": sha256_file(target),
            }])

        return {
            "state": "complete_visible_synthetic",
            "post_id": post_id,
            "post_state": "complete_visible_post",
            "comment_state": "complete_visible_comments_exhausted" if comments else "not_requested",
            "repost_state": "complete_visible_reposts_exhausted" if reposts else "not_requested",
        }

    return execute


def _run_recovery_probe(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    out = root / "recovery_delivery"
    profile = root / "recovery_profile"
    dry_run = build_project_dry_run(
        plan, mode="all", profile_dir=profile, out=out,
        assets=[], resume=False, package_zip=False,
    )
    task_ids = [task["source_task_id"] for task in dry_run["source_tasks"]]
    transient_ids = set(task_ids[-2:])
    first_calls: list[str] = []

    def first_executor(task: dict[str, Any], **_: Any) -> dict[str, Any]:
        task_id = str(task["source_task_id"])
        first_calls.append(task_id)
        if task_id == task_ids[-1]:
            raise RuntimeError("synthetic transient network interruption")
        if task_id == task_ids[-2]:
            return {"state": "partial_selector_drift"}
        return {"state": "complete_visible_synthetic"}

    first = run_project_tasks(
        plan, profile_dir=profile, out=out, mode="all", assets=[], resume=False,
        task_executor=first_executor, session_factory=SyntheticSessionFactory(),
    )
    retry_calls: list[str] = []

    def retry_executor(task: dict[str, Any], **_: Any) -> dict[str, Any]:
        retry_calls.append(str(task["source_task_id"]))
        return {"state": "complete_visible_synthetic"}

    resumed = run_project_tasks(
        plan, profile_dir=profile, out=out, mode="all", assets=[], resume=True,
        task_executor=retry_executor, session_factory=SyntheticSessionFactory(),
    )
    passed = (
        first["state"] == "partial"
        and set(retry_calls) == transient_ids
        and resumed["state"] == "complete"
    )
    if not passed:
        raise AssertionError("synthetic recovery probe did not retry exactly the incomplete tasks")
    return {
        "passed": True,
        "initial_state": first["state"],
        "initial_task_counts": first["source_task_counts"],
        "retried_tasks": len(retry_calls),
        "final_state": resumed["state"],
    }


def run_stress(
    *, campaigns: int, comments: int, reposts: int,
    asset_mb: int, work_root: Path,
) -> dict[str, Any]:
    if min(comments, reposts, asset_mb) < 0:
        raise ValueError("comments, reposts and asset_mb must be non-negative")
    plan, lookup = build_synthetic_plan(campaigns)
    profile = work_root / "profile"
    out = work_root / "delivery"
    asset_bytes = asset_mb * 1024 * 1024
    executor = build_synthetic_executor(
        lookup=lookup,
        total_comments=comments,
        total_reposts=reposts,
        total_asset_bytes=asset_bytes,
    )
    phases: dict[str, float] = {}
    tracemalloc.start()
    started = time.perf_counter()

    mark = time.perf_counter()
    manifest = run_project_tasks(
        plan, profile_dir=profile, out=out, mode="all", assets=["images"], resume=False,
        task_executor=executor, session_factory=SyntheticSessionFactory(),
    )
    phases["task_run_seconds"] = round(time.perf_counter() - mark, 3)
    if manifest["state"] != "complete":
        raise AssertionError(f"synthetic project did not complete: {manifest['state']}")

    resume_executor_calls: list[str] = []
    mark = time.perf_counter()
    resumed = run_project_tasks(
        plan, profile_dir=profile, out=out, mode="all", assets=["images"], resume=True,
        task_executor=lambda task, **kwargs: resume_executor_calls.append(task["source_task_id"]) or {"state": "failed"},
        session_factory=SyntheticSessionFactory(),
    )
    phases["completed_resume_seconds"] = round(time.perf_counter() - mark, 3)
    if resumed["state"] != "complete" or resume_executor_calls:
        raise AssertionError("completed resume reran tasks unexpectedly")

    mark = time.perf_counter()
    finalization = finalize_project_delivery(out)
    phases["merge_and_delivery_seconds"] = round(time.perf_counter() - mark, 3)
    counts = finalization["merge"]["counts"]
    expected = {"posts": campaigns, "comments": comments, "reposts": reposts}
    for key, expected_count in expected.items():
        if int(counts.get(key) or 0) != expected_count:
            raise AssertionError(f"{key} mismatch: {counts.get(key)} != {expected_count}")

    mark = time.perf_counter()
    package = package_directory(out)
    phases["package_seconds"] = round(time.perf_counter() - mark, 3)
    if sha256_file(Path(package["zip"])) != package["sha256"]:
        raise AssertionError("package checksum mismatch")

    mark = time.perf_counter()
    recovery = _run_recovery_probe(plan, work_root)
    phases["recovery_probe_seconds"] = round(time.perf_counter() - mark, 3)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_seconds = round(time.perf_counter() - started, 3)

    state_dir = project_state_dir(out)
    return {
        "schema_version": "brandbai.weibo.local-stress-result.v1",
        "scope": "local_synthetic_only",
        "live_platform_access": False,
        "formal_stress_complete": False,
        "configuration": {
            "campaigns": campaigns,
            "source_tasks": manifest["source_task_total"],
            "comments": comments,
            "reposts": reposts,
            "synthetic_asset_mb": asset_mb,
        },
        "result": {
            "passed": True,
            "project_state": finalization["merge"]["project_manifest"]["state"],
            "counts": counts,
            "package_files": package["files"],
            "package_bytes": package["bytes"],
            "package_sha256": package["sha256"],
            "completed_resume_reran_tasks": len(resume_executor_calls),
            "recovery": recovery,
        },
        "performance": {
            **phases,
            "total_seconds": total_seconds,
            "python_tracemalloc_peak_mb": round(peak_bytes / (1024 * 1024), 2),
        },
        "boundaries": [
            "This result does not measure Weibo response time, platform rate limits, login expiry, or selector drift on a live page.",
            "Python tracemalloc does not include every native-library or browser allocation.",
            "A formal release claim still requires low-frequency real-page endurance and fault acceptance.",
        ],
        "work_output": str(out),
        "private_state": str(state_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local synthetic Weibo Skill load and recovery test")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="quick")
    parser.add_argument("--campaigns", type=int)
    parser.add_argument("--comments", type=int)
    parser.add_argument("--reposts", type=int)
    parser.add_argument("--asset-mb", type=int)
    parser.add_argument("--work-dir", type=Path, help="Keep generated synthetic delivery under this directory")
    parser.add_argument("--report", type=Path, help="Write the JSON result outside the temporary work directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = dict(PRESETS[args.preset])
    for name in ("campaigns", "comments", "reposts", "asset_mb"):
        value = getattr(args, name)
        if value is not None:
            settings[name] = value

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.work_dir:
        root = args.work_dir.expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise SystemExit("--work-dir must be empty or not yet exist")
        root.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="brandbai-weibo-stress-")
        root = Path(temporary.name)

    try:
        result = run_stress(work_root=root, **settings)
        result["work_output_retained"] = temporary is None
        if temporary is not None:
            result.pop("work_output", None)
            result.pop("private_state", None)
        if args.report:
            report = args.report.expanduser().resolve()
            report.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()
        elif root.exists():
            # A caller-selected directory is retained for manual inspection.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
