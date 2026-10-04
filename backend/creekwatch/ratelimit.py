"""Tiny in-process sliding-window rate limiter (single uvicorn process, so memory is enough)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

MAX_KEYS = 10_000


class RateLimiter:
    """Per-key limit plus a global limit, so rotating IPs can't fill the disk or the key table."""

    def __init__(self, count: int, window_s: float, global_count: int | None = None):
        self.count, self.window_s = count, window_s
        self.global_count = global_count
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()  # LRU by last hit
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window_s:
            q.popleft()

    def check(self, key: str) -> float | None:
        """Record a hit; return None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            self._trim(self._global, now)
            if self.global_count is not None and len(self._global) >= self.global_count:
                return max(1.0, self.window_s - (now - self._global[0]))
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
            self._hits.move_to_end(key)
            self._trim(q, now)
            if len(q) >= self.count:
                return max(1.0, self.window_s - (now - q[0]))
            q.append(now)
            self._global.append(now)
            # Bound memory: evict least-recently-seen keys (their windows are the oldest).
            while len(self._hits) > MAX_KEYS:
                self._hits.popitem(last=False)
            return None
