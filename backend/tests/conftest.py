import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from creekwatch.config import Settings
from creekwatch.main import create_app


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    # Unit tests use the built-in stubs; the data package is exercised in test_integration_data.py.
    monkeypatch.setenv("CREEKWATCH_USE_DATA_PKG", "0")
    # no background conditions warm-up in tests unless a test opts in (keeps tests offline/deterministic)
    monkeypatch.setenv("CREEKWATCH_WARM_CONDITIONS", "0")
    # tests must behave the same on any host, including a Fly machine (FLY_APP_NAME changes client-IP trust)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "noweb", sites_json=tmp_path / "missing.json",
                    rate_limit_count=1000)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def gps_jpeg(size=(3000, 2000)) -> bytes:
    """A JPEG carrying GPS EXIF (Nevada City), camera make, and an orientation tag."""
    img = Image.new("RGB", size, (30, 120, 80))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (39.0, 15.0, 47.0)
    gps[3], gps[4] = "W", (121.0, 1.0, 1.0)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


REPORT = {
    "creek_id": "deer", "lat": "39.2630", "lon": "-121.0228",
    "water_color": "clear", "algae": "none", "trash": "some", "flow": "normal", "odor": "none",
    "dead_fish": "false", "notes": "Looks good", "reporter_name": "Alec",
}
