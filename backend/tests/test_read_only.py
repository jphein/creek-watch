"""CREEKWATCH_READ_ONLY: the cutover write freeze."""
from fastapi.testclient import TestClient

from conftest import REPORT
from creekwatch.config import Settings
from creekwatch.main import create_app


def test_read_only_freezes_writes_not_reads(tmp_path, monkeypatch):
    from test_alerts_push import body, vapid_private_b64
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", vapid_private_b64())
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", read_only=True)
    with TestClient(create_app(s)) as c:
        r = c.post("/api/reports", data=REPORT)
        assert r.status_code == 503 and r.headers["retry-after"] == "120" and "moving to a new server" in r.text
        assert c.post("/api/push/subscriptions", json=body()).status_code == 503
        ep = body()["subscription"]["endpoint"]
        assert c.request("DELETE", "/api/push/subscriptions", json={"endpoint": ep}).status_code == 503
        for path in ("/healthz", "/api/creeks", "/api/reports", "/api/alerts", "/api/stats/cleanups"):
            assert c.get(path).status_code == 200, path
        assert c.get("/api/reports").json() == []


def test_writes_work_when_not_read_only(tmp_path):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json")
    with TestClient(create_app(s)) as c:
        assert c.post("/api/reports", data=REPORT).status_code == 201
