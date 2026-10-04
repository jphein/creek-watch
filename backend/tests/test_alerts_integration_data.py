"""Integration: the REAL data.alerts.ADAPTERS (#38) through the REAL poller + store, on the data lane's
captured fixtures (no network). Proves the contract end to end:
  - a RAISING source changes nothing (no expire-on-failure),
  - a SUCCESSFUL empty fetch expires that source's alerts,
  - every real alert passes validate_alert and renders schema-valid CAP 1.2."""
import copy
import importlib.util
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("data.alerts") is None, reason="data.alerts not present")

NOW = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)   # the fixtures' capture time
GAUGE = {"site_no": "11418500", "name": "DEER C NR SMARTSVILLE CA", "discharge_cfs": 4.8, "gage_height_ft": 2.5,
         "pct_of_median": 93, "on_creek": True, "observed_at": "2026-10-04T02:45:00Z",
         "source_url": "https://waterdata.usgs.gov/monitoring-location/11418500/"}
CONDITIONS = {"gauge": GAUGE, "weather": {"temp_f": 88, "precip_24h_in": 0.0, "forecast_short": "Sunny",
                                          "observed_at": "2026-10-04T02:00:00Z", "source_url": "https://www.weather.gov/"},
              "fetched_at": "2026-10-04T03:00:00Z"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from data import alerts, sites, wq
    from data.alerts import http
    from data.tests.test_alerts import OEHHA_FIX, route   # the data lane's own fixture router
    from creekwatch.alerts.poller import AlertContext, Poller
    from creekwatch.alerts.store import AlertStore

    monkeypatch.setattr(http, "get_text", route())
    monkeypatch.setattr(wq, "_gql", lambda ref, timeout: [])
    store = AlertStore(tmp_path / "i.db")
    ctx = lambda: AlertContext(creeks=sites.load_creeks(), reports_fn=lambda c, d: [],  # noqa: E731
                               conditions_fn=lambda c: copy.deepcopy(CONDITIONS), now=NOW)
    poller = Poller(alerts.ADAPTERS, store, ctx)
    yield {"poller": poller, "store": store, "http": http, "route": route, "OEHHA_FIX": OEHHA_FIX,
           "monkeypatch": monkeypatch}
    poller.shutdown()


def _ids(store, source, status="active"):
    return sorted(a["id"] for a in store.query(source=source, status=status, limit=500))


def test_real_adapters_all_run_and_validate(world):
    from lxml import etree
    from creekwatch.alerts import feeds
    p, store = world["poller"], world["store"]
    assert {a.source for a in p.adapters.values()} >= {"nws", "nwps", "sso", "hab", "riverdb", "oehha", "usgs", "creekwatch"}
    s = p.run_due(force=True)
    assert s["failed"] == {}, s["failed"]
    assert set(s["ran"]) == set(p.adapters)
    rows = store.query(status=None, limit=500)
    assert len(rows) > 10 and _ids(store, "oehha")          # OEHHA advisories are standing (no expiry)
    xsd = etree.XMLSchema(etree.parse(str(Path(__file__).parent / "schemas" / "CAP-v1.2.xsd")))
    for a in rows:
        assert xsd.validate(etree.ElementTree(etree.fromstring(ET.tostring(feeds.cap_alert(a))))), a["id"]


def test_raising_source_keeps_alerts_successful_empty_expires(world):
    p, store, mp = world["poller"], world["store"], world["monkeypatch"]
    p.run_due(force=True)
    before = _ids(store, "oehha")
    assert before, "fixture should yield OEHHA advisories"

    # 1) OEHHA's upstream fails: the real adapter RAISES -> its alerts must stay active
    real = world["route"]()
    def oehha_down(url, **kw):
        if "datastore_search" in url and "datastore_search_sql" not in url:
            raise OSError("CKAN 503")
        return real(url, **kw)
    mp.setattr(world["http"], "get_text", oehha_down)
    s = p.run_due(force=True)
    assert "oehha" in s["failed"]
    assert _ids(store, "oehha") == before, "a failed fetch must not expire anything"

    # 2) OEHHA answers successfully with zero advisories -> they are resolved (expired)
    empty = copy.deepcopy(world["OEHHA_FIX"]); empty["result"]["records"] = []
    mp.setattr(world["http"], "get_text", world["route"](oehha=empty))
    s = p.run_due(force=True)
    assert "oehha" in s["ran"] and "oehha" not in s["failed"]
    assert _ids(store, "oehha") == [] and set(_ids(store, "oehha", "expired")) == set(before)
    assert _ids(store, "hab") or _ids(store, "hab", None), "other sources untouched"
