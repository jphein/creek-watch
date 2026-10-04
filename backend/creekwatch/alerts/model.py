"""The Alert model (docs/ALERTS-SPEC.md) and its validation.

Alerts come from adapters we don't control (official feeds, scraped data), and they're rendered into
JSON, Atom, CAP and push payloads, so every field is checked and bounded here, once, before storage.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

SEVERITIES = ("info", "advisory", "watch", "alert")  # ascending
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
CATEGORIES = {"flood", "flash_flood", "storm", "heat", "sewage_spill", "algal_bloom", "bacteria", "low_flow",
              "high_flow", "contamination", "runoff", "other"}
STATUSES = {"active", "expired", "cancelled"}
CAP_URGENCY = {"Immediate", "Expected", "Future", "Past", "Unknown"}
CAP_SEVERITY = {"Extreme", "Severe", "Moderate", "Minor", "Unknown"}
CAP_CERTAINTY = {"Observed", "Likely", "Possible", "Unlikely", "Unknown"}

ID_RE = re.compile(r"^[a-z0-9_]{1,32}:[A-Za-z0-9._:/#-]{1,200}$")
SOURCE_RE = re.compile(r"^[a-z0-9_]{1,32}$")
# Control chars (except \t \n) break XML 1.0 and terminals; strip them from every string.
_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff\ud800-\udfff]")  # + lone surrogates: they 500 JSONResponse and make XML ill-formed
LIMITS = {"title": 200, "summary": 280, "instruction": 1000, "source_name": 120, "attribution": 300,
          "area_desc": 300, "event": 120}


# Life-safety deferral (docs/devpost/PRIOR-ART.md §2b): Creek Watch relays and summarises; it is not an
# official warning service. Shown in feeds, CAP notes and push payloads.
OFFICIAL_CHANNELS = ("For emergencies call 911. Official alerts: Nevada County Alerts "
                     "(https://www.nevadacountyca.gov/3780/Emergency-Alerts), AwareCA, and NWS Wireless Emergency Alerts.")
DEFER_SHORT = "Emergencies: 911. Official: Nevada County Alerts, AwareCA."
CAP_TOKEN_RE = re.compile(r"^[^\s,<&]{1,240}$")  # CAP identifier/sender: no spaces, commas or < &


class AlertInvalid(ValueError):
    pass


def _text(v: Any, field: str, required: bool = True) -> str | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise AlertInvalid(f"{field} is required")
        return None
    if not isinstance(v, str):
        raise AlertInvalid(f"{field} must be a string")
    v = _CTRL.sub("", v).strip()
    lim = LIMITS.get(field)
    if lim and len(v) > lim:
        v = v[: lim - 1].rstrip() + "…"
    return v


def _time(v: Any, field: str, required: bool = True) -> str | None:
    if v in (None, ""):
        if required:
            raise AlertInvalid(f"{field} is required")
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            raise AlertInvalid(f"{field} is not ISO-8601: {str(v)[:40]!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Host characters only in the authority: no userinfo "@", backslash, "%", non-ASCII; port 443 only.
_SAFE_URL = re.compile(
    r"^https://[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)+"
    r"(?::443)?(?:[/?#][A-Za-z0-9\-._~!$&'()*+,;=:@%/?#]*)?$")


def _https(v: Any, field: str) -> str:
    """Links rendered to browsers and feed readers. WHATWG parsers treat a backslash as "/", so
    https://evil.example<backslash>@official.gov/ would pass a urlsplit-based check yet open evil."""
    v = _text(v, field)
    if len(v) > 500 or not v.isascii() or "\\" in v or not _SAFE_URL.match(v):
        raise AlertInvalid(f"{field} must be a plain https URL (no credentials, escapes or non-default port)")
    return v


def _num(v: Any, lo: float, hi: float) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def _ids(v: Any) -> list[str]:
    if not v:
        return []
    if not isinstance(v, (list, tuple)):
        raise AlertInvalid("area ids must be a list")
    out = [x for x in v if isinstance(x, str) and re.match(r"^[a-z0-9-]{1,64}$", x)]
    return out[:50]


