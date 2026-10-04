"""CREEKWATCH_CACHE_CONTROL: the app mirrors the homelab Caddy Cache-Control policy (AWS has no Caddy)."""

import pytest
from conftest import REPORT, gps_jpeg
from creekwatch.config import Settings
from creekwatch.main import create_app
from fastapi.testclient import TestClient

UPLOADS = "private, max-age=86400, no-transform"
DEFAULT = "private, no-cache, no-transform"


def _app(tmp_path, monkeypatch, on: bool | None):
    if on is None:
        monkeypatch.delenv("CREEKWATCH_CACHE_CONTROL", raising=False)
    else:
        monkeypatch.setenv("CREEKWATCH_CACHE_CONTROL", "1" if on else "0")
    web = tmp_path / "w"
    (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>cw</title>")
    (web / "js" / "app.js").write_text("console.log(1)")
    (web / "sw.js").write_text("self.x=1")
    s = Settings(data_dir=tmp_path / "d", web_dir=web, sites_json=tmp_path / "m.json", rate_limit_count=1000)
    return TestClient(create_app(s))


def _cc(r):
    return r.headers.get_list("cache-control")


def test_policies_when_on(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, True) as c:
        rep = c.post("/api/reports", data=REPORT, files={"photo": ("p.jpg", gps_jpeg(), "image/jpeg")})
        assert rep.status_code == 201 and _cc(rep) == [DEFAULT]
        photo = c.get(rep.json()["photo_url"])
        assert photo.status_code == 200 and _cc(photo) == [UPLOADS]
        for path in ("/", "/index.html", "/js/app.js", "/sw.js", "/healthz", "/api/creeks", "/nope-404"):
            assert _cc(c.get(path)) == [DEFAULT], path
        assert _cc(c.get("/uploads/missing.jpg")) == [UPLOADS]  # 404 under /uploads: still the photo policy
        assert _cc(c.post("/api/reports", data={})) == [DEFAULT]  # error responses too
        # A route's own Cache-Control is kept, never overridden or duplicated.
        assert _cc(c.get("/alerts.cap.xml")) == ["public, max-age=120"]
        # "/uploadsX" isn't the uploads tree.
        assert _cc(c.get("/uploadsX")) == [DEFAULT]


@pytest.mark.parametrize("on", [None, False])
def test_off_by_default_is_unchanged(tmp_path, monkeypatch, on):
    """Homelab: Caddy sets Cache-Control and does not replace an upstream one, so the app must not add one."""
    with _app(tmp_path, monkeypatch, on) as c:
        assert _cc(c.get("/js/app.js")) == []
        assert _cc(c.get("/healthz")) == []
        assert _cc(c.get("/alerts.cap.xml")) == ["public, max-age=120"]
