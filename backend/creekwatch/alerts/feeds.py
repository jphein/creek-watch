"""Atom 1.0 and CAP 1.2 renderings of the alert store. Built with ElementTree, so every text node and
attribute is escaped by the serializer (feed-injection safe); nothing is string-concatenated into XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .model import OFFICIAL_CHANNELS

ATOM = "http://www.w3.org/2005/Atom"
CAP = "urn:oasis:names:tc:emergency:cap:1.2"
ET.register_namespace("", ATOM)
ET.register_namespace("cap", CAP)
TAG = "tag:creekwatch.realm.watch,2026"

CAP_CATEGORY = {"flood": "Met", "flash_flood": "Met", "storm": "Met", "heat": "Met", "sewage_spill": "Env",
                "contamination": "Env", "runoff": "Env", "low_flow": "Env", "high_flow": "Env",
                "algal_bloom": "Health", "bacteria": "Health", "other": "Other"}
DERIVED = {  # severity -> (urgency, severity, certainty) when the source gave no CAP values
    "alert": ("Immediate", "Severe", "Likely"), "watch": ("Expected", "Moderate", "Possible"),
    "advisory": ("Future", "Minor", "Possible"), "info": ("Unknown", "Unknown", "Unknown"),
}
EVENT = {"flood": "Flood", "flash_flood": "Flash Flood", "storm": "Storm", "heat": "Heat",
         "sewage_spill": "Sewage Spill", "algal_bloom": "Harmful Algal Bloom", "bacteria": "Bacteria Advisory",
         "low_flow": "Low Stream Flow", "high_flow": "High Stream Flow", "contamination": "Water Contamination",
         "runoff": "Runoff / Sediment", "other": "Water Advisory"}


def _sub(parent: ET.Element, tag: str, text: str | None = None, ns: str = ATOM, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ns}}}{tag}", {k.rstrip("_"): v for k, v in attrs.items()})
    if text is not None:
        el.text = text
    return el


def cap_time(iso_z: str) -> str:
    """CAP 1.2 forbids 'Z': times need an explicit numeric offset."""
    return iso_z.replace("Z", "+00:00")


def _alert_app_url(base: str, a: dict) -> str:
    return f"{base}/#alerts"


# ---- Atom ---------------------------------------------------------------------------------------

def atom_feed(alerts: list[dict], base: str, self_url: str, updated: str, title: str) -> bytes:
    feed = ET.Element(f"{{{ATOM}}}feed")
    _sub(feed, "id", f"{TAG}:alerts" + (self_url.split("?", 1)[1].replace("&", ":") if "?" in self_url else ""))
    _sub(feed, "title", title)
    _sub(feed, "subtitle", "Water-related alerts for Nevada County creeks, relayed from official sources with "
                           "attribution, plus Creek Watch community early warnings. Not an official warning "
                           "service. " + OFFICIAL_CHANNELS)
    _sub(feed, "updated", max([a["updated"] for a in alerts], default=updated))
    _sub(feed, "link", rel="self", href=self_url, type="application/atom+xml")
    _sub(feed, "link", rel="alternate", href=f"{base}/#alerts", type="text/html")
    _sub(feed, "generator", "Creek Watch", uri=base)
    author = _sub(feed, "author"); _sub(author, "name", "Creek Watch"); _sub(author, "uri", base)
    for a in alerts:
        e = _sub(feed, "entry")
        _sub(e, "id", f"{TAG}:alert:{a['id']}")
        _sub(e, "title", f"[{a['severity'].upper()}] {a['title']}")
        _sub(e, "updated", a["updated"])
        _sub(e, "published", a["effective"])
        _sub(e, "link", rel="alternate", href=a["url"], type="text/html")  # the official source
        _sub(e, "link", rel="related", href=_alert_app_url(base, a), type="text/html")
        _sub(e, "category", term=a["category"], label=a["category"].replace("_", " "))
        _sub(e, "category", term=f"severity:{a['severity']}")
        for cid in a["area"]["creek_ids"]:
            _sub(e, "category", term=f"creek:{cid}")
        au = _sub(e, "author"); _sub(au, "name", a["source_name"])
        body = a["summary"]
        if a.get("instruction"):
            body += f"\n\nWhat to do: {a['instruction']}"
        body += f"\n\nArea: {a['area']['area_desc']}. Source: {a['source_name']} ({a['url']})."
        if a.get("expires"):
            body += f" Expires {a['expires']}."
        if a["source"] == "creekwatch":
            body += "\n\nCommunity early warning derived from volunteer reports and public data; not an official warning."
        body += f"\n\n{OFFICIAL_CHANNELS}"
        _sub(e, "summary", body, type="text")
        _sub(e, "rights", a["attribution"])
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


# ---- CAP 1.2 ------------------------------------------------------------------------------------

def _cap_polygons(geo: dict | None) -> list[str]:
    if not geo:
        return []
    rings = [geo["coordinates"][0]] if geo["type"] == "Polygon" else [p[0] for p in geo["coordinates"]]
    out = []
    for ring in rings[:10]:
        pts = [(float(p[1]), float(p[0])) for p in ring]
        if len(pts) < 3:
            continue
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        if len(pts) >= 4:
            out.append(" ".join(f"{lat:.5f},{lon:.5f}" for lat, lon in pts))
    return out


NWS_SENDER = "w-nws.webmaster@noaa.gov"


def relay_references(a: dict) -> str | None:
    """CAP <references> ("sender,identifier,sent") pointing at the original official message.
    Uses the adapter's cap_identifier/cap_sender/cap_sent when given; for NWS falls back to the
    identifier embedded in our id ("nws:<identifier>") and the alert's updated time."""
    ident = a.get("cap_identifier") or (a["id"].split(":", 1)[1] if a["source"] == "nws" else None)
    sender = a.get("cap_sender") or (NWS_SENDER if a["source"] == "nws" else None)
    if not ident or not sender or any(ch in ident + sender for ch in " ,<&"):
        return None
    return f"{sender},{ident},{cap_time(a.get('cap_sent') or a['updated'])}"


