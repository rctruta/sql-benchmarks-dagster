"""Locks in the lazy-init contract for utils.common._GLOBAL_COMPILER.

The FastAPI app must import cleanly WITHOUT parsing active.yaml. The compiler
is only constructed at first load_context() call — that call happens eagerly
at Dagster asset-definition time (via `CTX = load_context()` in
sql_benchmarks/assets/*_factory.py), so from Dagster's perspective the
fail-hard behavior is preserved. The API and CLI paths never call
load_context(), so they never trigger the compiler at all.

If this test fails, the API is doing import-time work it doesn't need — and
a broken active.yaml (which is now gitignored, so a fresh clone won't have
one) will crash the API at boot instead of just crashing Dagster.
"""
from unittest.mock import patch

import pytest

from sql_benchmarks.config_loader import ConfigLoader
from sql_benchmarks.utils import common as common_module


def test_global_compiler_starts_none():
    """Import-time state: no ConfigLoader instance exists yet."""
    # Simulate a fresh import by resetting the module state.
    common_module._GLOBAL_COMPILER = None
    assert common_module._GLOBAL_COMPILER is None


def test_load_context_creates_compiler_lazily(monkeypatch):
    """First load_context() call instantiates ConfigLoader exactly once."""
    common_module._GLOBAL_COMPILER = None
    calls = []
    orig_init = ConfigLoader.__init__

    def counting_init(self, *a, **kw):
        calls.append(1)
        return orig_init(self, *a, **kw)

    monkeypatch.setattr(ConfigLoader, "__init__", counting_init)
    common_module.load_context()
    assert len(calls) == 1


def test_load_context_caches_compiler(monkeypatch):
    """Subsequent load_context() calls reuse the compiler, not recreate it."""
    common_module._GLOBAL_COMPILER = None
    calls = []
    orig_init = ConfigLoader.__init__

    def counting_init(self, *a, **kw):
        calls.append(1)
        return orig_init(self, *a, **kw)

    monkeypatch.setattr(ConfigLoader, "__init__", counting_init)
    common_module.load_context()
    common_module.load_context()
    common_module.load_context()
    assert len(calls) == 1


def test_api_import_does_not_instantiate_compiler(monkeypatch):
    """Importing the FastAPI app must NOT instantiate a ConfigLoader — the
    API accepts YAML payloads directly and has no business parsing the local
    active.yaml runtime-staging file at boot."""
    # Reset module state so any previous test's cache doesn't confound this one.
    common_module._GLOBAL_COMPILER = None
    calls = []
    orig_init = ConfigLoader.__init__

    def counting_init(self, *a, **kw):
        calls.append(1)
        return orig_init(self, *a, **kw)

    monkeypatch.setattr(ConfigLoader, "__init__", counting_init)

    # The API app builder — importing app.py and its router chain must be inert.
    from sql_benchmarks.api.app import create_app
    create_app()
    assert calls == [], (
        f"create_app() instantiated ConfigLoader {len(calls)} time(s); "
        "something on the API import chain regressed to eager init. Check "
        "sql_benchmarks/utils/common.py: _GLOBAL_COMPILER must default to None."
    )
