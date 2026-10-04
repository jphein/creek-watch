"""Tiny in-process sliding-window rate limiter (single uvicorn process, so memory is enough)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

MAX_KEYS = 10_000


class RateLimiter:
    """`count` hits per key per `window_s`. The key table is LRU-bounded so rotating keys can't grow memory."""

    def __init__(self, count: int, window_s: float):
        self.count, self.window_s = count, window_s
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a hit; return None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
            self._hits.move_to_end(key)
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.count:
                return max(1.0, self.window_s - (now - q[0]))
            q.append(now)
            while len(self._hits) > MAX_KEYS:  # evict least-recently-seen keys
                self._hits.popitem(last=False)
            return None
