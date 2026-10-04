"""ASGI entry point: `uvicorn creekwatch.asgi:app` (kept separate so importing main has no side effects)."""

import logging
import os

from .main import create_app

logging.basicConfig(level=os.environ.get("CREEKWATCH_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
