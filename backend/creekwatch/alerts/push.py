"""Web Push (RFC 8030 + VAPID RFC 8292) for alerts: subscriptions, filters, hardened outbound sends.

Threat model (Oracle gate): a subscription endpoint is an attacker-chosen URL we will POST to, so
- SSRF: endpoint must be https, port 443, no userinfo, hostname on an allowlist of real push services
  (no IP literals), re-checked at send time; redirects are never followed; env proxies ignored.
- DoS: total subscriptions capped; per-send timeouts; response bodies read with a size cap; payload
  capped; fan-out bounded by a worker pool and an overall deadline.
- Secrets: the VAPID private key comes only from env (CREEKWATCH_VAPID_PRIVATE), never disk/logs.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import SEVERITY_RANK

log = logging.getLogger("creekwatch.push")

PUSH_HOSTS_EXACT = {"fcm.googleapis.com", "updates.push.services.mozilla.com"}
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")
MAX_ENDPOINT_LEN = 1024
MAX_PAYLOAD = 3000          # bytes before encryption (push services cap ~4 KB)
SEND_TIMEOUT = (3.05, 10)   # connect, read
MAX_RESPONSE = 64 * 1024
FANOUT_WORKERS = 8
FANOUT_DEADLINE_S = 120
MAX_FAILURES = 5            # consecutive non-404/410 failures before a subscription is dropped

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint      TEXT PRIMARY KEY,
    p256dh        TEXT NOT NULL,
    auth          TEXT NOT NULL,
    creek_ids     TEXT NOT NULL DEFAULT '[]',
    min_severity  TEXT NOT NULL DEFAULT 'watch',
    quiet_start   TEXT,
    quiet_end     TEXT,
    tz            TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    created       TEXT NOT NULL,
    updated       TEXT NOT NULL,
    failures      INTEGER NOT NULL DEFAULT 0,
    last_ok       TEXT
);
"""


class SubscriptionInvalid(ValueError):
    pass


