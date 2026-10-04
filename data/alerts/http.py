"""Tiny HTTP helper for alert sources: UA, timeout, conditional GET for big daily files.

Tests monkeypatch `get_text` (one seam for every adapter).
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

UA = "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"
_cond: dict[str, tuple[str | None, str | None, str]] = {}   # url -> (etag, last_modified, body)
_lock = threading.Lock()


def get_text(url: str, timeout: float = 20, conditional: bool = False, accept: str = "*/*") -> str:
    """GET url as text. With conditional=True, sends If-None-Match/If-Modified-Since and
    returns the cached body on 304 (used for the 10 MB daily sewage-spill file)."""
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
            body = r.read().decode("utf-8", "replace")
            if conditional:
                with _lock:
                    _cond[url] = (r.headers.get("ETag"), r.headers.get("Last-Modified"), body)
            return body
    except urllib.error.HTTPError as e:
        if e.code == 304 and conditional:
            with _lock:
                return _cond[url][2]
        raise


def get_json(url: str, timeout: float = 20, accept: str = "application/json"):
    return json.loads(get_text(url, timeout=timeout, accept=accept))
