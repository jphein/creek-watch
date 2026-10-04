"""Adapters for the two-process --once test. Each fetch appends a line to $FAKE_ADAPTER_LOG."""
import os


class _A:
    def __init__(self, source, interval_s, fail=False):
        self.source, self.source_name, self.interval_s, self.fail = source, source.upper(), interval_s, fail

    def fetch(self, ctx):
        with open(os.environ["FAKE_ADAPTER_LOG"], "a") as f:
            f.write(self.source + "\n")
        if self.fail or os.environ.get("FAKE_ADAPTERS_FAIL"):
            raise RuntimeError("upstream down")
        return [{"id": f"{self.source}:1", "source": self.source, "source_name": self.source_name,
                 "category": "other", "severity": "info", "title": "t", "summary": "s",
                 "effective": "2026-10-03T00:00:00Z", "status": "active",
                 "url": "https://example.gov/x", "attribution": "public domain"}]


ADAPTERS = [_A("sso", 43200), _A("nws", 300)]
