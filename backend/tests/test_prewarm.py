"""Cold start: startup prewarms the data package in the background; /healthz stays instant."""
import importlib.util
import threading
import time

import pytest
from fastapi.testclient import TestClient

from creekwatch.config import REPO_ROOT, Settings
from creekwatch.main import create_app

pytestmark = pytest.mark.skipif(importlib.util.find_spec("data.ingest") is None, reason="needs data package")


def _settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w",
                    sites_json=REPO_ROOT / "data" / "sites.json", **kw)


def test_startup_does_not_block_and_first_visit_is_fast(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_USE_DATA_PKG", "1")
    from data import ingest
    warm, calls, lock = {}, [], threading.Lock()

    def fake_conditions(creek_id, **kw):      # cold first call per creek, warm afterwards
        with lock:
            calls.append(creek_id)
            cold = creek_id not in warm
        if cold:
            time.sleep(1.0)
            with lock:
                warm[creek_id] = {"gauge": None, "weather": None, "fetched_at": "2026-10-04T00:00:00Z"}
        return warm[creek_id]
    monkeypatch.setattr(ingest, "get_conditions", fake_conditions)

    app = create_app(_settings(tmp_path))
    t0 = time.monotonic()
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert time.monotonic() - t0 < 0.8                # startup + healthz not delayed by warm-up
        deadline = time.monotonic() + 5
        while len(warm) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert set(warm) == {"wolf", "deer"}              # prewarm covered every creek
        t1 = time.monotonic()
        r = c.get("/api/conditions?creek_id=wolf")
        assert r.status_code == 200 and time.monotonic() - t1 < 0.3   # first VISITOR is fast


def test_prewarm_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_USE_DATA_PKG", "1")
    from data import ingest
    called = []
    monkeypatch.setattr(ingest, "prewarm", lambda ids: called.append(ids))
    with TestClient(create_app(_settings(tmp_path, prewarm_enabled=False))) as c:
        c.get("/healthz")
    assert called == []
    with TestClient(create_app(_settings(tmp_path))) as c:
        c.get("/healthz")
    assert called and set(called[0]) == {"wolf", "deer"}
