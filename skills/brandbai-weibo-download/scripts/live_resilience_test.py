"""Low-frequency visible-Chrome resilience checks for BrandBAI Weibo collection."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from browser_collect_weibo import _page_blocker
from collector_core import CollectionError, atomic_write_json, canonical_post_url, utc_now
from project_runner import visible_chrome_session


SCHEMA_VERSION = "brandbai.weibo.live-resilience.v1"


def classify_page_health(*, blocker: str, article_visible: bool, current_url: str) -> str:
    if blocker == "login":
        return "partial_login_required"
    if blocker == "verification":
        return "partial_verification_required"
    if blocker:
        return "partial_page_blocked"
    if "weibo.com" not in current_url.lower():
        return "partial_navigation_unavailable"
    if not article_visible:
        return "partial_article_unavailable"
    return "complete_visible_page_healthy"


def soak_result_state(checkpoints: list[dict[str, Any]], *, elapsed_seconds: float,
                      requested_seconds: int) -> str:
    if elapsed_seconds + 0.5 < requested_seconds:
        return "partial_duration_not_reached"
    if checkpoints and all(str(row.get("state") or "").startswith("complete") for row in checkpoints):
        return "complete_soak_duration_healthy"
    return "partial_soak_health_anomaly"


def _page_health(page: Any) -> dict[str, Any]:
    blocker = _page_blocker(page)
    article_visible = False
    try:
        article = page.locator("main article").first
        article_visible = bool(article.count() and article.is_visible(timeout=500))
    except Exception:
        article_visible = False
    current_url = str(page.url or "")
    return {
        "checked_at": utc_now(),
        "state": classify_page_health(
            blocker=blocker, article_visible=article_visible, current_url=current_url,
        ),
        "blocker": blocker or "none",
        "article_visible": article_visible,
        "weibo_origin_visible": "weibo.com" in current_url.lower(),
    }


def _navigate(page: Any, target: str, *, attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3_000)
            return
        except Exception as exc:
            last_error = exc
            if attempt < max(1, attempts):
                page.wait_for_timeout(2_000)
    assert last_error is not None
    raise last_error


def _wait_for_manual_recovery(page: Any, *, seconds: int) -> dict[str, Any]:
    latest = _page_health(page)
    if latest["state"].startswith("complete") or seconds <= 0:
        return latest
    if latest["blocker"] not in {"login", "verification"}:
        return latest
    print(f"Complete the visible Weibo login or verification within {seconds} seconds.")
    for _ in range(seconds):
        page.wait_for_timeout(1_000)
        latest = _page_health(page)
        if latest["state"].startswith("complete"):
            break
    return latest


def run_network_recovery(*, target: str, profile_dir: Path, out: Path,
                         offline_seconds: int, login_wait: int,
                         chrome_path: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "controlled_browser_offline_recovery",
        "target_kind": "public_post",
        "offline_seconds": offline_seconds,
        "started_at": utc_now(),
        "before": {},
        "during": {},
        "after": {},
        "state": "running",
        "finished_at": "",
    }
    atomic_write_json(out, result)
    with visible_chrome_session(profile_dir=profile_dir, chrome_path=chrome_path) as (context, page):
        _navigate(page, target)
        result["before"] = _wait_for_manual_recovery(page, seconds=login_wait)
        offline_error_type = ""
        context.set_offline(True)
        try:
            try:
                page.reload(wait_until="domcontentloaded", timeout=10_000)
            except Exception as exc:
                offline_error_type = type(exc).__name__
            page.wait_for_timeout(max(1, offline_seconds) * 1_000)
            result["during"] = {
                "offline_mode_enabled": True,
                "reload_error_type": offline_error_type or "none",
            }
        finally:
            context.set_offline(False)
        recovery_started = time.monotonic()
        recovery_error_type = ""
        try:
            _navigate(page, target)
        except Exception as exc:
            recovery_error_type = type(exc).__name__
        result["after"] = _wait_for_manual_recovery(page, seconds=login_wait)
        result["after"]["recovery_seconds"] = round(time.monotonic() - recovery_started, 3)
        result["after"]["navigation_error_type"] = recovery_error_type or "none"

    before_ok = str(result["before"].get("state") or "").startswith("complete")
    after_ok = str(result["after"].get("state") or "").startswith("complete")
    result["state"] = (
        "complete_controlled_offline_recovery" if before_ok and after_ok
        else "partial_controlled_offline_recovery"
    )
    result["finished_at"] = utc_now()
    atomic_write_json(out, result)
    return result


def run_soak(*, target: str, profile_dir: Path, out: Path, duration_seconds: int,
             check_interval_seconds: int, reload_interval_seconds: int,
             login_wait: int, chrome_path: str | None = None) -> dict[str, Any]:
    duration_seconds = max(1, duration_seconds)
    check_interval_seconds = max(10, check_interval_seconds)
    reload_interval_seconds = max(0, reload_interval_seconds)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "visible_chrome_low_frequency_soak",
        "target_kind": "public_post",
        "requested_duration_seconds": duration_seconds,
        "check_interval_seconds": check_interval_seconds,
        "reload_interval_seconds": reload_interval_seconds,
        "started_at": utc_now(),
        "checkpoints": [],
        "reload_attempts": 0,
        "reload_failures": 0,
        "state": "running",
        "finished_at": "",
    }
    atomic_write_json(out, result)
    started = time.monotonic()
    try:
        with visible_chrome_session(profile_dir=profile_dir, chrome_path=chrome_path) as (_context, page):
            _navigate(page, target)
            next_reload = float(reload_interval_seconds) if reload_interval_seconds else float("inf")
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= next_reload:
                    result["reload_attempts"] += 1
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=45_000)
                        page.wait_for_timeout(3_000)
                    except Exception:
                        result["reload_failures"] += 1
                    next_reload += reload_interval_seconds
                checkpoint = _wait_for_manual_recovery(page, seconds=login_wait)
                checkpoint["elapsed_seconds"] = round(elapsed, 3)
                result["checkpoints"].append(checkpoint)
                result["elapsed_seconds"] = round(elapsed, 3)
                atomic_write_json(out, result)
                if elapsed >= duration_seconds:
                    break
                remaining = max(0.0, duration_seconds - elapsed)
                page.wait_for_timeout(int(min(check_interval_seconds, remaining) * 1_000))
    except Exception as exc:
        result["state"] = "failed_soak_runtime"
        result["error_type"] = type(exc).__name__
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["finished_at"] = utc_now()
        atomic_write_json(out, result)
        raise

    elapsed = time.monotonic() - started
    result["elapsed_seconds"] = round(elapsed, 3)
    result["healthy_checkpoints"] = sum(
        1 for row in result["checkpoints"] if str(row.get("state") or "").startswith("complete")
    )
    result["state"] = soak_result_state(
        result["checkpoints"], elapsed_seconds=elapsed, requested_seconds=duration_seconds,
    )
    result["finished_at"] = utc_now()
    atomic_write_json(out, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run low-frequency visible-Chrome Weibo resilience checks")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("network-recovery", "soak"):
        command = subparsers.add_parser(name)
        command.add_argument("--post", required=True)
        command.add_argument("--profile-dir", required=True, type=Path)
        command.add_argument("--out", required=True, type=Path)
        command.add_argument("--login-wait", type=int, default=0)
        command.add_argument("--chrome-path")
    subparsers.choices["network-recovery"].add_argument("--offline-seconds", type=int, default=8)
    soak = subparsers.choices["soak"]
    soak.add_argument("--duration-seconds", type=int, default=7_200)
    soak.add_argument("--check-interval-seconds", type=int, default=60)
    soak.add_argument("--reload-interval-seconds", type=int, default=1_800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = canonical_post_url(args.post)
    if args.operation == "network-recovery":
        result = run_network_recovery(
            target=target, profile_dir=args.profile_dir, out=args.out,
            offline_seconds=max(1, args.offline_seconds), login_wait=max(0, args.login_wait),
            chrome_path=args.chrome_path,
        )
    else:
        result = run_soak(
            target=target, profile_dir=args.profile_dir, out=args.out,
            duration_seconds=max(1, args.duration_seconds),
            check_interval_seconds=max(10, args.check_interval_seconds),
            reload_interval_seconds=max(0, args.reload_interval_seconds),
            login_wait=max(0, args.login_wait), chrome_path=args.chrome_path,
        )
    print(result)
    return 0 if str(result.get("state") or "").startswith("complete") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CollectionError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