def _polygon(v: Any) -> dict | None:
    """Keep only a GeoJSON Polygon/MultiPolygon with sane numeric coordinates (bounded size)."""
    if not isinstance(v, dict) or v.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    coords, n = v.get("coordinates"), [0]

    def ok(x: Any, depth: int) -> bool:
        if depth == 0:
            n[0] += 1
            return (isinstance(x, (list, tuple)) and len(x) >= 2
                    and all(isinstance(c, (int, float)) for c in x[:2])
                    and -180 <= x[0] <= 180 and -90 <= x[1] <= 90)
        return isinstance(x, (list, tuple)) and len(x) > 0 and all(ok(y, depth - 1) for y in x)

    depth = 2 if v["type"] == "Polygon" else 3
    if not ok(coords, depth) or n[0] > 5000:
        return None
    return {"type": v["type"], "coordinates": coords}


def validate_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a clean, bounded Alert dict or raise AlertInvalid."""
    if not isinstance(raw, dict):
        raise AlertInvalid("alert must be an object")
    aid = raw.get("id")
    if not isinstance(aid, str) or not ID_RE.match(aid):
        raise AlertInvalid(f"bad id {str(aid)[:60]!r}")
    source = raw.get("source")
    if not isinstance(source, str) or not SOURCE_RE.match(source) or not aid.startswith(source + ":"):
        raise AlertInvalid("source must be a slug and prefix the id")
    if raw.get("category") not in CATEGORIES:
        raise AlertInvalid(f"bad category {raw.get('category')!r}")
    if raw.get("severity") not in SEVERITY_RANK:
        raise AlertInvalid(f"bad severity {raw.get('severity')!r}")
    status = raw.get("status", "active")
    if status not in STATUSES:
        raise AlertInvalid(f"bad status {status!r}")
    area = raw.get("area") or {}
    if not isinstance(area, dict):
        raise AlertInvalid("area must be an object")
    a = {
        "id": aid, "source": source, "source_name": _text(raw.get("source_name"), "source_name"),
        "category": raw["category"], "severity": raw["severity"],
        "title": _text(raw.get("title"), "title"), "summary": _text(raw.get("summary"), "summary"),
        "instruction": _text(raw.get("instruction"), "instruction", required=False),
        "area": {"creek_ids": _ids(area.get("creek_ids")), "site_ids": _ids(area.get("site_ids")),
                 "lat": _num(area.get("lat"), -90, 90), "lon": _num(area.get("lon"), -180, 180),
                 "polygon_geojson": _polygon(area.get("polygon_geojson")),
                 "area_desc": _text(area.get("area_desc") or "Nevada County, CA", "area_desc")},
        "effective": _time(raw.get("effective"), "effective"),
        "expires": _time(raw.get("expires"), "expires", required=False),
        "updated": _time(raw.get("updated") or raw.get("effective"), "updated"),
        "status": status, "url": _https(raw.get("url"), "url"),
        "attribution": _text(raw.get("attribution"), "attribution"),
    }
    # Optional CAP passthrough for official CAP sources (so the CAP feed isn't reworded).
    if raw.get("event"):
        a["event"] = _text(raw["event"], "event")
    for k, allowed in (("cap_urgency", CAP_URGENCY), ("cap_severity", CAP_SEVERITY),
                       ("cap_certainty", CAP_CERTAINTY)):
        if raw.get(k) in allowed:
            a[k] = raw[k]
    # Relay provenance for official CAP sources (NWS): the original message's identifier/sender/sent,
    # emitted as CAP <references> so we are a relay with attribution, not a re-issuer.
    for k in ("cap_identifier", "cap_sender"):
        v = raw.get(k)
        if isinstance(v, str) and CAP_TOKEN_RE.match(v):
            a[k] = v
    if raw.get("cap_sent"):
        try:
            a["cap_sent"] = _time(raw["cap_sent"], "cap_sent")
        except AlertInvalid:
            pass
    return a
