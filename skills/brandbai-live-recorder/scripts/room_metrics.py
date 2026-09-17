"""Low-frequency, browser-free Douyin room metric snapshots.

Only a small allowlist of public room-level values is persisted. Raw room
responses, stream URLs, cookies, signatures, owner objects, and user data are
never written by this module.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


MIN_POLL_INTERVAL_SECONDS = 10
MAX_POLL_INTERVAL_SECONDS = 300
DEFAULT_POLL_INTERVAL_SECONDS = 15


def _safe_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _safe_short_text(value: Any, *, limit: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or len(text) > limit or "http://" in text.lower() or "https://" in text.lower():
        return None
    return text


def extract_safe_room_metrics(page_data: dict[str, Any]) -> dict[str, Any]:
    """Extract only non-sensitive room-level metrics from StreamGet data."""

    if not isinstance(page_data, dict):
        return {}
    view_stats = page_data.get("room_view_stats")
    if not isinstance(view_stats, dict):
        view_stats = {}
    stats = page_data.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    room_cart = page_data.get("room_cart")
    if not isinstance(room_cart, dict):
        room_cart = {}

    online_viewers = _safe_nonnegative_int(view_stats.get("display_value"))
    online_display = _safe_short_text(
        page_data.get("user_count_str")
        or view_stats.get("display_short")
        or stats.get("user_count_str")
    )
    likes_count = _safe_nonnegative_int(page_data.get("like_count"))
    if likes_count is None:
        likes_count = _safe_nonnegative_int(stats.get("like_count"))
    cart_total = _safe_nonnegative_int(room_cart.get("total"))

    has_commerce_raw = page_data.get("has_commerce_goods")
    has_commerce_goods = has_commerce_raw if isinstance(has_commerce_raw, bool) else None
    cart_visible_raw = room_cart.get("show_cart")
    cart_visible = cart_visible_raw if isinstance(cart_visible_raw, bool) else None

    return {
        "online_viewers": online_viewers,
        "online_viewers_display": online_display,
        "likes_count": likes_count,
        "has_commerce_goods": has_commerce_goods,
        "cart_visible": cart_visible,
        "cart_total": cart_total,
        "observation_kind": "streamget_room_poll",
        "product_popup_boundary": "room_commerce_state_only_not_active_product_popup",
    }


def fetch_room_page_sync(room_url: str) -> dict[str, Any]:
    """Fetch one room snapshot through StreamGet's public resolver interface."""

    try:
        from streamget import DouyinLiveStream  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("streamget_unavailable") from exc
    return asyncio.run(DouyinLiveStream().fetch_web_stream_data(room_url))


class RoomMetricsCollector:
    """Append safe room snapshots while a recording process is active."""

    def __init__(
        self,
        *,
        room_url: str,
        output_path: Path,
        recording_started_epoch_ms: int,
        interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        fetcher: Callable[[str], dict[str, Any]] = fetch_room_page_sync,
    ) -> None:
        if not MIN_POLL_INTERVAL_SECONDS <= interval_seconds <= MAX_POLL_INTERVAL_SECONDS:
            raise ValueError("room metric interval must be between 10 and 300 seconds")
        self.room_url = room_url
        self.output_path = output_path
        self.recording_started_epoch_ms = recording_started_epoch_ms
        self.interval_seconds = interval_seconds
        self.fetcher = fetcher
        self.collector_session_id = f"room-metrics-{uuid.uuid4().hex[:12]}"
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"brandbai-{self.collector_session_id}",
            daemon=True,
        )
        self.sample_count = 0
        self.failure_count = 0
        self._sequence = 0

    @staticmethod
    def _iso_from_epoch_ms(epoch_ms: int) -> str:
        return datetime.fromtimestamp(epoch_ms / 1000).astimezone().isoformat(timespec="milliseconds")

    def _append(self, event_type: str, payload: dict[str, Any]) -> None:
        observed_at_epoch_ms = int(time.time() * 1000)
        self._sequence += 1
        event = {
            "collector_session_id": self.collector_session_id,
            "sequence": self._sequence,
            "event_type": event_type,
            "observed_at_epoch_ms": observed_at_epoch_ms,
            "observed_at": self._iso_from_epoch_ms(observed_at_epoch_ms),
            "recording_offset_seconds": round(
                (observed_at_epoch_ms - self.recording_started_epoch_ms) / 1000,
                3,
            ),
            "within_recording_window": observed_at_epoch_ms >= self.recording_started_epoch_ms,
            "time_alignment_status": "wall_clock_approximate_uncalibrated",
            "room_url": self.room_url,
            "payload": payload,
            "completeness": "observed_snapshot",
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def _run(self) -> None:
        self._append(
            "collector_status",
            {
                "status": "started",
                "collector_source": "streamget_room_poll",
                "interval_seconds": self.interval_seconds,
            },
        )
        while not self._stop_event.is_set():
            try:
                page_data = self.fetcher(self.room_url)
                metrics = extract_safe_room_metrics(page_data)
                self._append("room_snapshot", metrics)
                self.sample_count += 1
            except Exception:
                self.failure_count += 1
                self._append(
                    "collector_status",
                    {
                        "status": "fetch_failed",
                        "collector_source": "streamget_room_poll",
                        "reason": "room_snapshot_unavailable",
                    },
                )
            if self._stop_event.wait(self.interval_seconds):
                break
        self._append(
            "collector_status",
            {
                "status": "stopped",
                "collector_source": "streamget_room_poll",
                "sample_count": self.sample_count,
                "failure_count": self.failure_count,
            },
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)

