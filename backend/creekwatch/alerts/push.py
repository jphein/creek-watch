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
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from urllib.parse import quote

from .model import DEFER_SHORT, SEVERITY_RANK

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
    severities    TEXT,
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
    host = (host or "").lower()
    return host in PUSH_HOSTS_EXACT or any(host.endswith(sfx) and len(host) > len(sfx) for sfx in PUSH_HOST_SUFFIXES)


# Strict syntax: the authority may contain ONLY host characters (no userinfo '@', no '\\', no '%',
# no non-ASCII/IDNA, no whitespace) plus an optional :443; path/query are RFC 3986 characters only.
# This is what closes the urlsplit-vs-urllib3 parser differential ("https://10.0.6.1\\.push.apple.com/").
_ENDPOINT_RE = re.compile(
    r"^https://(?P<host>[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)+)"
    r"(?::443)?(?P<rest>/[A-Za-z0-9\-._~!$&'()*+,;=:@%/?]*)?$")


def endpoint_host(endpoint: Any) -> str:
    """Return the allowlisted host for a push endpoint, or raise SubscriptionInvalid.

    The same URL is parsed by the stdlib AND by the exact parser that will send it
    (requests -> urllib3); both must agree on host and port before the allowlist applies."""
    host = _syntax_host(endpoint)          # layer 1: strict charset/shape
    _same_parser_host(endpoint, host)      # layer 2: stdlib and the sending parser must agree
    if not push_host_allowed(host):        # layer 3: allowlist (DNS/IP vetting happens at send)
        raise SubscriptionInvalid("endpoint is not a recognised push service (FCM, Mozilla, Apple, Windows)")
    return host


def _syntax_host(endpoint: Any) -> str:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_LEN:
        raise SubscriptionInvalid("endpoint missing or too long")
    if not endpoint.isascii() or any(ch.isspace() or ord(ch) < 0x21 or ord(ch) == 0x7F for ch in endpoint):
        raise SubscriptionInvalid("endpoint must be plain ASCII without spaces or control characters")
    if "\\" in endpoint:
        raise SubscriptionInvalid("endpoint must not contain a backslash")
    m = _ENDPOINT_RE.match(endpoint)
    if not m:
        raise SubscriptionInvalid("endpoint must be https://<push service host>/... (no credentials, "
                                  "no port other than 443, no escapes in the host)")
    return m.group("host").lower()


def _same_parser_host(endpoint: str, host: str) -> None:
    try:
        import requests
        from urllib3.util import parse_url

        u = urlsplit(endpoint)
        sent = parse_url(requests.Request("POST", endpoint).prepare().url)
    except Exception:
        raise SubscriptionInvalid("endpoint is not a valid URL")
    if (u.hostname or "") != host or (sent.host or "").lower() != host:
        raise SubscriptionInvalid("endpoint host is ambiguous")      # parser differential: refuse
    if u.port not in (None, 443) or sent.port not in (None, 443) or u.username or u.password or sent.auth:
        raise SubscriptionInvalid("endpoint must use the default https port and no credentials")


def validate_endpoint(endpoint: Any) -> str:
    endpoint_host(endpoint)
    return endpoint


_getaddrinfo = socket.getaddrinfo  # indirection so tests can fake DNS


def _public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_global and not ip.is_multicast and not ip.is_reserved and not ip.is_unspecified
            and not ip.is_loopback and not ip.is_link_local and not ip.is_private
            and ip not in ipaddress.ip_network("100.64.0.0/10"))


def resolve_public(host: str) -> str:
    """Resolve and return an IP to connect to; refuse if ANY address is non-public (private, loopback,
    link-local, CGNAT, multicast, ULA...). Guards an allowlisted name resolving (or rebinding) inward."""
    try:
        infos = _getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as e:
        raise PermissionError(f"push host did not resolve ({type(e).__name__})")
    addrs = [i[4][0] for i in infos]
    if not addrs or not all(_public_ip(a) for a in addrs):
        raise PermissionError("push host resolves to a non-public address")
    return addrs[0]


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
    if isinstance(body.get("filters"), dict):  # web shape: {subscription, filters:{...}}
        body = {**body["filters"], "subscription": sub}
    creek_ids = body.get("creek_ids") or []
    if not isinstance(creek_ids, list) or not all(isinstance(c, str) for c in creek_ids):
        raise SubscriptionInvalid("creek_ids must be a list of creek ids")
    unknown = [c for c in creek_ids if c not in known_creeks]
    if unknown:
        raise SubscriptionInvalid(f"unknown creek_ids: {', '.join(unknown[:5])}")
    severities = body.get("severities")
    if severities is not None:
        if (not isinstance(severities, list) or not severities
                or not all(isinstance(x, str) and x in SEVERITY_RANK for x in severities)):
            raise SubscriptionInvalid("severities must be a non-empty list of info, advisory, watch, alert")
        severities = sorted(set(severities), key=SEVERITY_RANK.get)
    min_sev = body.get("min_severity") or (severities[0] if severities else "watch")
    if min_sev not in SEVERITY_RANK:
        raise SubscriptionInvalid("min_severity must be one of info, advisory, watch, alert")
    qh = body.get("quiet_hours") or {}  # null = no quiet hours
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
    if start is not None and start == end:
        raise SubscriptionInvalid("quiet_hours start and end must differ")
    return {"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "creek_ids": sorted(set(creek_ids)),
            "min_severity": min_sev, "severities": severities, "quiet_start": start, "quiet_end": end, "tz": tz}


