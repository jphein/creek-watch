"""ASGI entry point: `uvicorn creekwatch.asgi:app --app-dir backend` (separate so importing main has no side effects)."""

import logging
import os
import sys

from .config import REPO_ROOT

# The data lane's `data` package lives at the repo root; --app-dir only adds backend/ to sys.path.
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from .main import create_app  # noqa: E402

logging.basicConfig(level=os.environ.get("CREEKWATCH_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
