import base64
import logging
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from alert_fixtures import make_alert
from creekwatch.alerts import push as push_mod
from creekwatch.alerts.model import validate_alert
from creekwatch.alerts.push import (PushService, SubscriptionInvalid, VapidKeys, in_quiet_hours, matches,
                                    validate_endpoint, validate_subscription)
from creekwatch.config import Settings
from creekwatch.main import create_app


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def vapid_private_b64() -> str:
    k = ec.generate_private_key(ec.SECP256R1())
    return b64u(k.private_numbers().private_value.to_bytes(32, "big"))


def sub_keys():
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": b64u(pub), "auth": b64u(b"0123456789abcdef")}


def body(endpoint="https://fcm.googleapis.com/fcm/send/abc123", **kw):
    return {"subscription": {"endpoint": endpoint, "keys": sub_keys()}, **kw}


# ---- SSRF allowlist ----------------------------------------------------------------------------

@pytest.mark.parametrize("ok", [
    "https://fcm.googleapis.com/fcm/send/xyz", "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
    "https://web.push.apple.com/QAbc", "https://wns2-par02p.notify.windows.com/w/?token=AAA",
    "https://FCM.GOOGLEAPIS.COM/fcm/send/x", "https://fcm.googleapis.com:443/x",
])
def test_endpoint_allowed(ok):
    assert validate_endpoint(ok) == ok


@pytest.mark.parametrize("bad", [
    "http://fcm.googleapis.com/fcm/send/x",            # not https
    "https://fcm.googleapis.com@169.254.169.254/x",    # userinfo trick
    "https://user:pw@fcm.googleapis.com/x",
    "https://fcm.googleapis.com.evil.example/x",       # suffix trick
    "https://evil.example/fcm.googleapis.com",
    "https://push.apple.com/x",                        # bare suffix, no subdomain
    "https://evilpush.apple.com.attacker.net/x",
    "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.6.1/x",
    "https://fcm.googleapis.com:8443/x",               # non-default port
    "https://fcm.googleapis.com/x y", "https://fcm.googleapis.com/x\n", "",
    "https://" + "a" * 1100, "file:///etc/passwd", "gopher://fcm.googleapis.com/x",
])
def test_endpoint_rejected(bad):
    with pytest.raises(SubscriptionInvalid):
        validate_endpoint(bad)


def test_subscription_keys_and_filters_validated():
    known = {"wolf", "deer"}
    s = validate_subscription(body(creek_ids=["deer"], min_severity="advisory",
                                   quiet_hours={"start": "22:00", "end": "07:00", "tz": "America/Los_Angeles"}), known)
    assert s["creek_ids"] == ["deer"] and s["quiet_start"] == "22:00"
    for bad in (body(creek_ids=["mars"]), body(min_severity="loud"), body(quiet_hours={"start": "25:00", "end": "07:00"}),
                body(quiet_hours={"start": "22:00"}), body(quiet_hours={"start": "22:00", "end": "07:00", "tz": "Mars/Base"}),
                {"subscription": {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "AAAA", "auth": "AAAA"}}},
                {"subscription": "nope"}, []):
        with pytest.raises(SubscriptionInvalid):
            validate_subscription(bad, known)


# ---- filters -----------------------------------------------------------------------------------

def test_matches_creek_severity_quiet_hours():
    sub = {"creek_ids": ["deer"], "min_severity": "watch", "quiet_start": "22:00", "quiet_end": "07:00",
           "tz": "America/Los_Angeles"}
    day = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)    # 13:00 PDT
    night = datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc)   # 00:00 PDT
    a = validate_alert(make_alert())                            # deer, watch
    assert matches(sub, a, day) and not matches(sub, a, night)  # quiet hours hold back a watch
    assert matches(sub, validate_alert(make_alert(severity="alert")), night)  # ... but not an alert
    assert not matches(sub, validate_alert(make_alert(creek_ids=("wolf",))), day)
    assert matches(sub, validate_alert(make_alert(creek_ids=())), day)        # regional -> everyone
    assert not matches(sub, validate_alert(make_alert(severity="advisory")), day)
    assert in_quiet_hours({"quiet_start": "01:00", "quiet_end": "05:00", "tz": "UTC"},
                          datetime(2026, 1, 1, 3, tzinfo=timezone.utc))


