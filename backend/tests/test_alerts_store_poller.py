import time

import pytest

from alert_fixtures import FakeAdapter, RecordingPush, ctx_factory, make_alert
from creekwatch.alerts.model import AlertInvalid, validate_alert
from creekwatch.alerts.poller import Poller
from creekwatch.alerts.store import AlertStore


@pytest.fixture
def store(tmp_path):
    return AlertStore(tmp_path / "a.db")


# ---- model -------------------------------------------------------------------------------------

def test_validate_good_and_bounded():
    a = validate_alert(make_alert(summary="x" * 400, title="Flood\x00 Watch\x1b[31m"))
    assert len(a["summary"]) == 280 and a["summary"].endswith("…")
    assert "\x00" not in a["title"] and "\x1b" not in a["title"]
    assert a["effective"].endswith("Z")


@pytest.mark.parametrize("bad", [
    {"severity": "extreme"}, {"category": "zombies"}, {"status": "maybe"}, {"url": "http://example.com/x"},
    {"url": "javascript:alert(1)"}, {"id": "nws abc"}, {"id": "other:abc"}, {"title": ""},
    {"effective": "yesterday"}, {"source": "NWS!"},
])
def test_validate_rejects(bad):
    with pytest.raises(AlertInvalid):
        validate_alert(make_alert(**bad))


def test_polygon_sanitised():
    a = validate_alert(make_alert(area={"creek_ids": ["deer", "BAD ID"], "polygon_geojson": {"type": "Point"}}))
    assert a["area"]["polygon_geojson"] is None and a["area"]["creek_ids"] == ["deer"]


# ---- store -------------------------------------------------------------------------------------

def test_store_new_unchanged_escalated_expired_reactivated(store):
    a = validate_alert(make_alert())
    assert [c.kind for c in store.apply_fetch("nws", [a])] == ["new"]
    assert [c.kind for c in store.apply_fetch("nws", [a])] == ["unchanged"]
    up = validate_alert(make_alert(severity="alert", updated="2026-10-03T19:00:00Z"))
    assert [c.kind for c in store.apply_fetch("nws", [up])] == ["escalated"]
    down = validate_alert(make_alert(severity="advisory", updated="2026-10-03T20:00:00Z"))
    assert [c.kind for c in store.apply_fetch("nws", [down])] == ["updated"]
    store.apply_fetch("nws", [])  # source no longer reports it -> expired
    assert store.get("nws:abc-1")["status"] == "expired" and store.query() == []
    assert [c.kind for c in store.apply_fetch("nws", [down])] == ["new"]  # re-activated


def test_store_filters_and_time_expiry(store):
    store.apply_fetch("nws", [validate_alert(make_alert()),
                              validate_alert(make_alert(id="nws:2", severity="advisory", creek_ids=("wolf",),
                                                        category="heat"))])
    store.apply_fetch("sso", [validate_alert(make_alert(id="sso:9", source="sso", severity="alert",
                                                        category="sewage_spill", expires="2026-01-01T00:00:00Z"))])
    assert [a["id"] for a in store.query(creek_id="wolf")] == ["nws:2"]
    assert [a["id"] for a in store.query(severity="watch")] == ["nws:abc-1"]  # sso arrived already expired
    assert [a["id"] for a in store.query(category="heat")] == ["nws:2"]
    assert {a["id"] for a in store.query(status=None)} == {"nws:abc-1", "nws:2", "sso:9"}
    assert store.expire_due() == 0                                       # nothing past its expiry yet
    assert store.expire_due(now="2100-01-01T00:00:00Z") == 2             # both nws alerts expire (2099)
    assert store.get("nws:abc-1")["status"] == "expired" and store.query() == []
    # an alert that is already past its expiry at ingest is stored expired and is never "new"
    assert [c.kind for c in store.apply_fetch("sso", [validate_alert(make_alert(
        id="sso:old", source="sso", expires="2026-01-01T00:00:00Z"))])] == ["unchanged"]


def test_other_sources_untouched_by_a_fetch(store):
    store.apply_fetch("nws", [validate_alert(make_alert())])
    store.apply_fetch("sso", [])
    assert store.get("nws:abc-1")["status"] == "active"


# ---- poller ------------------------------------------------------------------------------------

