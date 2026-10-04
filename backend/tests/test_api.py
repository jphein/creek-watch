import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from conftest import REPORT, gps_jpeg
from creekwatch.config import Settings
from creekwatch.main import create_app
from creekwatch.photos import process_photo
from fastapi.testclient import TestClient


def test_healthz_and_version(client):
    assert client.get("/healthz").status_code == 200
    v = client.get("/api/version").json()
    assert v["name"] == "creekwatch" and "·" in v["version"] and "uptime" in v


def test_creeks_stub(client):
    creeks = client.get("/api/creeks").json()
    ids = {c["id"] for c in creeks}
    assert {"wolf", "deer"} <= ids
    assert all(st.keys() >= {"id", "name", "lat", "lon"} for c in creeks for st in c["sites"])


def test_creeks_from_sites_json(tmp_path):
    p = tmp_path / "sites.json"
    p.write_text('[{"id":"x-creek","name":"X","town":"T","sites":[{"id":"s1","name":"S","lat":39.2,"lon":-121.0}]}]')
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=p)
    with TestClient(create_app(s)) as c:
        assert [x["id"] for x in c.get("/api/creeks").json()] == ["x-creek"]


def test_post_and_get_report_with_photo(client, settings):
    r = client.post("/api/reports", data=REPORT, files={"photo": ("creek.jpg", gps_jpeg(), "image/jpeg")})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["id"] and rep["creek_id"] == "deer"
    assert rep["site_id"] == "deer-pioneer-park"  # auto-picked nearest site
    assert rep["dead_fish"] is False and rep["flags"] == []
    assert rep["photo_url"].startswith("/uploads/") and rep["photo_url"].endswith(".jpg")

    # served photo: EXIF/GPS gone, downscaled to <=1600, orientation applied (3000x2000 rotated -> portrait)
    body = client.get(rep["photo_url"]).content
    img = Image.open(io.BytesIO(body))
    assert img.format == "JPEG"
    assert not img.getexif() and "exif" not in img.info
    assert img.getexif().get_ifd(0x8825) == {}
    assert b"TestCam" not in body and b"GPS" not in body
    assert max(img.size) <= 1600 and img.size[1] > img.size[0]

    assert client.get(f"/api/reports/{rep['id']}").json() == rep
    lst = client.get("/api/reports", params={"creek_id": "deer"}).json()
    assert [x["id"] for x in lst] == [rep["id"]]
    assert client.get("/api/reports/999999").status_code == 404


def test_reports_newest_first_and_since(client):
    now = datetime.now(timezone.utc)
    ids = []
    for h in (5, 1, 3):
        d = dict(REPORT, observed_at=(now - timedelta(hours=h)).isoformat())
        ids.append(client.post("/api/reports", data=d).json()["id"])
    lst = client.get("/api/reports").json()
    assert [x["id"] for x in lst] == [ids[1], ids[2], ids[0]]
    since = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert [x["id"] for x in client.get("/api/reports", params={"since": since}).json()] == [ids[1]]
    assert len(client.get("/api/reports", params={"limit": 2}).json()) == 2