# ---- fan-out -----------------------------------------------------------------------------------

def test_notify_counts_prunes_gone_and_repeated_failures(tmp_path):
    codes = {}
    vapid = VapidKeys(vapid_private_b64(), None, "https://creekwatch.realm.watch")
    svc = PushService(tmp_path / "p.db", vapid, sender=lambda sub, data, urg: codes[sub["endpoint"]])
    eps = {f"https://fcm.googleapis.com/fcm/send/{n}": c for n, c in (("ok", 201), ("gone", 410), ("nf", 404), ("err", 500))}
    for ep, code in eps.items():
        svc.upsert(validate_subscription(body(ep), {"deer"})); codes[ep] = code
    a = validate_alert(make_alert(severity="alert"))
    assert svc.notify(a, "new") == {"matched": 4, "sent": 1, "gone": 2, "failed": 1}
    assert svc.count() == 2
    for _ in range(push_mod.MAX_FAILURES):
        svc.notify(a, "new")
    assert [s["endpoint"] for s in svc.all()] == ["https://fcm.googleapis.com/fcm/send/ok"]


def test_notify_rechecks_stored_endpoints(tmp_path):
    calls = []
    svc = PushService(tmp_path / "p.db", VapidKeys(vapid_private_b64(), None, "https://x.example"),
                      sender=lambda *a: calls.append(a) or 201)
    svc.upsert(validate_subscription(body(), {"deer"}))
    with svc._conn() as c:  # simulate a tampered row
        c.execute("UPDATE push_subscriptions SET endpoint='https://169.254.169.254/latest/meta-data'")
    svc.notify(validate_alert(make_alert(severity="alert")), "new")
    assert calls == []


def test_subscription_cap(tmp_path):
    svc = PushService(tmp_path / "p.db", VapidKeys(vapid_private_b64(), None, "https://x.example"), max_subs=2)
    svc.upsert(validate_subscription(body("https://fcm.googleapis.com/fcm/send/1"), set()))
    svc.upsert(validate_subscription(body("https://fcm.googleapis.com/fcm/send/2"), set()))
    svc.upsert(validate_subscription(body("https://fcm.googleapis.com/fcm/send/2"), set()))  # update is fine
    with pytest.raises(OverflowError):
        svc.upsert(validate_subscription(body("https://fcm.googleapis.com/fcm/send/3"), set()))


def test_payload_capped():
    a = validate_alert(make_alert(summary="x" * 280, title="t" * 200))
    assert len(push_mod.payload_for(a, "new")) <= push_mod.MAX_PAYLOAD


# ---- hardened session + real pywebpush encryption ----------------------------------------------

def test_hardened_session_forces_safe_kwargs(monkeypatch):
    import requests
    seen = {}

    class R:
        status_code = 201
        class raw:  # noqa: N801
            @staticmethod
            def read(n, decode_content=True):
                seen["read_cap"] = n
                return b""
        def close(self):
            pass

    def fake_request(self, method, url, *a, **kw):
        seen.update(kw); seen["trust_env"] = self.trust_env
        return R()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    s = push_mod.hardened_session()
    s.request("POST", "https://fcm.googleapis.com/fcm/send/x", allow_redirects=True, timeout=999,
              proxies={"https": "http://evil:8080"})
    assert seen["allow_redirects"] is False and seen["timeout"] == push_mod.SEND_TIMEOUT
    assert seen["stream"] is True and "proxies" not in seen and seen["trust_env"] is False
    assert seen["read_cap"] == push_mod.MAX_RESPONSE
    with pytest.raises(PermissionError):
        s.request("POST", "https://169.254.169.254/x")


