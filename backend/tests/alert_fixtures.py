"""Shared alert fixtures for the alerts tests."""
import copy
import time
from types import SimpleNamespace


def make_alert(id="nws:abc-1", source="nws", severity="watch", category="flood", creek_ids=("deer",), **kw):
    a = {
        "id": id, "source": source, "source_name": "National Weather Service", "category": category,
        "severity": severity, "title": "Flood Watch for Nevada County",
        "summary": "Heavy rain may cause creeks to rise quickly.", "instruction": "Stay away from creek banks.",
        "area": {"creek_ids": list(creek_ids), "site_ids": [], "lat": 39.26, "lon": -121.02,
                 "polygon_geojson": {"type": "Polygon", "coordinates": [[[-121.1, 39.2], [-121.0, 39.2],
                                                                         [-121.0, 39.3], [-121.1, 39.2]]]},
                 "area_desc": "Western Nevada County"},
        "effective": "2026-10-03T18:00:00Z", "expires": "2099-10-04T18:00:00Z", "updated": "2026-10-03T18:00:00Z",
        "status": "active", "url": "https://api.weather.gov/alerts/abc-1", "attribution": "NOAA/NWS (public domain)",
    }
    a.update(kw)
    return a


class FakeAdapter:
    def __init__(self, source, alerts=None, interval_s=300, exc=None, sleep=0.0):
        self.source, self.source_name, self.interval_s = source, source.upper(), interval_s
        self.alerts, self.exc, self.sleep, self.calls = alerts or [], exc, sleep, 0

    def fetch(self, ctx):
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        if self.exc:
            raise self.exc
        return copy.deepcopy(self.alerts)


class RecordingPush:
    def __init__(self):
        self.sent = []

    def notify(self, alert, kind):
        self.sent.append((alert["id"], alert["severity"], kind))
        return {"sent": 1}


def ctx_factory():
    from creekwatch.alerts.poller import AlertContext
    return AlertContext(creeks=[{"id": "wolf", "sites": []}, {"id": "deer", "sites": []}],
                        reports_fn=lambda c, d: [], conditions_fn=lambda c: {})


NS = SimpleNamespace