def in_quiet_hours(sub: dict, when: datetime) -> bool:
    if not sub.get("quiet_start"):
        return False
    local = when.astimezone(ZoneInfo(sub["tz"])).strftime("%H:%M")
    s, e = sub["quiet_start"], sub["quiet_end"]
    return (s <= local < e) if s < e else (local >= s or local < e)  # wraps midnight


def matches(sub: dict, alert: dict, when: datetime) -> bool:
    """Creek filter (an alert with no creek ids is regional and goes to everyone), severity filter
    (explicit list, else minimum), and quiet hours (hold back advisory/info; watch and alert go through)."""
    creeks = sub["creek_ids"]
    if creeks and alert["area"]["creek_ids"] and not set(creeks) & set(alert["area"]["creek_ids"]):
        return False
    if sub.get("severities"):
        if alert["severity"] not in sub["severities"]:
            return False
    elif SEVERITY_RANK[alert["severity"]] < SEVERITY_RANK[sub["min_severity"]]:
        return False
    if SEVERITY_RANK[alert["severity"]] < SEVERITY_RANK["watch"] and in_quiet_hours(sub, when):
        return False
    return True


def payload_for(alert: dict, kind: str) -> bytes:
    short = alert["summary"] if len(alert["summary"]) <= 140 else alert["summary"][:139].rstrip() + "…"
    summary200 = alert["summary"] if len(alert["summary"]) <= 200 else alert["summary"][:199].rstrip() + "…"
    body = {"id": alert["id"], "alert_id": alert["id"], "tag": alert["id"], "kind": kind,
            "severity": alert["severity"], "category": alert["category"], "title": alert["title"],
            "body": short, "summary": summary200, "source_name": alert["source_name"],
            "official": alert["source"] != "creekwatch", "notice": DEFER_SHORT,
            "url": "/#alerts?id=" + quote(alert["id"], safe=""), "source_url": alert["url"],
            "creek_ids": alert["area"]["creek_ids"]}
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

    def __repr__(self) -> str:  # never let a log line or debug dump carry the private key
        return f"VapidKeys(public={self.public[:12]}…, subject={self.subject!r})"

    __str__ = __repr__

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
    from requests.adapters import HTTPAdapter
    from urllib3.util import parse_url

    class _PinnedAdapter(HTTPAdapter):
        """Connects to the vetted IP while TLS (SNI + certificate) is verified against the hostname."""

        def send(self, request, **kw):
            host = endpoint_host(request.url)          # same-parser + allowlist, at send time
            ip = resolve_public(host)                  # no inward resolution / rebinding
            u = parse_url(request.url)
            self._host = host
            request.url = u._replace(host=f"[{ip}]" if ":" in ip else ip).url
            request.headers["Host"] = host
            return super().send(request, **kw)

        def build_connection_pool_key_attributes(self, request, verify, cert=None):
            host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
            pool_kwargs["server_hostname"] = self._host
            pool_kwargs["assert_hostname"] = self._host
            return host_params, pool_kwargs

    class _Session(requests.Session):
        def request(self, method, url, *a, **kw):
            endpoint_host(url)  # refuse before anything else touches the URL
            kw["allow_redirects"] = False
            kw["timeout"] = SEND_TIMEOUT
            kw["stream"] = True
            kw["verify"] = True
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
    s.mount("https://", _PinnedAdapter(max_retries=0))
    s.mount("http://", _PinnedAdapter(max_retries=0))  # endpoint_host refuses http anyway
    return s


# ---- subscription store + sender ---------------------------------------------------------------

SEVERITY_WORDS = {"info": "all", "advisory": "advisory-level and higher", "watch": "watch-level and higher",
                  "alert": "alert-level"}
WELCOME_TAG = "cw-welcome"
WELCOME_MAX_PENDING = 20   # bound the welcome backlog (subscribe is rate-limited per IP; this caps across IPs)
WELCOME_DEDUP_S = 24 * 3600  # an endpoint is welcomed at most once per 24 h (delete/re-subscribe loops)
WELCOME_DEDUP_MAX = 10_000   # LRU size bound


