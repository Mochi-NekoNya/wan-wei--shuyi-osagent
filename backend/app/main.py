"""FastAPI application entrypoint.

Runtime implementation lives in ``backend.app.app_runtime``.
This module re-exports the FastAPI ``app`` instance for ASGI servers and TestClient.
All route handlers and service functions remain in ``app_runtime`` to avoid
module-level state duplication caused by ``sys.modules`` self-aliasing.
"""
from __future__ import annotations

from .app_runtime import app
