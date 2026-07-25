"""System service router entrypoint shim.

Runtime implementation lives in ``_system_svc_runtime``. The module object is
aliased so tests/imports that patch ``backend.app.platform_api.system_svc`` still
patch the live router runtime.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

from . import _system_svc_runtime as _runtime

_runtime = _importlib.reload(_runtime)
_sys.modules[__name__] = _runtime