def test_poller_isolation_hang_and_crash_do_not_block(store):
    ok = FakeAdapter("nws", [make_alert()])
    boom = FakeAdapter("sso", exc=RuntimeError("upstream 500"))
    hang = FakeAdapter("hab", sleep=3.0)
    p = Poller([ok, boom, hang], store, ctx_factory, fetch_timeout_s=0.5)
    t0 = time.monotonic()
    summary = p.run_due()
    assert time.monotonic() - t0 < 2.0, "a hung source must not hold the cycle past the deadline"
    assert summary["ran"] == ["nws"] and set(summary["failed"]) == {"sso", "hab"}
    assert store.get("nws:abc-1")["status"] == "active"
    src = {r["source"]: r for r in store.sources()}
    assert src["sso"]["failures"] == 1 and "upstream 500" in src["sso"]["last_error"]
    assert p.state["hab"].running  # still sleeping: must not be relaunched
    p.run_due(force=True)
    assert hang.calls == 1
    p.shutdown()


def test_poller_backoff_and_schedule(store):
    clock = [1000.0]
    boom = FakeAdapter("sso", exc=ValueError("x"), interval_s=300)
    p = Poller([boom], store, ctx_factory, clock=lambda: clock[0])
    p.run_due()
    assert p.state["sso"].next_run == 1000 + 600  # interval * 2**1
    clock[0] += 599; p.run_due(); assert boom.calls == 1   # not due yet
    clock[0] += 2; p.run_due(); assert boom.calls == 2
    assert p.state["sso"].next_run == clock[0] + 1200      # 2**2
    boom.exc = None
    clock[0] += 1200; p.run_due()
    assert p.state["sso"].failures == 0 and p.state["sso"].next_run == clock[0] + 300
    p.shutdown()


def test_push_only_new_or_escalated(store):
    src = FakeAdapter("nws", [make_alert()])
    push = RecordingPush()
    p = Poller([src], store, ctx_factory, push=push)
    p.run_due(force=True); p.run_due(force=True)
    assert push.sent == [("nws:abc-1", "watch", "new")]                 # second identical run: nothing
    src.alerts = [make_alert(severity="advisory", updated="2026-10-03T19:00:00Z")]
    p.run_due(force=True)
    assert len(push.sent) == 1                                          # downgrade: no push
    src.alerts = [make_alert(severity="alert", updated="2026-10-03T20:00:00Z")]
    p.run_due(force=True)
    assert push.sent[-1] == ("nws:abc-1", "alert", "escalated")
    src.alerts = []; p.run_due(force=True)                              # expires
    src.alerts = [make_alert(severity="alert", updated="2026-10-03T21:00:00Z")]
    p.run_due(force=True)
    assert len(push.sent) == 2, "re-activation at an already-pushed severity must not re-notify"
    p.shutdown()


def test_poller_drops_invalid_and_foreign_alerts(store):
    src = FakeAdapter("nws", [make_alert(), make_alert(id="nws:bad", severity="apocalypse"),
                              make_alert(id="sso:spoof", source="sso")])
    p = Poller([src], store, ctx_factory)
    p.run_due(force=True)
    assert [a["id"] for a in store.query(status=None)] == ["nws:abc-1"]
    p.shutdown()


def test_poller_rejects_non_list(store):
    class Weird(FakeAdapter):
        def fetch(self, ctx):
            return {"not": "a list"}
    p = Poller([Weird("nws")], store, ctx_factory)
    assert "nws" in p.run_due(force=True)["failed"]
    p.shutdown()


def test_claim_push_is_atomic_across_processes(tmp_path):
    a, b = AlertStore(tmp_path / "x.db"), AlertStore(tmp_path / "x.db")   # live + staging container
    a.apply_fetch("nws", [validate_alert(make_alert())])
    assert a.claim_push("nws:abc-1", "watch") is True
    assert b.claim_push("nws:abc-1", "watch") is False                   # second process loses
    assert b.claim_push("nws:abc-1", "advisory") is False                # lower: never re-announce
    assert b.claim_push("nws:abc-1", "alert") is True                    # escalation: exactly once
    assert a.claim_push("nws:abc-1", "alert") is False


def test_two_pollers_one_push(tmp_path):
    push_a, push_b = RecordingPush(), RecordingPush()
    pa = Poller([FakeAdapter("nws", [make_alert()])], AlertStore(tmp_path / "y.db"), ctx_factory, push=push_a)
    pb = Poller([FakeAdapter("nws", [make_alert()])], AlertStore(tmp_path / "y.db"), ctx_factory, push=push_b)
    pa.run_due(force=True); pb.run_due(force=True)
    assert len(push_a.sent) + len(push_b.sent) == 1
    pa.shutdown(); pb.shutdown()


