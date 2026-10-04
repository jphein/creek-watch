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
    # Disk guard across ALL clients: stored photos per window. Only spent by VALID reports carrying a
    # photo, and when exhausted only the photo is refused; text reports are never globally blocked.
    # Global bound on stored reports per window (text rows are tiny; this only stops a distributed flood).
    report_budget: int = int(os.environ.get("CREEKWATCH_REPORT_BUDGET", "2000"))
    photo_budget: int = int(os.environ.get("CREEKWATCH_PHOTO_BUDGET", "300"))
    # Public API returns coordinates rounded to this many decimals (3 ≈ 110 m) to protect reporters.
    public_coord_decimals: int = int(os.environ.get("CREEKWATCH_COORD_DECIMALS", "3"))
    conditions_ttl_s: int = int(os.environ.get("CREEKWATCH_CONDITIONS_TTL_S", "600"))
    # Use the data lane's `data` package (sites/ingest/score). Tests turn this off for hermetic stubs.
    use_data_package: bool = field(default_factory=lambda: _env_bool("CREEKWATCH_USE_DATA_PKG", True))
    # Peers allowed to tell us the client IP (CF-Connecting-IP / X-Forwarded-For): Caddy on the host via docker bridge.
    trusted_proxies: str = field(default_factory=lambda: os.environ.get(
        "CREEKWATCH_TRUSTED_PROXIES", "127.0.0.0/8,::1/128,172.16.0.0/12"))

    # Alerts: background poller (off unless enabled; tests/dev never fetch), push limits.
    # Prefetch every creek's conditions in the background at startup (first visit after a redeploy).
    warm_conditions: bool = field(default_factory=lambda: _env_bool("CREEKWATCH_WARM_CONDITIONS", True))
    poller_enabled: bool = field(default_factory=lambda: _env_bool("CREEKWATCH_POLLER", False))
    poller_tick_s: float = field(default_factory=lambda: float(os.environ.get("CREEKWATCH_POLLER_TICK_S", "30")))
    push_max_subs: int = field(default_factory=lambda: int(os.environ.get("CREEKWATCH_PUSH_MAX_SUBS", "5000")))
    push_rate_count: int = field(default_factory=lambda: int(os.environ.get("CREEKWATCH_PUSH_RATE_COUNT", "20")))
    public_url: str | None = field(default_factory=lambda: os.environ.get("CREEKWATCH_PUBLIC_URL") or None)

    # Fly.io injects FLY_APP_NAME into every machine; only then is Fly-Client-IP trusted (fly-proxy sets it).
    on_fly: bool = field(default_factory=lambda: bool(os.environ.get("FLY_APP_NAME")))
    # Our own Cloudflare-proxied hostnames: only for these is CF-Connecting-IP trusted on Fly.
    cf_hosts: frozenset = field(default_factory=lambda: frozenset(
        h.strip().lower().rstrip(".") for h in os.environ.get(
            "CREEKWATCH_CF_HOSTS", "creekwatch.realm.watch,creek.realm.watch").split(",") if h.strip()))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "creekwatch.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"
