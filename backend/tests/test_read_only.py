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


def test_cli_poller_skips_when_read_only(tmp_path):
    """`poller --once` (and --force) must not fetch/claim/push during the cutover copy."""
    import json, os, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    log = tmp_path / "calls.log"
    env = dict(os.environ, CREEKWATCH_DATA_DIR=str(tmp_path / "d"), CREEKWATCH_SITES_JSON=str(tmp_path / "none.json"),
               CREEKWATCH_ALERT_ADAPTERS="fake_alert_adapters:ADAPTERS", CREEKWATCH_USE_DATA_PKG="0",
               FAKE_ADAPTER_LOG=str(log), CREEKWATCH_READ_ONLY="1",
               PYTHONPATH=os.pathsep.join([str(root / "backend"), str(root), str(Path(__file__).parent)]))
    for flag in ("--once", "--force"):
        r = subprocess.run([sys.executable, "-m", "creekwatch.alerts.poller", flag], env=env, capture_output=True,
                           text=True, timeout=120)
        assert r.returncode == 0 and json.loads(r.stdout) == {"skipped": "read_only"}, (flag, r.stdout, r.stderr)
    assert not log.exists(), "no adapter may run while read-only"


def test_in_app_poller_paused_when_read_only(tmp_path):
    import asyncio
    from creekwatch.main import _poll_forever

    class P:
        calls = 0

        def run_due(self):
            P.calls += 1

    async def run(read_only):
        t = asyncio.create_task(_poll_forever(P(), 0.01, lambda: read_only))
        await asyncio.sleep(0.1)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    asyncio.run(run(True))
    assert P.calls == 0, "frozen: no poll cycles"
    asyncio.run(run(False))
    assert P.calls > 0