def welcome_payload(sub: dict, creek_names: dict[str, str] | None = None) -> bytes:
    """The one confirmation push sent to a NEW subscription. Not an alert: touches no alert/claim state."""
    names = creek_names or {}
    creeks = ", ".join(names.get(c, c) for c in sub["creek_ids"]) if sub["creek_ids"] else "all creeks"
    sev = (min(sub["severities"], key=SEVERITY_RANK.get) if sub.get("severities") else sub["min_severity"])
    body = (f"You'll get {SEVERITY_WORDS.get(sev, sev + '+')} alerts for {creeks}. "
            "For emergencies: Nevada County Alerts, AwareCA, 911.")
    # id None (and no alert_id): the SW builds /#alerts?id=<id> for alerts; a welcome is not an alert, so
    # it must fall back to /#alerts (sw.js uses tag||id for the notification tag).
    data = {"id": None, "tag": WELCOME_TAG, "kind": "welcome", "severity": "info",
            "category": "other", "title": "Creek Watch alerts are on", "body": body[:200], "summary": body[:200],
            # no `notice`: the body already carries the emergency line, and sw.js appends notice to the body
            "source_name": "Creek Watch", "official": False, "url": "/#alerts",
            "source_url": None, "creek_ids": sub["creek_ids"]}
    raw = json.dumps(data, separators=(",", ":")).encode()
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("welcome payload too large")
    return raw


class PushService:
    def __init__(self, db_path: Path, vapid: VapidKeys | None, max_subs: int = 5000, sender=None):
        self.db_path, self.vapid, self.max_subs = db_path, vapid, max_subs
        self._send = sender or self._webpush_send   # injectable for tests
        self._welcome_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push-welcome")
        self._welcome_pending: set = set()
        self._welcomed: "OrderedDict[str, float]" = OrderedDict()   # sha256(endpoint) -> time welcomed
        self._clock = time.time
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
            c.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, creek_ids, min_severity, severities,"
                      " quiet_start, quiet_end, tz, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                      " ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth,"
                      " creek_ids=excluded.creek_ids, min_severity=excluded.min_severity,"
                      " severities=excluded.severities, quiet_start=excluded.quiet_start,"
                      " quiet_end=excluded.quiet_end, tz=excluded.tz, updated=excluded.updated, failures=0",
                      (sub["endpoint"], sub["p256dh"], sub["auth"], json.dumps(sub["creek_ids"]), sub["min_severity"],
                       json.dumps(sub["severities"]) if sub.get("severities") else None,
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
            r["severities"] = json.loads(r["severities"]) if r.get("severities") else None
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

    def welcome_async(self, sub: dict, creek_names: dict[str, str] | None = None):
        """Queue ONE confirmation push to this (new) subscription, off the request thread. Same
        hardened send path; 404/410 prunes it; failures are logged, never raised to the caller.
        Returns the Future, or None when push is off or the backlog is full."""
        if not self.enabled:
            return None
        key = hashlib.sha256(sub["endpoint"].encode()).hexdigest()
        now = self._clock()
        with self._lock:
            while self._welcomed and (len(self._welcomed) > WELCOME_DEDUP_MAX
                                      or now - next(iter(self._welcomed.values())) > WELCOME_DEDUP_S):
                self._welcomed.popitem(last=False)          # LRU / TTL eviction (oldest first)
            if key in self._welcomed:
                log.info("welcome push skipped: endpoint welcomed in the last 24 h")
                return None
            if len(self._welcome_pending) >= WELCOME_MAX_PENDING:
                log.warning("welcome push skipped: backlog full")
                return None
            self._welcomed[key] = now
            fut = self._welcome_pool.submit(self._welcome_send, dict(sub), creek_names)
            self._welcome_pending.add(fut)
        fut.add_done_callback(lambda f: self._welcome_pending.discard(f))
        return fut

    def _welcome_send(self, sub: dict, creek_names: dict[str, str] | None) -> int:
        try:
            validate_endpoint(sub["endpoint"])
            code = self._send(sub, welcome_payload(sub, creek_names), "normal")
        except Exception as e:
            log.warning("welcome push to %s failed: %s", urlsplit(sub["endpoint"]).hostname, type(e).__name__)
            return 0
        if code in (404, 410):
            self.delete(sub["endpoint"])
        log.info("welcome push to %s: %s", urlsplit(sub["endpoint"]).hostname, code)
        return code

    def drain(self, timeout: float = 10) -> None:
        """Wait for queued welcome pushes (tests/shutdown)."""
        wait(list(self._welcome_pending), timeout=timeout)

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

        # NOT a `with` block: its exit would shutdown(wait=True) and silently wait for every send,
        # making the deadline dead. Stragglers are abandoned (their own timeouts end them).
        ex = ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="push")
        try:
            futs = [ex.submit(one, s) for s in targets]
            done, _ = wait(futs, timeout=FANOUT_DEADLINE_S)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
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