def test_app_without_lifespan_has_reports_table(tmp_path):
    """The CLI poller builds the app but never runs its lifespan; the creekwatch adapter reads reports."""
    from creekwatch.config import Settings
    from creekwatch.main import create_app
    app = create_app(Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json"))
    ctx = app.state.alert_poller.ctx_factory()
    assert ctx.reports(ctx.creek_ids[0], 14) == []



# ---- Oracle should-fix + notes -----------------------------------------------------------------

def test_lone_surrogates_stripped_api_and_xml_survive(tmp_path):
    from fastapi.testclient import TestClient
    from lxml import etree
    from creekwatch.config import Settings
    from creekwatch.main import create_app
    a = validate_alert(make_alert(title="Flood \ud800 Watch", summary="bad \udfff surrogate", instruction="x\ud83d"))
    assert "\ud800" not in a["title"] and "\udfff" not in a["summary"] and "\ud83d" not in a["instruction"]
    app = create_app(Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json"))
    with TestClient(app) as c:
        app.state.alert_store.apply_fetch("nws", [a])
        assert c.get("/api/alerts").status_code == 200
        etree.fromstring(c.get("/alerts.atom").content)
        etree.fromstring(c.get("/alerts.cap.xml").content)


@pytest.mark.parametrize("url", ["https://evil.example\\@forecast.weather.gov/x", "https://u:p@forecast.weather.gov/",
                                 "https://forecast.weather.gov:8443/", "https://fórecast.weather.gov/",
                                 "https://forecast.weather.gov./x", "https://x.gov/a\\b"])
def test_alert_url_parser_differentials_rejected(url):
    with pytest.raises(AlertInvalid):
        validate_alert(make_alert(url=url))


def test_one_crashing_source_cannot_abort_cycle(store, monkeypatch):
    good, bad = FakeAdapter("nws", [make_alert()]), FakeAdapter("sso", [make_alert(id="sso:1", source="sso")])
    p = Poller([bad, good], store, ctx_factory)
    real = store.apply_fetch
    monkeypatch.setattr(store, "apply_fetch", lambda src, al, now=None: (_ for _ in ()).throw(RuntimeError("db"))
                        if src == "sso" else real(src, al, now))
    expired = []
    monkeypatch.setattr(store, "expire_due", lambda now=None: expired.append(1) or 0)
    summary = p.run_due(force=True)
    assert summary["ran"] == ["nws"] and "sso" in summary["failed"] and expired == [1]
    p.shutdown()


def test_load_adapters_fails_loud(monkeypatch, caplog, tmp_path):
    import logging
    from fastapi.testclient import TestClient
    from creekwatch.alerts.poller import load_adapters
    from creekwatch.config import Settings
    from creekwatch.main import create_app
    monkeypatch.setenv("CREEKWATCH_ALERT_ADAPTERS", "no_such_module_xyz:ADAPTERS")
    with caplog.at_level(logging.ERROR):
        adapters, err = load_adapters(True)
    assert adapters == [] and "ModuleNotFoundError" in err and "FAILED TO LOAD" in caplog.text
    with TestClient(create_app(Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w",
                                        sites_json=tmp_path / "m.json"))) as c:
        j = c.get("/api/alerts/sources").json()
    assert j["adapters_loaded"] == 0 and "ModuleNotFoundError" in j["load_error"]


def test_schedule_persists_across_poller_instances(store):
    clock = [1_000_000.0]
    src = FakeAdapter("sso", [make_alert(id="sso:1", source="sso")], interval_s=43200)
    p1 = Poller([src], store, ctx_factory, clock=lambda: clock[0])
    p1.run_due(); p1.shutdown()
    assert src.calls == 1
    clock[0] += 600                                   # 10 min later: a NEW process (fresh Poller)
    p2 = Poller([src], store, ctx_factory, clock=lambda: clock[0])
    s2 = p2.run_due(); p2.shutdown()
    assert src.calls == 1 and s2["skipped_not_due"] == ["sso"], "12 h source must not refetch inside its interval"
    clock[0] += 43200
    p3 = Poller([src], store, ctx_factory, clock=lambda: clock[0]); p3.run_due(); p3.shutdown()
    assert src.calls == 2
    boom = FakeAdapter("nws", exc=RuntimeError("down"), interval_s=300)
    q1 = Poller([boom], store, ctx_factory, clock=lambda: clock[0]); q1.run_due(); q1.shutdown()
    q2 = Poller([boom], store, ctx_factory, clock=lambda: clock[0] + 400)   # past interval, inside backoff
    q2.run_due(); q2.shutdown()
    assert boom.calls == 1 and q2.state["nws"].failures == 1, "backoff must survive a process restart"


def test_long_intervals_not_clamped(store):
    p = Poller([FakeAdapter("riverdb", interval_s=86400), FakeAdapter("sso", interval_s=43200)], store, ctx_factory)
    assert p.interval("riverdb") == 86400 and p.interval("sso") == 43200 and p.fetch_timeout_s > 60
    p.shutdown()


def test_claim_outcome_logged_with_pid(tmp_path, caplog):
    import logging
    import os
    a = Poller([FakeAdapter("nws", [make_alert()])], AlertStore(tmp_path / "z.db"), ctx_factory)
    b = Poller([FakeAdapter("nws", [make_alert()])], AlertStore(tmp_path / "z.db"), ctx_factory)
    with caplog.at_level(logging.INFO, logger="creekwatch.alerts"):
        a.run_due(force=True)
        b.store.apply_fetch("nws", [])                                # make it "new" again for b
        b.run_due(force=True)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("push claim")]
    assert lines[0] == f"push claim won id=nws:abc-1 sev=watch kind=new pid={os.getpid()}"
    assert lines[1] == f"push claim lost id=nws:abc-1 sev=watch kind=new pid={os.getpid()}"
    a.shutdown(); b.shutdown()


