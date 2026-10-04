import io
from datetime import datetime, timedelta, timezone

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
    assert {"wolf-creek", "deer-creek"} <= ids
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
    assert rep["id"] and rep["creek_id"] == "deer-creek"
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
    lst = client.get("/api/reports", params={"creek_id": "deer-creek"}).json()
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
    assert set(r["flags"]) >= {"dead_fish", "chemical_odor"}
    h = client.get("/api/health", params={"creek_id": "deer-creek"}).json()
    assert 0 <= h["score"] <= 100 and h["band"] == "alert" and h["recent_report_count"] == 1
    assert all(sig.keys() >= {"name", "value", "weight", "explanation", "source"} for sig in h["signals"])
    calm = client.get("/api/health", params={"creek_id": "wolf-creek"}).json()
    assert calm["band"] == "good" and calm["recent_report_count"] == 0
    assert set(client.get("/api/health").json()) >= {"wolf-creek", "deer-creek"}


def test_conditions(client):
    c = client.get("/api/conditions", params={"creek_id": "wolf-creek"}).json()
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
        codes = [c.post("/api/reports", data=REPORT, files={"photo": ("a.jpg", jpg, "image/jpeg")}).status_code
                 for _ in range(3)]
        assert codes == [201, 201, 503]
        assert c.post("/api/reports", data=REPORT).status_code == 201  # text report still accepted
