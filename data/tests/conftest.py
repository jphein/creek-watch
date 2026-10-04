"""Hard network block for data tests (installed at import, never restored).

monkeypatch restores the real functions when a test ends, but background jobs (the ingest
thread pool, capped RiverDB fetches) can run AFTER that and would hit the real network, e.g.
RiverDB, which must not be queried from tests. Tests that need data monkeypatch over these
blockers; when they're undone, the blockers come back, never the real functions.
"""
from data import cdec, ingest, wq
from data.alerts import http as alerts_http


def _blocked(*a, **kw):
    raise OSError("network disabled in data tests (data/tests/conftest.py)")


wq._gql = _blocked
cdec._get_json = _blocked
ingest._http_get_text = _blocked
alerts_http.get_text = _blocked
