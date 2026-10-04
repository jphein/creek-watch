"""Oracle gate 13-17 SHOULD-FIX items: IPv6 /64 rate-limit keying and photo decode memory."""
import collections
import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import REPORT, gps_jpeg
from creekwatch import photos
from creekwatch.config import Settings
from creekwatch.main import create_app
from creekwatch.ratelimit import rate_key


# ---- (1) IPv6 rate-limit keying ---------------------------------------------------
def test_rate_key_ipv6_by_64_ipv4_unchanged():
    assert rate_key("2001:db8:1:2::1") == rate_key("2001:db8:1:2:ffff:ffff:ffff:ffff") == "2001:db8:1:2::/64"
    assert rate_key("2001:db8:1:2::1") != rate_key("2001:db8:1:3::1")
    assert rate_key("203.0.113.7") == "203.0.113.7"
    assert rate_key("::ffff:203.0.113.7") == "203.0.113.7"   # IPv4-mapped shares the IPv4 bucket
    assert rate_key("2001:DB8:1:2::AbCd") == "2001:db8:1:2::/64"  # case-insensitive
    assert rate_key("fe80::1%eth0") == "fe80::/64"            # scoped address doesn't raise
    assert rate_key("unknown") == "unknown"


def _post_from(tmp_path, peers, count=1):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json",
                 rate_limit_count=count)
    app = create_app(s)
    codes = []
    with TestClient(app) as c0:  # run lifespan once (db init)
        c0.get("/healthz")
    for peer in peers:
        with TestClient(app, client=(peer, 50000)) as c:
            codes.append(c.post("/api/reports", data=REPORT).status_code)
    return codes


def test_same_ipv6_64_shares_one_bucket(tmp_path):
    # Two different addresses in one /64: with a limit of 1, the second is throttled.
    assert _post_from(tmp_path, ["2001:db8:1:2::1", "2001:db8:1:2::dead:beef"]) == [201, 429]


def test_different_ipv6_64_gets_its_own_bucket(tmp_path):
    assert _post_from(tmp_path, ["2001:db8:1:2::1", "2001:db8:1:3::1"]) == [201, 201]


def test_ipv4_clients_still_keyed_per_address(tmp_path):
    assert _post_from(tmp_path, ["203.0.113.7", "203.0.113.8", "203.0.113.7"]) == [201, 201, 429]


# ---- (2) decode memory: pixel cap + semaphore ------------------------------------
def _png(w, h, mode="RGB"):
    b = io.BytesIO()
    Image.new(mode, (w, h), (30, 120, 80) + ((200,) if mode == "RGBA" else ())).save(b, format="PNG")
    return b.getvalue()


def test_41mp_rejected_with_clear_message():
    with pytest.raises(photos.PhotoError) as e:
        photos.process_photo(_png(7400, 5550))           # 41.07 MP
    msg = str(e.value)
    assert "41.1 megapixels" in msg and "limit is 40" in msg


def test_48mp_heif_max_size_rejected_before_decode(monkeypatch):
    # iPhone "HEIF Max" is 8064x6048 = 48.8 MP. Rejected from the header, without decoding.
    raw = _png(8064, 6048)  # build first: saving calls load()

    def boom(self):
        raise AssertionError("decoded an over-cap image")
    monkeypatch.setattr(Image.Image, "load", boom)
    with pytest.raises(photos.PhotoError, match=r"48\.8 megapixels"):
        photos.process_photo(raw)


def test_12mp_phone_photo_passes():
    out = photos.process_photo(gps_jpeg((4032, 3024)))  # standard 12 MP iPhone frame
    assert Image.open(io.BytesIO(out)).size == (1200, 1600)  # orientation 6 applied, then shrunk


def test_40mp_rgba_png_passes_and_is_flattened():
    out = photos.process_photo(_png(7300, 5470, "RGBA"))  # 39.9 MP, just under the cap
    img = Image.open(io.BytesIO(out))
    assert img.mode == "RGB" and max(img.size) == 1600


def test_decode_semaphore_limits_concurrency(monkeypatch):
    live, peak, lock = 0, 0, threading.Lock()

    def slow(raw, max_px, quality):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.15)
        with lock:
            live -= 1
        return b"ok"

    monkeypatch.setattr(photos, "_process_photo", slow)
    threads = [threading.Thread(target=photos.process_photo, args=(b"x",)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == photos.DECODE_SLOTS == 2


def test_decode_semaphore_times_out_with_clear_message(monkeypatch):
    monkeypatch.setattr(photos, "DECODE_WAIT_S", 0.05)
    held = [photos._decode_slots.acquire() for _ in range(photos.DECODE_SLOTS)]
    try:
        with pytest.raises(photos.PhotoError, match="busy"):
            photos.process_photo(_png(10, 10))
    finally:
        for _ in held:
            photos._decode_slots.release()


def test_semaphore_released_after_errors():
    for _ in range(photos.DECODE_SLOTS + 2):
        with pytest.raises(photos.PhotoError):
            photos.process_photo(b"not an image")
    assert photos.process_photo(_png(20, 20))  # slots weren't leaked


# ---- (3) waiting photo uploads must not hold threadpool threads -------------------
def test_queued_photo_uploads_do_not_starve_other_endpoints(tmp_path, monkeypatch):
    """Sync endpoints (/healthz, /api/*) share Starlette's 40-thread pool with photo decoding.
    A burst of uploads waiting for a decode slot must not occupy that pool."""
    import anyio
    import httpx

    def slow(raw, max_px, quality):
        time.sleep(1.5)
        return b"jpeg"

    monkeypatch.setattr(photos, "_process_photo", slow)
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json",
                 rate_limit_count=10_000, report_budget=10_000, photo_budget=10_000)
    app = create_app(s)
    photo = _png(16, 16)
    result = {}

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                async def upload():
                    r = await c.post("/api/reports", data=REPORT, files={"photo": ("p.png", photo, "image/png")})
                    result.setdefault("codes", []).append(r.status_code)

                async with anyio.create_task_group() as tg:
                    for _ in range(45):
                        tg.start_soon(upload)
                    await anyio.sleep(0.5)  # uploads are now queued behind the 2 decode slots
                    t0 = time.monotonic()
                    r = await c.get("/healthz")
                    result["healthz_s"] = time.monotonic() - t0
                    result["healthz"] = r.status_code

    anyio.run(main)
    assert result["healthz"] == 200
    assert result["healthz_s"] < 1.0, f"/healthz took {result['healthz_s']:.1f}s behind queued uploads"
    # Overflow is refused fast with 503 (not 415), never left to pile up.
    assert set(result["codes"]) <= {201, 503}
    # 2 decoding + MAX_QUEUE waiting are accepted; the rest are refused immediately.
    assert result["codes"].count(201) == photos.DECODE_SLOTS + photos.MAX_QUEUE
    print("healthz_s", round(result["healthz_s"], 3), "codes", sorted(collections.Counter(result["codes"]).items()))