def cap_alert(a: dict, sender: str = "creekwatch.realm.watch") -> ET.Element:
    """One schema-valid CAP 1.2 <alert> (element order follows the OASIS XSD sequence)."""
    al = ET.Element(f"{{{CAP}}}alert")
    c = lambda parent, tag, text=None: _sub(parent, tag, text, ns=CAP)  # noqa: E731
    c(al, "identifier", f"creekwatch-{a['id']}".replace(" ", "_").replace(",", "_"))
    c(al, "sender", sender)
    c(al, "sent", cap_time(a["updated"]))
    c(al, "status", "Actual")
    refs = relay_references(a)
    c(al, "msgType", "Cancel" if a["status"] == "cancelled" else "Alert")
    c(al, "source", a["source_name"])
    c(al, "scope", "Public")
    if a["source"] == "creekwatch":
        note = ("Creek Watch community early warning, derived from volunteer citizen reports and public data. "
                "Not an official warning. ")
    else:
        note = (f"Relayed by Creek Watch from {a['source_name']} with attribution; the official message is "
                f"authoritative ({a['url']}). Creek Watch does not issue official warnings. ")
    c(al, "note", note + OFFICIAL_CHANNELS)
    if refs:
        c(al, "references", refs)
    info = c(al, "info")
    c(info, "language", "en-US")
    c(info, "category", CAP_CATEGORY.get(a["category"], "Other"))
    c(info, "event", a.get("event") or EVENT.get(a["category"], "Water Advisory"))
    du, ds, dc = DERIVED[a["severity"]]
    c(info, "urgency", a.get("cap_urgency") or du)
    c(info, "severity", a.get("cap_severity") or ds)
    c(info, "certainty", a.get("cap_certainty") or dc)
    c(info, "effective", cap_time(a["effective"]))
    if a.get("expires"):
        c(info, "expires", cap_time(a["expires"]))
    c(info, "senderName", a["source_name"])
    c(info, "headline", a["title"])
    c(info, "description", a["summary"])
    if a.get("instruction"):
        c(info, "instruction", a["instruction"])
    c(info, "web", a["url"])
    area = c(info, "area")
    c(area, "areaDesc", a["area"]["area_desc"])
    for poly in _cap_polygons(a["area"].get("polygon_geojson")):
        c(area, "polygon", poly)
    if a["area"].get("lat") is not None and a["area"].get("lon") is not None:
        c(area, "circle", f"{a['area']['lat']:.5f},{a['area']['lon']:.5f} 1.0")
    return al


def cap_document(a: dict) -> bytes:
    return ET.tostring(cap_alert(a), encoding="utf-8", xml_declaration=True)


def cap_feed(alerts: list[dict], base: str, self_url: str, updated: str) -> bytes:
    """Atom index whose entries each carry one CAP 1.2 <alert> as content (the CAP-over-Atom pattern
    NWS uses). Each embedded <cap:alert> validates against the OASIS XSD on its own."""
    feed = ET.Element(f"{{{ATOM}}}feed")
    _sub(feed, "id", f"{TAG}:alerts:cap")
    _sub(feed, "title", "Creek Watch water alerts (CAP 1.2)")
    _sub(feed, "updated", max([a["updated"] for a in alerts], default=updated))
    _sub(feed, "link", rel="self", href=self_url, type="application/atom+xml")
    author = _sub(feed, "author"); _sub(author, "name", "Creek Watch")
    for a in alerts:
        e = _sub(feed, "entry")
        _sub(e, "id", f"{TAG}:alert:{a['id']}:cap")
        _sub(e, "title", a["title"])
        _sub(e, "updated", a["updated"])
        _sub(e, "link", rel="alternate", href=a["url"])
        content = _sub(e, "content", type="application/cap+xml")
        content.append(cap_alert(a))
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)