def test_validation(client):
    assert client.post("/api/reports", data=dict(REPORT, water_color="purple")).status_code == 422
    assert client.post("/api/reports", data=dict(REPORT, creek_id="nope")).status_code == 404
    far = client.post("/api/reports", data=dict(REPORT, lat="37.77", lon="-122.42"))  # San Francisco
    assert far.status_code == 422 and "km" in far.json()["detail"]
    assert client.post("/api/reports", data=dict(REPORT, site_id="wolf-memorial-park")).status_code == 422
    assert client.post("/api/reports", data=dict(REPORT, notes="x" * 1001)).status_code == 422
    assert client.post("/api/reports", data=dict(REPORT, reporter_name="x" * 61)).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.post("/api/reports", data=dict(REPORT, observed_at=future)).status_code == 422
    bad = client.post("/api/reports", data=REPORT, files={"photo": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 415
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, format="GIF")
    assert client.post("/api/reports", data=REPORT, files={"photo": ("x.gif", gif.getvalue(), "image/gif")}).status_code == 415


def test_photo_too_large(tmp_path):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", max_photo_bytes=1000)
    with TestClient(create_app(s)) as c:
        r = c.post("/api/reports", data=REPORT, files={"photo": ("c.jpg", gps_jpeg((200, 200)), "image/jpeg")})
        assert r.status_code == 413


def test_flags_and_health_alert(client):
    r = client.post("/api/reports", data=dict(REPORT, dead_fish="true", odor="chemical")).json()
    assert set(r["flags"]) >= {"dead_fish_alert", "chemical_odor_alert"}
    h = client.get("/api/health", params={"creek_id": "deer"}).json()
    assert 0 <= h["score"] <= 100 and h["band"] == "alert" and h["recent_report_count"] == 1
    assert all(sig.keys() >= {"name", "value", "weight", "explanation", "source"} for sig in h["signals"])
    calm = client.get("/api/health", params={"creek_id": "wolf"}).json()
    assert calm["band"] == "good" and calm["recent_report_count"] == 0
    assert set(client.get("/api/health").json()) >= {"wolf", "deer"}


def test_conditions(client):
    c = client.get("/api/conditions", params={"creek_id": "wolf"}).json()
    assert {"gauge", "weather", "fetched_at"} <= c.keys()
    assert client.get("/api/conditions", params={"creek_id": "nope"}).status_code == 404


def test_rate_limit(tmp_path):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", rate_limit_count=2)
    with TestClient(create_app(s)) as c:
        codes = [c.post("/api/reports", data=REPORT).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_png_with_alpha_and_static_web(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>Creek Watch</title>")
    s = Settings(data_dir=tmp_path / "d", web_dir=web, sites_json=tmp_path / "m.json")
    buf = io.BytesIO()
    Image.new("RGBA", (50, 40), (0, 0, 255, 128)).save(buf, format="PNG")
    with TestClient(create_app(s)) as c:
        assert "Creek Watch" in c.get("/").text
        r = c.post("/api/reports", data=REPORT, files={"photo": ("p.png", buf.getvalue(), "image/png")})
        assert r.status_code == 201 and c.get("/api/creeks").status_code == 200


def test_process_photo_strips_exif_unit():
    out = process_photo(gps_jpeg((800, 600)))
    img = Image.open(io.BytesIO(out))
    assert not img.getexif() and img.size == (600, 800)


def test_public_coords_are_coarsened(client):
    r = client.post("/api/reports", data=dict(REPORT, lat="39.263123456", lon="-121.022987654")).json()
    assert (r["lat"], r["lon"]) == (39.263, -121.023)
    assert client.get(f"/api/reports/{r['id']}").json()["lat"] == 39.263


def test_rate_limiter_bounded_keys(monkeypatch):
    from creekwatch import ratelimit

    monkeypatch.setattr(ratelimit, "MAX_KEYS", 50)
    rl = ratelimit.RateLimiter(count=5, window_s=600)
    assert all(rl.check(f"10.0.{i // 256}.{i % 256}") is None for i in range(500))  # rotating IPs
    assert len(rl._hits) <= 50


def test_photo_budget_cannot_block_reports(tmp_path):
    """DoS guard: junk requests don't drain the global budget, and an exhausted budget only refuses photos."""
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json",
                 rate_limit_count=1000, photo_budget=2)
    jpg = gps_jpeg((100, 100))
    with TestClient(create_app(s)) as c:
        for _ in range(20):  # flood of invalid posts with photos
            assert c.post("/api/reports", data=dict(REPORT, water_color="x"),
                          files={"photo": ("a.jpg", jpg, "image/jpeg")}).status_code == 422
        for _ in range(20):  # valid fields, garbage photo: must not spend the photo budget
            assert c.post("/api/reports", data=REPORT,
                          files={"photo": ("a.jpg", b"garbage", "image/jpeg")}).status_code == 415
        codes = [c.post("/api/reports", data=REPORT, files={"photo": ("a.jpg", jpg, "image/jpeg")}).status_code
                 for _ in range(3)]
        assert codes == [201, 201, 503]
        assert c.post("/api/reports", data=REPORT).status_code == 201  # text report still accepted


def test_report_budget_bounds_valid_flood_only(tmp_path):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json",
                 rate_limit_count=1000, report_budget=3)
    with TestClient(create_app(s)) as c:
        for _ in range(10):  # junk never counts against the global report budget
            assert c.post("/api/reports", data=dict(REPORT, algae="x")).status_code == 422
            assert c.post("/api/reports", data=REPORT,
                          files={"photo": ("a.jpg", b"garbage", "image/jpeg")}).status_code == 415
        assert [c.post("/api/reports", data=REPORT).status_code for _ in range(4)] == [201, 201, 201, 503]


def test_client_ip_trust():
    from starlette.requests import Request

    from creekwatch.main import make_client_ip

    ip = make_client_ip("127.0.0.0/8,172.16.0.0/12")

    def req(peer, **h):
        hdrs = [(k.replace("_", "-").encode(), v.encode()) for k, v in h.items()]
        return Request({"type": "http", "client": (peer, 1234), "headers": hdrs})

    assert ip(req("172.17.0.1", cf_connecting_ip="203.0.113.7", x_forwarded_for="127.0.0.1")) == "203.0.113.7"
    assert ip(req("172.17.0.1", x_forwarded_for="198.51.100.2, 127.0.0.1")) == "198.51.100.2"
    assert ip(req("172.17.0.1", cf_connecting_ip="not-an-ip")) == "172.17.0.1"
    # untrusted peer can't spoof
    assert ip(req("203.0.113.99", cf_connecting_ip="1.2.3.4", x_forwarded_for="5.6.7.8")) == "203.0.113.99"


# ---- cleanups: trash_removed / trash_bags (JP request) ------------------------------------------

def test_trash_removed_roundtrip_and_defaults(client):
    r = client.post("/api/reports", data=dict(REPORT, trash="lots", trash_removed="true", trash_bags="3"))
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["trash_removed"] is True and rep["trash_bags"] == 3
    assert client.get(f"/api/reports/{rep['id']}").json()["trash_bags"] == 3
    plain = client.post("/api/reports", data=REPORT).json()
    assert plain["trash_removed"] is False and plain["trash_bags"] is None
    empty_bags = client.post("/api/reports", data=dict(REPORT, trash_removed="true", trash_bags=""))
    assert empty_bags.status_code == 201 and empty_bags.json()["trash_bags"] is None


@pytest.mark.parametrize("extra,msg", [
    ({"trash": "none", "trash_removed": "true"}, "trash_removed"),
    ({"trash_bags": "2"}, "only for reports where you removed"),
    ({"trash_removed": "true", "trash_bags": "21"}, "0 to 20"),
    ({"trash_removed": "true", "trash_bags": "-1"}, "0 to 20"),
    ({"trash_removed": "true", "trash_bags": "two"}, "0 to 20"),
    ({"trash_removed": "true", "trash_bags": "2.5"}, "0 to 20"),
    ({"trash_removed": "true", "trash_bags": "\u00b2"}, "0 to 20"),     # superscript two: isdigit() True, int() raises
    ({"trash_removed": "true", "trash_bags": "\u0663"}, "0 to 20"),     # Arabic-Indic three: int() would return 3
    ({"trash_removed": "true", "trash_bags": "007"}, "0 to 20"),
])
def test_trash_removed_validation(client, extra, msg):
    r = client.post("/api/reports", data=dict(REPORT, **extra))
    assert r.status_code == 422 and msg in r.text


def test_cleanup_stats(client):
    assert client.get("/api/stats/cleanups").json() == {"cleanups": 0, "bags": 0, "since": None}
    from datetime import datetime, timedelta, timezone
    t0 = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.post("/api/reports", data=dict(REPORT, trash="some", trash_removed="true", trash_bags="2", observed_at=t0))
    client.post("/api/reports", data=dict(REPORT, trash="lots", trash_removed="true"))              # bags unknown
    client.post("/api/reports", data=dict(REPORT, trash="lots"))                                     # seen, not removed
    wolf = client.post("/api/reports", data=dict(REPORT, creek_id="wolf", lat="39.2253", lon="-121.0607",
                                                 trash="some", trash_removed="true", trash_bags="5"))
    assert wolf.status_code == 201, wolf.text
    allc = client.get("/api/stats/cleanups").json()
    assert allc == {"cleanups": 3, "bags": 7, "since": t0}
    assert set(allc) == {"cleanups", "bags", "since"}              # aggregates only, no personal data
    assert client.get("/api/stats/cleanups", params={"creek_id": "wolf"}).json()["cleanups"] == 1
    assert client.get("/api/stats/cleanups", params={"creek_id": "deer"}).json() == {"cleanups": 2, "bags": 2, "since": t0}
    assert client.get("/api/stats/cleanups", params={"creek_id": "mars"}).status_code == 404


def test_reports_migration_adds_cleanup_columns(tmp_path):
    import sqlite3
    from creekwatch import db
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("""CREATE TABLE reports (id INTEGER PRIMARY KEY AUTOINCREMENT, creek_id TEXT NOT NULL,
        site_id TEXT, lat REAL NOT NULL, lon REAL NOT NULL, observed_at TEXT NOT NULL, created_at TEXT NOT NULL,
        water_color TEXT NOT NULL, algae TEXT NOT NULL, trash TEXT NOT NULL, flow TEXT NOT NULL, odor TEXT NOT NULL,
        dead_fish INTEGER NOT NULL DEFAULT 0, wildlife_seen TEXT, notes TEXT, reporter_name TEXT, photo_file TEXT,
        flags TEXT NOT NULL DEFAULT '[]');
        INSERT INTO reports (creek_id, lat, lon, observed_at, created_at, water_color, algae, trash, flow, odor)
        VALUES ('deer', 39.26, -121.02, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'clear','none','some','normal','none');""")
    c.commit(); c.close()
    db.init(p); db.init(p)                                         # idempotent
    row = sqlite3.connect(p).execute("SELECT trash_removed, trash_bags FROM reports").fetchone()
    assert row == (0, None)


# ---- conditions: startup warm-up + single-flight (cold first visit after every redeploy) -------

def test_conditions_single_flight():
    import threading
    import time as _t
    from creekwatch.data_iface import DataLayer
    calls = []
    dl = DataLayer(600, use_data_package=False)
    dl._get_conditions = lambda cid: calls.append(cid) or _t.sleep(0.5) or {"gauge": None, "weather": None}
    ths = [threading.Thread(target=dl.conditions, args=("deer",)) for _ in range(5)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert calls == ["deer"], "concurrent callers must share one upstream fetch"


def _counting_app(tmp_path, warm: bool):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", warm_conditions=warm)
    app = create_app(s)
    calls = []
    app.state.data._get_conditions = lambda cid: calls.append(cid) or {"gauge": None, "weather": None}
    return app, calls


def test_conditions_warmed_at_startup(tmp_path):
    import time as _t
    app, calls = _counting_app(tmp_path, warm=True)
    with TestClient(app) as c:
        deadline = _t.monotonic() + 5
        while sorted(calls) != ["deer", "wolf"] and _t.monotonic() < deadline:
            _t.sleep(0.02)
        assert sorted(calls) == ["deer", "wolf"], "every creek prefetched with no request"
        c.get("/api/conditions", params={"creek_id": "deer"})
        assert sorted(calls) == ["deer", "wolf"], "the first visitor hits the warm cache"


def test_conditions_warmup_can_be_disabled(tmp_path):
    import time as _t
    app, calls = _counting_app(tmp_path, warm=False)
    with TestClient(app) as c:
        _t.sleep(0.3)
        assert calls == []
        c.get("/api/conditions", params={"creek_id": "deer"})
        assert calls == ["deer"]


# ---- cache_ttl_hint_s from data.ingest (RiverDB cap answered from the snapshot) -----------------

def _dl_with(results):
    from creekwatch.data_iface import DataLayer
    dl = DataLayer(600, use_data_package=False)
    calls = []

    def gc(cid):
        calls.append(cid)
        return dict(results[min(len(calls), len(results)) - 1])
    dl._get_conditions = gc
    return dl, calls


def test_capped_response_cached_briefly_and_hint_stripped(monkeypatch):
    import time as _t
    from creekwatch import data_iface
    clock = [1000.0]
    monkeypatch.setattr(data_iface.time, "monotonic", lambda: clock[0])
    capped = {"gauge": None, "water_quality": {"capped": True, "stations": []}, "cache_ttl_hint_s": 30}
    full = {"gauge": None, "water_quality": {"stations": [{"live": True}]}}
    dl, calls = _dl_with([capped, full])
    r1 = dl.conditions("deer")
    assert "cache_ttl_hint_s" not in r1 and r1["water_quality"]["capped"] is True   # internal hint stripped
    clock[0] += 29; dl.conditions("deer"); assert len(calls) == 1                  # within the hint
    clock[0] += 2;  r3 = dl.conditions("deer"); assert len(calls) == 2              # hint expired: refetch
    assert "capped" not in r3["water_quality"]
    clock[0] += 599; dl.conditions("deer"); assert len(calls) == 2                  # normal 600 s again


@pytest.mark.parametrize("hint,expect", [(None, 600), (0, 600), (-5, 600), ("30", 600), (True, 600),
                                         (1, 5), (30, 30), (30.5, 30.5), (10_000, 600)])
def test_ttl_hint_clamped(hint, expect):
    from creekwatch.data_iface import DataLayer
    dl = DataLayer(600, use_data_package=False)
    res = {"gauge": None} if hint is None else {"gauge": None, "cache_ttl_hint_s": hint}
    assert dl._ttl_for(res) == expect


def test_failed_conditions_negative_cached_60s(monkeypatch):
    from creekwatch import data_iface
    from creekwatch.data_iface import DataLayer
    clock = [1000.0]
    monkeypatch.setattr(data_iface.time, "monotonic", lambda: clock[0])
    dl = DataLayer(600, use_data_package=False)
    calls = []

    def boom(cid):
        calls.append(cid)
        raise RuntimeError("upstream down")
    dl._get_conditions = boom
    assert "error" in dl.conditions("deer")
    clock[0] += 59; dl.conditions("deer"); assert len(calls) == 1
    clock[0] += 2;  dl.conditions("deer"); assert len(calls) == 2


# ---- water_color "orange" (possible mine drainage) + reports away from named sites --------------

def test_orange_water_accepted_and_returned(client):
    r = client.post("/api/reports", data=dict(REPORT, water_color="orange"))
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["water_color"] == "orange"
    assert client.get(f"/api/reports/{rep['id']}").json()["water_color"] == "orange"
    assert [x["water_color"] for x in client.get("/api/reports").json()] == ["orange"]
    assert client.post("/api/reports", data=dict(REPORT, water_color="rust")).status_code == 422


def test_report_on_a_tributary_away_from_named_sites(client):
    """site_id is optional: a point >1.5 km from every named site (e.g. a small tributary) is accepted
    with site_id null, as long as it is within 25 km of the creek's sites/line."""
    from creekwatch.main import haversine_km
    creeks = {c["id"]: c for c in client.get("/api/creeks").json()}
    lat, lon = 39.2950, -121.0600                                   # ~4 km from every Deer Creek stub site
    assert min(haversine_km(lat, lon, s["lat"], s["lon"]) for s in creeks["deer"]["sites"]) > 1.5
    r = client.post("/api/reports", data=dict(REPORT, lat=str(lat), lon=str(lon), water_color="orange"))
    assert r.status_code == 201, r.text
    assert r.json()["site_id"] is None
    far = client.post("/api/reports", data=dict(REPORT, lat="39.55", lon="-121.06"))   # ~32 km north
    assert far.status_code == 422 and "km" in far.json()["detail"]


def test_side_stream_skips_site_autopick(client):
    near_site = dict(REPORT)          # REPORT's point is ~0.03 km from deer-pioneer-park
    assert client.post("/api/reports", data=near_site).json()["site_id"] == "deer-pioneer-park"   # default
    r = client.post("/api/reports", data=dict(near_site, location_kind="side_stream", water_color="orange"))
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["site_id"] is None and rep["location_kind"] == "side_stream"
    assert client.get(f"/api/reports/{rep['id']}").json()["location_kind"] == "side_stream"
    assert client.post("/api/reports", data=dict(near_site, location_kind="")).json()["location_kind"] is None


@pytest.mark.parametrize("extra,msg", [
    ({"location_kind": "creek"}, "location_kind must be"),
    ({"location_kind": "side_stream", "site_id": "deer-pioneer-park"}, "can't also name a site"),
])
def test_location_kind_validation(client, extra, msg):
    r = client.post("/api/reports", data=dict(REPORT, **extra))
    assert r.status_code == 422 and msg in r.text


def test_reports_migration_adds_location_kind(tmp_path):
    import sqlite3
    from creekwatch import db
    p = tmp_path / "old3.db"
    db.init(p)
    c = sqlite3.connect(p); c.execute("ALTER TABLE reports DROP COLUMN location_kind"); c.commit(); c.close()
    db.init(p)
    assert "location_kind" in {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(reports)")}


# --- CREEKWATCH_CLIENT_IP_HEADER: one trusted header only (non-Cloudflare front proxy, e.g. kamal-proxy) ---

def _ipreq(peer, **h):
    from starlette.requests import Request
    hdrs = [(k.replace("_", "-").encode(), v.encode()) for k, v in h.items()]
    return Request({"type": "http", "client": (peer, 1234), "headers": hdrs})


def test_client_ip_header_xff_ignores_forged_cf():
    from creekwatch.main import make_client_ip
    ip = make_client_ip("127.0.0.0/8,172.16.0.0/12", "x-forwarded-for")
    # kamal-proxy (172.18.x) wrote the real client as the last XFF hop; the client forged CF-Connecting-IP,
    # Fly-Client-IP and an XFF prefix.
    r = _ipreq("172.18.0.2", cf_connecting_ip="9.9.9.9", fly_client_ip="8.8.8.8",
               x_forwarded_for="6.6.6.6, 203.0.113.7")
    assert ip(r) == "203.0.113.7"
    assert ip(_ipreq("172.18.0.2", x_forwarded_for="203.0.113.7")) == "203.0.113.7"
    # Two XFF header lines (client's first, proxy's appended as a separate line) → the proxy's last hop.
    from starlette.requests import Request
    two = Request({"type": "http", "client": ("172.18.0.2", 1), "headers": [
        (b"x-forwarded-for", b"6.6.6.6"), (b"x-forwarded-for", b"203.0.113.9")]})
    assert ip(two) == "203.0.113.9"
    assert ip(_ipreq("172.18.0.2", x_forwarded_for="6.6.6.6, 203.0.113.7,")) == "172.18.0.2"  # trailing comma
    # An invalid last hop → the peer; never the client-supplied prefix, never another header.
    assert ip(_ipreq("172.18.0.2", cf_connecting_ip="9.9.9.9", x_forwarded_for="6.6.6.6, junk")) == "172.18.0.2"
    # Only the forged header, no XFF → the peer, never the forgery.
    assert ip(_ipreq("172.18.0.2", cf_connecting_ip="9.9.9.9")) == "172.18.0.2"
    # Untrusted peer → the peer, whatever it sends.
    assert ip(_ipreq("198.51.100.4", x_forwarded_for="203.0.113.7")) == "198.51.100.4"


def test_client_ip_header_only_xff_and_default():
    from creekwatch.main import make_client_ip
    for bad in ("cf-connecting-ip", "x-real-ip", "fly-client-ip", "X-Forwarded-For", ""):
        with pytest.raises(ValueError, match="CREEKWATCH_CLIENT_IP_HEADER"):
            make_client_ip("172.16.0.0/12", bad)
    # Default (unset) is unchanged: CF-Connecting-IP first, then the FIRST XFF hop.
    d = make_client_ip("172.16.0.0/12")
    assert d(_ipreq("172.18.0.2", cf_connecting_ip="9.9.9.9", x_forwarded_for="203.0.113.7")) == "9.9.9.9"
    assert d(_ipreq("172.18.0.2", x_forwarded_for="203.0.113.7, 10.0.0.1")) == "203.0.113.7"


def test_client_ip_header_invalid_fails_at_startup(tmp_path, monkeypatch):
    from creekwatch.config import Settings
    from creekwatch.main import create_app
    monkeypatch.setenv("CREEKWATCH_CLIENT_IP_HEADER", "x-forwarded-fro")
    with pytest.raises(ValueError, match="CREEKWATCH_CLIENT_IP_HEADER"):
        create_app(Settings(data_dir=tmp_path))
    monkeypatch.setenv("CREEKWATCH_CLIENT_IP_HEADER", " X-Forwarded-For ")
    assert Settings(data_dir=tmp_path).client_ip_header == "x-forwarded-for"
    monkeypatch.setenv("CREEKWATCH_CLIENT_IP_HEADER", "")
    assert Settings(data_dir=tmp_path).client_ip_header is None


def test_client_ip_header_wired_into_rate_limit(tmp_path, monkeypatch):
    """Through the app: behind a trusted proxy, rotating a forged CF-Connecting-IP can't escape the limit."""
    monkeypatch.setenv("CREEKWATCH_CLIENT_IP_HEADER", "x-forwarded-for")
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", rate_limit_count=2)
    with TestClient(create_app(s), client=("172.18.0.2", 4321)) as c:
        codes = [c.post("/api/reports", data=REPORT, headers={
            "cf-connecting-ip": f"9.9.9.{i}", "x-forwarded-for": f"6.6.6.{i}, 203.0.113.7"}).status_code
            for i in range(3)]
        assert codes == [201, 201, 429]
        # A different real client (XFF) gets its own bucket.
        assert c.post("/api/reports", data=REPORT, headers={"x-forwarded-for": "203.0.113.8"}).status_code == 201
