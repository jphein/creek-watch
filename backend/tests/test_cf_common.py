"""Cloudflare-build common pieces: R2 uploads, READ_ONLY write freeze, cron-triggered /internal/poll."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import REPORT, gps_jpeg
from creekwatch.config import Settings
from creekwatch.main import create_app
from creekwatch.uploads import LocalUploads, R2Uploads, UploadError, make_upload_store


class FakeS3:
    def __init__(self, fail=False):
        self.objects, self.fail = {}, fail

    def put_object(self, **kw):
        if self.fail:
            raise ConnectionError("r2 down")
        self.objects[kw["Key"]] = kw


def _settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json",
                    rate_limit_count=1000, **kw)


# ---- uploads ------------------------------------------------------------------------------------

def test_local_uploads_default(tmp_path):
    s = _settings(tmp_path)
    st = make_upload_store(s)
    assert isinstance(st, LocalUploads)
    st.put("a.jpg", b"x")
    assert (s.uploads_dir / "a.jpg").read_bytes() == b"x"


def test_r2_uploads_put_and_cache(tmp_path):
    fake = FakeS3()
    r2 = R2Uploads("cw-photos", "https://x.r2.cloudflarestorage.com", "KEYID", "SECRETVALUE", tmp_path / "c", client=fake)
    r2.put("p.jpg", b"jpegbytes")
    obj = fake.objects["uploads/p.jpg"]
    assert obj["Bucket"] == "cw-photos" and obj["Body"] == b"jpegbytes" and obj["ContentType"] == "image/jpeg"
    assert (tmp_path / "c" / "p.jpg").read_bytes() == b"jpegbytes"
    assert "SECRETVALUE" not in repr(r2) and "KEYID" not in repr(r2)


def test_r2_failure_returns_503_and_stores_no_report(tmp_path):
    app = create_app(_settings(tmp_path))
    failing = R2Uploads("b", "https://e", "k", "s", tmp_path / "c", client=FakeS3(fail=True))
    with TestClient(app) as c:
        # the route closes over `uploads`; patch the object it holds
        app.state.uploads.put = failing.put
        r = c.post("/api/reports", data=REPORT, files={"photo": ("c.jpg", gps_jpeg((300, 200)), "image/jpeg")})
        assert r.status_code == 503 and "without the photo" in r.text
        assert c.get("/api/reports").json() == []


def test_r2_backend_requires_all_settings(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        make_upload_store(_settings(tmp_path, uploads_backend="r2", r2_bucket="b"))


def test_secrets_not_in_settings_repr(tmp_path):
    s = _settings(tmp_path, r2_access_key_id="AKID-XYZ", r2_secret_access_key="SECRET-XYZ", internal_token="TOKEN-XYZ")
    assert not any(v in repr(s) for v in ("AKID-XYZ", "SECRET-XYZ", "TOKEN-XYZ"))


# ---- READ_ONLY ----------------------------------------------------------------------------------

def test_read_only_freezes_writes_not_reads(tmp_path, monkeypatch):
    from test_alerts_push import body, vapid_private_b64
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", vapid_private_b64())
    with TestClient(create_app(_settings(tmp_path, read_only=True))) as c:
        r = c.post("/api/reports", data=REPORT)
        assert r.status_code == 503 and r.headers["retry-after"] == "120" and "moving to a new server" in r.text
        assert c.post("/api/push/subscriptions", json=body()).status_code == 503
        assert c.request("DELETE", "/api/push/subscriptions", json={"endpoint": body()["subscription"]["endpoint"]}).status_code == 503
        for path in ("/healthz", "/api/creeks", "/api/reports", "/api/alerts", "/api/stats/cleanups"):
            assert c.get(path).status_code == 200, path


# ---- /internal/poll -----------------------------------------------------------------------------

def test_internal_poll_hidden_without_token(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as c:
        assert c.post("/internal/poll").status_code == 404
        assert c.post("/internal/poll", headers={"X-Internal-Token": ""}).status_code == 404


def test_internal_poll_token_and_run(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_ALERT_ADAPTERS", "fake_alert_adapters:ADAPTERS")
    monkeypatch.setenv("FAKE_ADAPTER_LOG", str(tmp_path / "calls.log"))
    sys.path.insert(0, str(Path(__file__).parent))
    with TestClient(create_app(_settings(tmp_path, internal_token="s3cret-token"))) as c:
        assert c.post("/internal/poll", headers={"X-Internal-Token": "wrong"}).status_code == 404
        r = c.post("/internal/poll", headers={"X-Internal-Token": "s3cret-token"})
        assert r.status_code == 200 and sorted(r.json()["ran"]) == ["nws", "sso"]
        assert c.post("/internal/poll", headers={"X-Internal-Token": "s3cret-token"}).json()["ran"] == []  # not due


def test_internal_poll_503_when_adapters_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_ALERT_ADAPTERS", "no_such_mod:X")
    with TestClient(create_app(_settings(tmp_path, internal_token="t"))) as c:
        assert c.post("/internal/poll", headers={"X-Internal-Token": "t"}).status_code == 503
