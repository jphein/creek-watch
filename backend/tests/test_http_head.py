"""HEAD answers like GET without a body (uptime bots, link checkers, curl -I)."""

import pytest
from conftest import REPORT, gps_jpeg
from creekwatch.config import Settings
from creekwatch.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def c(tmp_path):
    web = tmp_path / "w"
    (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>cw</title>")
    (web / "js" / "app.js").write_text("console.log(1)")
    s = Settings(data_dir=tmp_path / "d", web_dir=web, sites_json=tmp_path / "m.json", rate_limit_count=1000)
    with TestClient(create_app(s)) as client:
        yield client


@pytest.mark.parametrize("path", ["/healthz", "/api/version", "/api/creeks", "/api/reports", "/api/meta",
                                  "/api/stats/cleanups", "/alerts.cap.xml", "/", "/js/app.js"])
def test_head_matches_get(c, path):
    g, h = c.get(path), c.head(path)
    assert g.status_code == 200, path
    assert h.status_code == 200, path
    assert h.content == b"", path
    assert h.headers.get("content-type") == g.headers.get("content-type"), path
    if "content-length" in g.headers:
        assert h.headers["content-length"] == g.headers["content-length"], path


def test_head_on_uploaded_photo_and_errors(c):
    rep = c.post("/api/reports", data=REPORT, files={"photo": ("p.jpg", gps_jpeg(), "image/jpeg")}).json()
    h = c.head(rep["photo_url"])
    assert h.status_code == 200 and h.content == b"" and int(h.headers["content-length"]) > 1000
    assert c.head(f"/api/reports/{rep['id']}").status_code == 200
    assert c.head("/api/reports/does-not-exist").status_code == c.get("/api/reports/does-not-exist").status_code
    assert c.head("/nope").status_code == 404
    assert c.head("/uploads/none.jpg").status_code == 404


def test_head_does_not_unlock_other_methods(c):
    # HEAD is only ever run as GET: a POST/DELETE-only route answers HEAD exactly as it answers GET, never 2xx.
    for path in ("/api/push/subscriptions", "/api/alerts/poll"):
        g, h = c.get(path).status_code, c.head(path).status_code
        assert h == g and h >= 400, (path, g, h)
    # GET/POST themselves are untouched.
    assert c.get("/healthz").content and c.post("/api/reports", data=REPORT).status_code == 201


def _raw(app, method):
    """Drive an ASGI app directly and record what it sends (httpx's TestClient discards HEAD bodies itself)."""
    import anyio
    sent, seen = [], {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    async def inner(scope, recv, snd):
        seen["method"] = scope["method"]
        await snd({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"10")]})
        await snd({"type": "http.response.body", "body": b"hello", "more_body": True})
        await snd({"type": "http.response.body", "body": b"world", "more_body": False})

    scope = {"type": "http", "method": method, "path": "/x", "headers": []}
    anyio.run(app(inner), scope, receive, send)
    return seen["method"], sent


def test_head_body_dropped_at_asgi_level():
    from creekwatch.http_head import HeadAsGetMiddleware
    method, sent = _raw(lambda inner: HeadAsGetMiddleware(inner), "HEAD")
    assert method == "GET"
    assert sent[0]["status"] == 200 and (b"content-length", b"10") in sent[0]["headers"]
    bodies = [m for m in sent if m["type"] == "http.response.body"]
    assert bodies == [{"type": "http.response.body", "body": b"", "more_body": False}]
    # GET passes through untouched, both chunks.
    method, sent = _raw(lambda inner: HeadAsGetMiddleware(inner), "GET")
    assert method == "GET" and b"".join(m.get("body", b"") for m in sent[1:]) == b"helloworld"
