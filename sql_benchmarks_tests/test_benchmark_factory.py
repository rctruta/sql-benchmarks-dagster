"""
Tests for namespaced engine_params: assembled once in
config_loader._compile_scenario_config, stored under the 'engine_params' key
of each partition's params, and sliced per engine by benchmark_factory
(each engine receives ONLY its own namespace).
"""
import os
import textwrap

import pytest
from sql_benchmarks.config_loader import ConfigLoader
from sql_benchmarks.partitions import SCENARIO_CONFIG


def make_loader(tmp_path, yaml_body: str) -> ConfigLoader:
    path = os.path.join(str(tmp_path), "exp.yaml")
    with open(path, "w") as f:
        f.write(textwrap.dedent(yaml_body))
    return ConfigLoader(config_path=path)


BASE_CONFIG = """
    meta:
      name: engine_params_test

    definitions:
      rows:
        tiny: 1000
        small: 100000

    execution:
      test_suite: sort_spill
      engines: [postgres, duckdb]
      engine_params:
        postgres:
          random_page_cost: 1.1
        duckdb:
          memory_limit: 1GB
      matrix:
        rows: [tiny, small]
        postgres.work_mem: [4MB, 1GB]
"""


# ---------------------------------------------------------------------------
# config_loader: namespace assembly
# ---------------------------------------------------------------------------

def test_namespaced_dimension_lands_in_engine_namespace(tmp_path):
    loader = make_loader(tmp_path, BASE_CONFIG)
    for pk, params in loader.scenario_config.items():
        ep = params["engine_params"]
        assert ep["postgres"]["work_mem"] in ("4MB", "1GB"), \
            f"Partition {pk!r}: namespaced dim missing from postgres namespace"


def test_static_block_merges_with_varied_dimensions(tmp_path):
    loader = make_loader(tmp_path, BASE_CONFIG)
    for pk, params in loader.scenario_config.items():
        ep = params["engine_params"]
        # static value present alongside the varied one
        assert ep["postgres"]["random_page_cost"] == 1.1
        assert ep["duckdb"] == {"memory_limit": "1GB"}


def test_matrix_dimension_overrides_static_block(tmp_path):
    loader = make_loader(tmp_path, """
        meta: {name: override_test}
        execution:
          engines: [postgres]
          engine_params:
            postgres: {work_mem: 16MB}
          matrix:
            rows: [100]
            postgres.work_mem: [4MB]
    """)
    (params,) = loader.scenario_config.values()
    assert params["engine_params"]["postgres"]["work_mem"] == "4MB"


def test_partitions_do_not_share_namespace_dicts(tmp_path):
    """Mutating one partition's engine_params must not affect another's."""
    loader = make_loader(tmp_path, BASE_CONFIG)
    partitions = list(loader.scenario_config.values())
    partitions[0]["engine_params"]["postgres"]["poisoned"] = True
    assert "poisoned" not in partitions[1]["engine_params"]["postgres"]


def test_plain_dimensions_do_not_leak_into_engine_params(tmp_path):
    loader = make_loader(tmp_path, BASE_CONFIG)
    for params in loader.scenario_config.values():
        for ns, settings in params["engine_params"].items():
            assert "rows" not in settings, f"'rows' leaked into namespace {ns!r}"


def test_no_engine_params_key_when_none_defined(tmp_path):
    loader = make_loader(tmp_path, """
        meta: {name: plain_test}
        execution:
          engines: [duckdb]
          matrix:
            rows: [100]
    """)
    (params,) = loader.scenario_config.values()
    assert "engine_params" not in params


def test_unknown_namespace_is_carried_not_dropped(tmp_path):
    """Future engines (e.g. quack) are first-class: the loader is namespace-agnostic."""
    loader = make_loader(tmp_path, """
        meta: {name: quack_test}
        execution:
          engines: [duckdb]
          engine_params:
            quack: {server_threads: 8}
          matrix:
            rows: [100]
    """)
    (params,) = loader.scenario_config.values()
    assert params["engine_params"]["quack"] == {"server_threads": 8}


# ---------------------------------------------------------------------------
# factory slice: each engine sees only its own namespace
# ---------------------------------------------------------------------------

def test_factory_slice_isolates_namespaces(tmp_path):
    """Replicates the exact lookup benchmark_factory performs per engine."""
    loader = make_loader(tmp_path, BASE_CONFIG)
    for params in loader.scenario_config.values():
        pg_slice = params.get("engine_params", {}).get("postgres", {})
        duck_slice = params.get("engine_params", {}).get("duckdb", {})
        assert "memory_limit" not in pg_slice
        assert "work_mem" not in duck_slice
        # engines not in the config get an empty dict, never an error
        assert params.get("engine_params", {}).get("quack", {}) == {}


def test_dims_exclude_engine_params_but_keep_dotted_keys(tmp_path):
    """Replicates the factory's dims split: traceability keys stay, nest goes."""
    loader = make_loader(tmp_path, BASE_CONFIG)
    for params in loader.scenario_config.values():
        dims = {k: v for k, v in params.items() if k != "engine_params"}
        assert "engine_params" not in dims
        assert "postgres.work_mem" in dims  # dotted dim remains for fragments/CSV
        assert "rows" in dims


# ---------------------------------------------------------------------------
# live SCENARIO_CONFIG sanity (whatever active.yaml currently is)
# ---------------------------------------------------------------------------

def test_live_scenario_config_engine_params_shape():
    """If active.yaml defines engine_params, it must be Dict[str, Dict]."""
    for pk, params in SCENARIO_CONFIG.items():
        ep = params.get("engine_params", {})
        assert isinstance(ep, dict)
        for ns, settings in ep.items():
            assert isinstance(settings, dict), \
                f"Partition {pk!r}: namespace {ns!r} is not a dict"
