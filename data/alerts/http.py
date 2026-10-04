"""Tiny HTTP helper for alert sources: UA, bounded read, wall-clock deadline, conditional GET.

Tests monkeypatch `get_text` (one seam for every adapter).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

UA = "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"
JSON_MAX_BYTES = 5 * 1024 * 1024      # every JSON API we call answers in well under 1 MB
CHUNK = 64 * 1024
_cond: dict[str, tuple[str | None, str | None, str]] = {}   # url -> (etag, last_modified, body)
_lock = threading.Lock()


class ResponseTooLarge(IOError):
    pass


class DeadlineExceeded(TimeoutError):
    pass


def _read_bounded(r, max_bytes: int, deadline: float) -> bytes:
    """Read at most max_bytes, and give up once the wall-clock deadline passes (the socket
    timeout alone only bounds each read, so a slow-drip server could otherwise hold us forever)."""
    declared = r.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLarge(f"Content-Length {declared} > {max_bytes}")
    buf = bytearray()
    while True:
        if time.monotonic() > deadline:
            raise DeadlineExceeded(f"read exceeded deadline after {len(buf)} bytes")
        chunk = r.read(CHUNK)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > max_bytes:
            raise ResponseTooLarge(f"body > {max_bytes} bytes")


def get_text(url: str, timeout: float = 10, conditional: bool = False, accept: str = "*/*",
             max_bytes: int = JSON_MAX_BYTES, deadline_s: float | None = None) -> str:
    """GET url as text, at most max_bytes, within deadline_s wall-clock seconds (default 2x timeout).
    With conditional=True, sends If-None-Match/If-Modified-Since and returns the cached body on 304
    (used for the 10 MB daily sewage-spill file)."""
    deadline = time.monotonic() + (deadline_s if deadline_s is not None else 2 * timeout)
    headers = {"User-Agent": UA, "Accept": accept}
    if conditional:
        with _lock:
            prev = _cond.get(url)
        if prev:
            if prev[0]:
                headers["If-None-Match"] = prev[0]
            if prev[1]:
                headers["If-Modified-Since"] = prev[1]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = _read_bounded(r, max_bytes, deadline).decode("utf-8", "replace")
            if conditional:
                with _lock:
                    _cond[url] = (r.headers.get("ETag"), r.headers.get("Last-Modified"), body)
            return body
    except urllib.error.HTTPError as e:
        if e.code == 304 and conditional:
            with _lock:
                return _cond[url][2]
        raise


def get_json(url: str, timeout: float = 10, accept: str = "application/json",
             max_bytes: int = JSON_MAX_BYTES):
    return json.loads(get_text(url, timeout=timeout, accept=accept, max_bytes=max_bytes))
