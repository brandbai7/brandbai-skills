"""Bounded media-progress monitoring. Never stores source URLs or stderr."""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, TextIO


class MediaProgress:
    def __init__(self, stream: TextIO | None, *, clock: Callable[[], float] = time.monotonic):
        self.stream = stream
        self.clock = clock
        self.started = self.last_advance = clock()
        self.seconds = 0.0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def accept(self, line: str) -> None:
        key, separator, value = line.strip().partition('=')
        if not separator or key != 'out_time_us':
            return
        try:
            seconds = float(value) / 1_000_000
        except ValueError:
            return
        if not math.isfinite(seconds) or seconds < 0:
            return
        with self.lock:
            if seconds > self.seconds:
                self.seconds = seconds
                self.last_advance = self.clock()

    def _drain(self) -> None:
        if self.stream is not None:
            for line in self.stream:
                self.accept(line)

    def snapshot(self, *, startup_timeout: float = 45, stall_timeout: float = 30) -> dict:
        with self.lock:
            age = max(0, self.clock() - self.last_advance)
            stalled = age >= (startup_timeout if self.seconds <= 0 else stall_timeout)
            return {'state': 'stalled' if stalled else 'receiving' if self.seconds > 0 else 'connecting',
                    'media_seconds': round(self.seconds, 3), 'no_progress_seconds': round(age, 1)}

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.thread.join(timeout=2)
