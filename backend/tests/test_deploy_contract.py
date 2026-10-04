"""The image and the live deploy must agree on port, data dir and volume, or a deploy either fails its
health gate or (worse) writes reports into the container layer and loses them at the next deploy."""

import re

import pytest

from creekwatch.config import REPO_ROOT

REDEPLOY = REPO_ROOT / "deploy" / "redeploy.sh"


def _default(script: str, var: str) -> str:
    m = re.search(rf'\$\{{{var}:-([^}}]+)\}}', script)
    assert m, f"{var} default not found in redeploy.sh"
    return m.group(1)


@pytest.fixture(scope="module")
def deploy():
    if not REDEPLOY.exists():
        pytest.skip("deploy/redeploy.sh not present")
    s = REDEPLOY.read_text()
    return {"port": _default(s, "CW_APP_PORT"), "var": _default(s, "CW_VAR"), "volume": _default(s, "CW_VOLUME")}


def test_dockerfile_matches_redeploy(deploy):
    d = (REPO_ROOT / "Dockerfile").read_text()
    port, var = deploy["port"], deploy["var"]
    assert re.search(rf"^EXPOSE {port}$", d, re.M), f"EXPOSE must be {port}"
    assert f'"--port", "{port}"' in d, f"CMD must listen on {port}"
    assert f"127.0.0.1:{port}/healthz" in d, f"HEALTHCHECK must probe {port}"
    assert re.search(rf"CREEKWATCH_DATA_DIR={re.escape(var)}\b", d), f"CREEKWATCH_DATA_DIR must be {var}"
    assert re.search(rf"^VOLUME {re.escape(var)}$", d, re.M), f"VOLUME must be {var}"


def test_compose_matches_redeploy(deploy):
    c = (REPO_ROOT / "compose.yaml").read_text()
    assert f":{deploy['port']}\"" in c, "compose must map to the app port"
    assert f"{deploy['volume']}:{deploy['var']}" in c, "compose must mount the live volume at the data dir"


def test_settings_default_data_dir_env_wins(monkeypatch, deploy):
    from creekwatch.config import Settings

    monkeypatch.setenv("CREEKWATCH_DATA_DIR", deploy["var"])
    assert str(Settings().db_path) == f"{deploy['var']}/creekwatch.db"
