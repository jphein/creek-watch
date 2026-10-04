"""Tiny in-process sliding-window rate limiter (single uvicorn process, so memory is enough)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, count: int, window_s: float):
        self.count, self.window_s = count, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a hit; return None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.count:
                return max(1.0, self.window_s - (now - q[0]))
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory under abuse
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return None