def test_sources_endpoint_contract_frozen(tmp_path):
    """luna's all-clear logic reads this shape (frozen from fe854b9): additive keys only."""
    from fastapi.testclient import TestClient
    from creekwatch.config import Settings
    from creekwatch.main import create_app
    app = create_app(Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json"))
    p = Poller([FakeAdapter("nws", [make_alert()], interval_s=300)], app.state.alert_store, ctx_factory)
    app.state.alert_poller.adapters, app.state.alert_poller.state = p.adapters, p.state
    p.run_due(force=True)
    with TestClient(app) as c:
        j = c.get("/api/alerts/sources").json()
    assert isinstance(j["sources"], list) and j["sources"][0]["source"] == "nws"
    assert j["sources"][0]["last_ok"].endswith("Z") and "last_error" in j["sources"][0]
    assert j["schedule"]["nws"]["interval_s"] == 300
    p.shutdown()


def test_new_incident_after_long_gap_notifies_again(tmp_path):
    """Same id, same severity: flapping (short gap) stays quiet; a new incident after REARM_AFTER_S
    notifies again (else a deploy test alert would silence the real one forever)."""
    from creekwatch.alerts import store as store_mod
    st = AlertStore(tmp_path / "r.db")
    a = validate_alert(make_alert(id="creekwatch:deer:contamination_alert", source="creekwatch", severity="alert",
                                  expires=None))
    st.apply_fetch("creekwatch", [a], now="2026-10-04T00:00:00Z")
    assert st.claim_push(a["id"], "alert") is True
    st.apply_fetch("creekwatch", [], now="2026-10-04T01:00:00Z")            # cleared
    assert [c.kind for c in st.apply_fetch("creekwatch", [a], now="2026-10-04T02:00:00Z")] == ["new"]
    assert st.claim_push(a["id"], "alert") is False                          # 1 h gap: flapping, quiet
    st.apply_fetch("creekwatch", [], now="2026-10-04T03:00:00Z")            # cleared again
    later = f"2026-10-04T{3 + store_mod.REARM_AFTER_S // 3600:02d}:00:00Z"
    assert [c.kind for c in st.apply_fetch("creekwatch", [a], now=later)] == ["new"]
    assert st.claim_push(a["id"], "alert") is True                           # new incident: announce


def test_inactive_since_migration(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE alerts (id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL, "
                    "status TEXT NOT NULL, severity TEXT NOT NULL, category TEXT NOT NULL, first_seen TEXT NOT NULL, "
                    "updated TEXT NOT NULL, expires TEXT, last_pushed_severity TEXT);")
    c.close()
    AlertStore(db)
    assert "inactive_since" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(alerts)")}