def test_real_webpush_encrypts_and_posts_via_hardened_session(tmp_path, monkeypatch):
    import requests
    posted = {}

    class R:
        status_code = 201
        headers = {}
        text = ""
        class raw:  # noqa: N801
            @staticmethod
            def read(n, decode_content=True):
                return b""
        def close(self):
            pass

    def fake_request(self, method, url, *a, **kw):
        posted.update(url=url, headers=kw.get("headers"), data=kw.get("data"), redirects=kw["allow_redirects"])
        return R()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    svc = PushService(tmp_path / "p.db", VapidKeys(vapid_private_b64(), None, "https://creekwatch.realm.watch"))
    svc.upsert(validate_subscription(body(), {"deer"}))
    stats = svc.notify(validate_alert(make_alert(severity="alert")), "new")
    assert stats["sent"] == 1 and posted["redirects"] is False
    assert posted["url"].startswith("https://fcm.googleapis.com/")
    h = {k.lower(): v for k, v in posted["headers"].items()}
    assert h["content-encoding"] == "aes128gcm" and h["urgency"] == "high" and h["authorization"].startswith("vapid ")
    assert b"Flood Watch" not in posted["data"]  # payload is encrypted


# ---- VAPID from env ----------------------------------------------------------------------------

def test_vapid_from_env(monkeypatch, caplog):
    priv = vapid_private_b64()
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", priv)
    v = VapidKeys.from_env()
    assert v and len(base64.urlsafe_b64decode(v.public + "==")) == 65
    monkeypatch.setenv("CREEKWATCH_VAPID_PUBLIC", b64u(b"\x04" + b"\x01" * 64))
    with caplog.at_level(logging.ERROR):
        assert VapidKeys.from_env() is None          # mismatched pair -> push disabled
    monkeypatch.delenv("CREEKWATCH_VAPID_PUBLIC")
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", "not-a-key-SECRETVALUE")
    with caplog.at_level(logging.ERROR):
        assert VapidKeys.from_env() is None
    assert "SECRETVALUE" not in caplog.text and priv not in caplog.text


# ---- HTTP endpoints ----------------------------------------------------------------------------

@pytest.fixture
def push_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", vapid_private_b64())
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", push_rate_count=1000)
    with TestClient(create_app(s)) as c:
        yield c


def test_subscribe_lifecycle(push_client):
    c = push_client
    key = c.get("/api/push/vapid-public-key").json()["key"]
    assert len(base64.urlsafe_b64decode(key + "==")) == 65
    b = body(creek_ids=["deer"], min_severity="advisory")
    r = c.post("/api/push/subscriptions", json=b)
    assert r.status_code == 201 and r.json()["creek_ids"] == ["deer"]
    assert c.post("/api/push/subscriptions", json=b).status_code == 200          # idempotent update
    assert c.request("DELETE", "/api/push/subscriptions", json={"endpoint": b["subscription"]["endpoint"]}).status_code == 204
    assert c.request("DELETE", "/api/push/subscriptions", json={"endpoint": b["subscription"]["endpoint"]}).status_code == 204
    assert c.post("/api/push/subscriptions", json=body("https://169.254.169.254/x")).status_code == 422
    assert c.post("/api/push/subscriptions", content=b"{" + b" " * 5000 + b"}",
                  headers={"content-type": "application/json"}).status_code == 413
    assert c.post("/api/push/subscriptions", content=b"not json",
                  headers={"content-type": "application/json"}).status_code == 422


def test_push_disabled_without_vapid(tmp_path, monkeypatch):
    monkeypatch.delenv("CREEKWATCH_VAPID_PRIVATE", raising=False)
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json")
    with TestClient(create_app(s)) as c:
        assert c.get("/api/push/vapid-public-key").status_code == 503
        assert c.post("/api/push/subscriptions", json=body()).status_code == 503


def test_subscription_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("CREEKWATCH_VAPID_PRIVATE", vapid_private_b64())
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json", push_rate_count=3)
    with TestClient(create_app(s)) as c:
        codes = [c.post("/api/push/subscriptions", json=body(f"https://fcm.googleapis.com/fcm/send/{i}")).status_code
                 for i in range(4)]
    assert codes == [201, 201, 201, 429]
