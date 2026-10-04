"""Tiny in-process sliding-window rate limiter (single uvicorn process, so memory is enough)."""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict, deque

MAX_KEYS = 10_000
IPV6_PREFIX = 64  # one end-user site usually gets a whole /64 (or more) from its ISP


def rate_key(ip: str) -> str:
    """Bucket key for a client address: IPv4 as-is, IPv6 by its /64.

    Keying IPv6 by the full /128 let anyone holding a /64 (i.e. any home connection)
    rotate through 2^64 addresses, so the per-IP limit never fired and the shared
    global budgets could be drained. IPv4-mapped IPv6 (::ffff:a.b.c.d) is keyed as the
    IPv4 address. Anything unparseable is returned unchanged.
    """
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        # Mask with ints rather than IPv6Network so scoped addresses (fe80::1%eth0) can't raise.
        mask = ((1 << IPV6_PREFIX) - 1) << (128 - IPV6_PREFIX)
        return f"{ipaddress.IPv6Address(int(addr) & mask)}/{IPV6_PREFIX}"
    return str(addr)


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