def _b64url_decode(s: str) -> bytes:
    if not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_\-]+={0,2}", s or ""):
        raise SubscriptionInvalid("keys must be base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def push_host_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host in PUSH_HOSTS_EXACT or any(host.endswith(sfx) and len(host) > len(sfx) for sfx in PUSH_HOST_SUFFIXES)


def validate_endpoint(endpoint: Any) -> str:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_LEN:
        raise SubscriptionInvalid("endpoint missing or too long")
    if any(ch.isspace() or ord(ch) < 0x21 for ch in endpoint):
        raise SubscriptionInvalid("endpoint contains whitespace/control characters")
    try:
        u = urlsplit(endpoint)
        port = u.port
    except ValueError:
        raise SubscriptionInvalid("endpoint is not a valid URL")
    if u.scheme != "https":
        raise SubscriptionInvalid("endpoint must be https")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise SubscriptionInvalid("endpoint must not contain credentials")
    if port not in (None, 443):
        raise SubscriptionInvalid("endpoint must use the default https port")
    if not push_host_allowed(u.hostname or ""):
        raise SubscriptionInvalid("endpoint is not a recognised push service (FCM, Mozilla, Apple, Windows)")
    return endpoint


def _hhmm(v: Any) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise SubscriptionInvalid("quiet hours must be HH:MM (24 h)")
    return v


def validate_subscription(body: Any, known_creeks: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise SubscriptionInvalid("body must be a JSON object")
    sub = body.get("subscription") or {}
    if not isinstance(sub, dict):
        raise SubscriptionInvalid("subscription must be an object")
    endpoint = validate_endpoint(sub.get("endpoint"))
    keys = sub.get("keys") or {}
    if not isinstance(keys, dict):
        raise SubscriptionInvalid("subscription.keys must be an object")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    pk = _b64url_decode(p256dh)
    if len(pk) != 65 or pk[0] != 4:
        raise SubscriptionInvalid("keys.p256dh must be an uncompressed P-256 public key")
    if len(_b64url_decode(auth)) != 16:
        raise SubscriptionInvalid("keys.auth must be 16 bytes")
    creek_ids = body.get("creek_ids") or []
    if not isinstance(creek_ids, list) or not all(isinstance(c, str) for c in creek_ids):
        raise SubscriptionInvalid("creek_ids must be a list of creek ids")
    unknown = [c for c in creek_ids if c not in known_creeks]
    if unknown:
        raise SubscriptionInvalid(f"unknown creek_ids: {', '.join(unknown[:5])}")
    min_sev = body.get("min_severity", "watch")
    if min_sev not in SEVERITY_RANK:
        raise SubscriptionInvalid("min_severity must be one of info, advisory, watch, alert")
    qh = body.get("quiet_hours") or {}
    if not isinstance(qh, dict):
        raise SubscriptionInvalid("quiet_hours must be an object")
    tz = qh.get("tz") or body.get("tz") or "America/Los_Angeles"
    try:
        if not isinstance(tz, str) or len(tz) > 64:
            raise ZoneInfoNotFoundError
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise SubscriptionInvalid("unknown time zone")
    start, end = _hhmm(qh.get("start")), _hhmm(qh.get("end"))
    if (start is None) != (end is None):
        raise SubscriptionInvalid("quiet_hours needs both start and end")
    return {"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "creek_ids": sorted(set(creek_ids)),
            "min_severity": min_sev, "quiet_start": start, "quiet_end": end, "tz": tz}


def in_quiet_hours(sub: dict, when: datetime) -> bool:
    if not sub.get("quiet_start"):
        return False
    local = when.astimezone(ZoneInfo(sub["tz"])).strftime("%H:%M")
    s, e = sub["quiet_start"], sub["quiet_end"]
    return (s <= local < e) if s < e else (local >= s or local < e)  # wraps midnight


def matches(sub: dict, alert: dict, when: datetime) -> bool:
    """Creek filter (an alert with no creek ids is regional and goes to everyone), minimum severity,
    and quiet hours (which hold back everything except 'alert', the life-safety level)."""
    creeks = sub["creek_ids"]
    if creeks and alert["area"]["creek_ids"] and not set(creeks) & set(alert["area"]["creek_ids"]):
        return False
    if SEVERITY_RANK[alert["severity"]] < SEVERITY_RANK[sub["min_severity"]]:
        return False
    if alert["severity"] != "alert" and in_quiet_hours(sub, when):
        return False
    return True


def payload_for(alert: dict, kind: str) -> bytes:
    body = {"id": alert["id"], "kind": kind, "severity": alert["severity"], "category": alert["category"],
            "title": alert["title"], "summary": alert["summary"], "source_name": alert["source_name"],
            "url": "/#alerts", "source_url": alert["url"], "creek_ids": alert["area"]["creek_ids"]}
    raw = json.dumps(body, separators=(",", ":")).encode()
    while len(raw) > MAX_PAYLOAD and len(body["summary"]) > 40:
        body["summary"] = body["summary"][: int(len(body["summary"]) * 0.7)].rstrip() + "…"
        raw = json.dumps(body, separators=(",", ":")).encode()
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("push payload too large")
    return raw


# ---- VAPID -------------------------------------------------------------------------------------

class VapidKeys:
    """Loaded from env only. Private: base64url raw 32-byte scalar or PEM. Public: base64url
    uncompressed point (derived from the private key when not given; must match when given)."""

    def __init__(self, private: str, public: str | None, subject: str):
        from py_vapid import Vapid02, b64urlencode
        from cryptography.hazmat.primitives import serialization

        self.vapid = Vapid02.from_string(private.strip())
        raw = self.vapid.public_key.public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
        derived = b64urlencode(raw)
        if public and public.strip().rstrip("=") != derived.rstrip("="):
            raise ValueError("CREEKWATCH_VAPID_PUBLIC does not match the private key")
        self.public = derived
        if not re.match(r"^(mailto:|https://)", subject):
            raise ValueError("VAPID subject must be mailto: or https://")
        self.subject = subject

    @classmethod
    def from_env(cls) -> "VapidKeys | None":
        priv = os.environ.get("CREEKWATCH_VAPID_PRIVATE", "")
        if not priv:
            return None
        try:
            return cls(priv, os.environ.get("CREEKWATCH_VAPID_PUBLIC"),
                       os.environ.get("CREEKWATCH_VAPID_SUBJECT", "https://creekwatch.realm.watch"))
        except Exception as e:  # never echo the key; only the error class
            log.error("VAPID keys from env are invalid (%s); push disabled", type(e).__name__)
            return None


# ---- hardened HTTP session ---------------------------------------------------------------------

def hardened_session():
    import requests

    class _Session(requests.Session):
        def request(self, method, url, *a, **kw):
            u = urlsplit(url)
            if u.scheme != "https" or not push_host_allowed(u.hostname or "") or u.port not in (None, 443):
                raise PermissionError("push endpoint not allowed")  # defence in depth at send time
            kw["allow_redirects"] = False
            kw["timeout"] = SEND_TIMEOUT
            kw["stream"] = True
            kw.pop("proxies", None)
            resp = super().request(method, url, *a, **kw)
            try:
                resp._content = resp.raw.read(MAX_RESPONSE, decode_content=True) or b""
            finally:
                resp.close()
            return resp

    s = _Session()
    s.trust_env = False   # ignore HTTP(S)_PROXY / netrc from the environment
    s.max_redirects = 0
    return s


# ---- subscription store + sender ---------------------------------------------------------------

class PushService:
    def __init__(self, db_path: Path, vapid: VapidKeys | None, max_subs: int = 5000, sender=None):
        self.db_path, self.vapid, self.max_subs = db_path, vapid, max_subs
        self._send = sender or self._webpush_send   # injectable for tests
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @property
    def enabled(self) -> bool:
        return self.vapid is not None

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def upsert(self, sub: dict) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock, self._conn() as c:
            exists = c.execute("SELECT 1 FROM push_subscriptions WHERE endpoint=?", (sub["endpoint"],)).fetchone()
            if not exists and c.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] >= self.max_subs:
                raise OverflowError("subscription limit reached")
            c.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, creek_ids, min_severity, quiet_start,"
                      " quiet_end, tz, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE"
                      " SET p256dh=excluded.p256dh, auth=excluded.auth, creek_ids=excluded.creek_ids,"
                      " min_severity=excluded.min_severity, quiet_start=excluded.quiet_start,"
                      " quiet_end=excluded.quiet_end, tz=excluded.tz, updated=excluded.updated, failures=0",
                      (sub["endpoint"], sub["p256dh"], sub["auth"], json.dumps(sub["creek_ids"]), sub["min_severity"],
                       sub["quiet_start"], sub["quiet_end"], sub["tz"], now, now))
        return "updated" if exists else "created"

    def delete(self, endpoint: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,)).rowcount > 0

    def all(self) -> list[dict]:
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM push_subscriptions")]
        for r in rows:
            r["creek_ids"] = json.loads(r["creek_ids"])
        return rows

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]

    def _webpush_send(self, sub: dict, data: bytes, urgency: str) -> int:
        from pywebpush import WebPushException, webpush

        try:
            resp = webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                           data=data.decode(), vapid_private_key=self.vapid.vapid,
                           vapid_claims={"sub": self.vapid.subject}, ttl=6 * 3600, timeout=SEND_TIMEOUT[1],
                           headers={"Urgency": urgency}, requests_session=hardened_session())
            return resp.status_code
        except WebPushException as e:
            return e.response.status_code if e.response is not None else 0

    def notify(self, alert: dict, kind: str, when: datetime | None = None) -> dict[str, int]:
        """Fan one NEW/ESCALATED alert out to matching subscriptions. Returns counters."""
        stats = {"matched": 0, "sent": 0, "gone": 0, "failed": 0}
        if not self.enabled:
            return stats
        when = when or datetime.now(timezone.utc)
        data = payload_for(alert, kind)
        urgency = "high" if alert["severity"] == "alert" else "normal"
        targets = [s for s in self.all() if matches(s, alert, when)]
        stats["matched"] = len(targets)

        def one(sub: dict) -> tuple[str, int]:
            try:
                validate_endpoint(sub["endpoint"])  # stored rows are re-checked before every send
                return sub["endpoint"], self._send(sub, data, urgency)
            except Exception as e:
                log.warning("push to %s failed: %s", urlsplit(sub["endpoint"]).hostname, type(e).__name__)
                return sub["endpoint"], 0

        deadline = time.monotonic() + FANOUT_DEADLINE_S
        with ThreadPoolExecutor(max_workers=FANOUT_WORKERS) as ex:
            futs = [ex.submit(one, s) for s in targets]
            done, _ = wait(futs, timeout=max(1, deadline - time.monotonic()))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn() as c:
            for f in done:
                endpoint, code = f.result()
                if 200 <= code < 300:
                    stats["sent"] += 1
                    c.execute("UPDATE push_subscriptions SET failures=0, last_ok=? WHERE endpoint=?", (now, endpoint))
                elif code in (404, 410):
                    stats["gone"] += 1
                    c.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
                else:
                    stats["failed"] += 1
                    c.execute("UPDATE push_subscriptions SET failures=failures+1 WHERE endpoint=?", (endpoint,))
                    c.execute("DELETE FROM push_subscriptions WHERE endpoint=? AND failures>=?", (endpoint, MAX_FAILURES))
        stats["failed"] += len(futs) - len(done)
        log.info("push %s %s: %s", kind, alert["id"], stats)
        return stats
