"""Runtime settings, all from environment variables (no secrets needed)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # SQLite db + uploads/ live here. Spec default: repo-root data/ (both gitignored).
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("CREEKWATCH_DATA_DIR", REPO_ROOT / "data")))
    web_dir: Path = field(default_factory=lambda: Path(os.environ.get("CREEKWATCH_WEB_DIR", REPO_ROOT / "web")))
    sites_json: Path = field(default_factory=lambda: Path(os.environ.get("CREEKWATCH_SITES_JSON", REPO_ROOT / "data" / "sites.json")))
    max_photo_bytes: int = int(os.environ.get("CREEKWATCH_MAX_PHOTO_MB", "10")) * 1024 * 1024
    photo_max_px: int = int(os.environ.get("CREEKWATCH_PHOTO_MAX_PX", "1600"))
    max_km_from_creek: float = float(os.environ.get("CREEKWATCH_MAX_KM", "25"))
    # POST /api/reports per client IP: N reports per window.
    rate_limit_count: int = int(os.environ.get("CREEKWATCH_RATE_COUNT", "12"))
    rate_limit_window_s: int = int(os.environ.get("CREEKWATCH_RATE_WINDOW_S", "600"))
    conditions_ttl_s: int = int(os.environ.get("CREEKWATCH_CONDITIONS_TTL_S", "600"))
    enable_stubs: bool = _env_bool("CREEKWATCH_STUBS_OK", True)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "creekwatch.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"
