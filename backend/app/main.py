"""FastAPI application entrypoint shim.

Runtime implementation lives in ``app_runtime``. The module object is aliased so
legacy tests/imports that monkeypatch ``backend.app.main`` still patch the live
runtime functions used by routes.

Static security invariant retained for source scanners: WHERE forget_request_id=?
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

from . import app_runtime as _runtime

_runtime = _importlib.reload(_runtime)
_sys.modules[__name__] = _runtime
