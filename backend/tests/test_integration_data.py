"""Runs the API against the data lane's real `data` package (sites/score). Skips pieces not merged yet.
Network-dependent ingest is replaced with a canned conditions dict, so this stays offline."""

import importlib.util

import pytest
from fastapi.testclient import TestClient

from conftest import REPORT
from creekwatch.config import REPO_ROOT, Settings
from creekwatch.main import create_app

HAS_SITES = importlib.util.find_spec("data.sites") is not None
HAS_SCORE = importlib.util.find_spec("data.score") is not None


@pytest.fixture
def real_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_USE_DATA_PKG", "1")
    if importlib.util.find_spec("data.ingest") is not None:
        from data import ingest

        monkeypatch.setattr(ingest, "get_conditions", lambda creek_id, **kw: {
            "gauge": None, "weather": {"temp_f": 80, "precip_24h_in": 1.2, "forecast_short": "Rain",
                                        "observed_at": "2026-10-04T00:00:00Z", "source_url": "https://example"},
            "fetched_at": "2026-10-04T00:00:00Z"})
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=REPO_ROOT / "data" / "sites.json",
                 rate_limit_count=1000)
    with TestClient(create_app(s)) as c:
        yield c


@pytest.mark.skipif(not HAS_SITES, reason="data.sites not merged")
def test_real_creeks_have_lines(real_client):
    creeks = {c["id"]: c for c in real_client.get("/api/creeks").json()}
    assert set(creeks) >= {"wolf", "deer"}
    assert all(c["geojson_line"]["features"] for c in creeks.values())


@pytest.mark.skipif(not (HAS_SITES and HAS_SCORE), reason="data.score not merged")
def test_real_score_and_flags(real_client):
    site = real_client.get("/api/creeks").json()[1]["sites"][0]
    creek_id = real_client.get("/api/creeks").json()[1]["id"]
    r = real_client.post("/api/reports", data=dict(REPORT, creek_id=creek_id, lat=str(site["lat"]),
                                                   lon=str(site["lon"]), dead_fish="true", odor="sewage"))
    assert r.status_code == 201, r.text
    assert "dead_fish_alert" in r.json()["flags"]
    h = real_client.get("/api/health", params={"creek_id": creek_id}).json()
    assert h["band"] == "alert" and "stub" not in h
    assert "warnings" in h
