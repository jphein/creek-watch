"""The deploy lane runs `python -m creekwatch.alerts.poller --once` from a systemd timer: separate
processes. Due/backoff must come from the DB, or the 10 MB SSO file downloads 144x a day."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_cli(tmp_path, *args, fail=False):
    env = dict(os.environ, CREEKWATCH_DATA_DIR=str(tmp_path / "d"), CREEKWATCH_SITES_JSON=str(tmp_path / "none.json"),
               CREEKWATCH_ALERT_ADAPTERS="fake_alert_adapters:ADAPTERS", CREEKWATCH_USE_DATA_PKG="0",
               FAKE_ADAPTER_LOG=str(tmp_path / "calls.log"),
               PYTHONPATH=os.pathsep.join([str(ROOT / "backend"), str(ROOT), str(Path(__file__).parent)]))
    if fail:
        env["FAKE_ADAPTERS_FAIL"] = "1"
    r = subprocess.run([sys.executable, "-m", "creekwatch.alerts.poller", *args], env=env, capture_output=True,
                       text=True, timeout=120)
    return r.returncode, json.loads(r.stdout or "{}"), r.stderr


def calls(tmp_path):
    p = tmp_path / "calls.log"
    return p.read_text().split() if p.exists() else []


def test_second_once_pass_fetches_nothing_not_due(tmp_path):
    code1, s1, _ = run_cli(tmp_path, "--once")
    assert code1 == 0 and sorted(s1["ran"]) == ["nws", "sso"]
    assert sorted(calls(tmp_path)) == ["nws", "sso"]
    code2, s2, _ = run_cli(tmp_path, "--once")           # a separate process, moments later
    assert code2 == 0 and s2["ran"] == [] and sorted(s2["skipped_not_due"]) == ["nws", "sso"]
    assert sorted(calls(tmp_path)) == ["nws", "sso"], "nothing may be refetched before it is due"
    code3, s3, _ = run_cli(tmp_path, "--force")
    assert sorted(s3["ran"]) == ["nws", "sso"] and len(calls(tmp_path)) == 4


def test_exit_nonzero_when_every_source_fails(tmp_path):
    code, s, _ = run_cli(tmp_path, "--once", fail=True)
    assert code == 2 and set(s["failed"]) == {"nws", "sso"} and s["ran"] == []
    code2, s2, _ = run_cli(tmp_path, "--once", fail=True)  # in backoff now: nothing due, not a failure
    assert code2 == 0 and s2["ran"] == [] and s2["failed"] == {}
    assert sorted(calls(tmp_path)) == ["nws", "sso"]


def test_exit_3_when_adapters_fail_to_load(tmp_path):
    env_bad = dict(os.environ, CREEKWATCH_DATA_DIR=str(tmp_path / "d"), CREEKWATCH_ALERT_ADAPTERS="nope_mod:X",
                   CREEKWATCH_USE_DATA_PKG="0", PYTHONPATH=os.pathsep.join([str(ROOT / "backend"), str(ROOT)]))
    r = subprocess.run([sys.executable, "-m", "creekwatch.alerts.poller", "--once"], env=env_bad,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 3 and "adapters not loaded" in r.stdout
