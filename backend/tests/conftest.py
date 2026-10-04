import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from creekwatch.config import Settings
from creekwatch.main import create_app


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
    "creek_id": "deer-creek", "lat": "39.2630", "lon": "-121.0228",
    "water_color": "clear", "algae": "none", "trash": "some", "flow": "normal", "odor": "none",
    "dead_fish": "false", "notes": "Looks good", "reporter_name": "Alec",
}
