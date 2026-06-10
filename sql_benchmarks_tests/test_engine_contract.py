"""
Engine contract tests.

The benchmark factory calls every engine resource with the exact keyword
arguments below.  Unit tests mock the engines, so a facade whose signature
drifts from the contract passes the suite but explodes on a real run
(e.g. "run_query() got an unexpected keyword argument 'pg_settings'").
These tests pin the signatures themselves.

NOTE: engines are imported lazily inside the tests, not at module level.
ActianEngine captures env vars in its class defaults at import time, and
test_actian_integration.py relies on importing it *after* monkeypatching
the environment — a module-level import here would freeze empty defaults
for the whole session.
"""
import importlib
import inspect

import pytest

ENGINE_CLASSES = [
    ("sql_benchmarks.resources.actian", "ActianEngine"),
    ("sql_benchmarks.resources.duckdb", "DuckDBEngine"),
    ("sql_benchmarks.resources.postgres", "PostgresEngine"),
    ("sql_benchmarks.resources.typedb_engine", "TypeDBEngine"),
]

# Keyword arguments used by sql_benchmarks/assets/benchmark_factory.py
RUN_QUERY_KWARGS = {"sql", "partition_key", "pg_settings"}
# Positional parameters used by the ingestion factory
BULK_LOAD_PARAMS = ["filepath", "table_name", "partition_key"]


def _load(module_path, class_name):
    return getattr(importlib.import_module(module_path), class_name)


@pytest.mark.parametrize("module_path,class_name", ENGINE_CLASSES, ids=lambda v: v.split(".")[-1])
def test_run_query_accepts_factory_kwargs(module_path, class_name):
    engine_cls = _load(module_path, class_name)
    params = inspect.signature(engine_cls.run_query).parameters
    missing = RUN_QUERY_KWARGS - set(params)
    assert not missing, (
        f"{class_name}.run_query is missing kwargs the benchmark "
        f"factory passes: {sorted(missing)}"
    )


@pytest.mark.parametrize("module_path,class_name", ENGINE_CLASSES, ids=lambda v: v.split(".")[-1])
def test_run_query_pg_settings_is_optional(module_path, class_name):
    """Engines that ignore pg_settings must still default it, not require it."""
    engine_cls = _load(module_path, class_name)
    param = inspect.signature(engine_cls.run_query).parameters["pg_settings"]
    assert param.default is None, (
        f"{class_name}.run_query: pg_settings must default to None"
    )


@pytest.mark.parametrize("module_path,class_name", ENGINE_CLASSES, ids=lambda v: v.split(".")[-1])
def test_bulk_load_signature(module_path, class_name):
    engine_cls = _load(module_path, class_name)
    params = list(inspect.signature(engine_cls.bulk_load).parameters)
    assert params[1:4] == BULK_LOAD_PARAMS, (
        f"{class_name}.bulk_load signature drifted from "
        f"{BULK_LOAD_PARAMS}: got {params[1:4]}"
    )


def test_interface_matches_factory_contract():
    """The Protocol itself must advertise the contract the factory uses."""
    from sql_benchmarks.resources.base_engine import IBenchmarkEngine
    params = inspect.signature(IBenchmarkEngine.run_query).parameters
    assert RUN_QUERY_KWARGS <= set(params)
