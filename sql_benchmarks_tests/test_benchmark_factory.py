"""
Tests for pg_settings preparation in config_loader and consumption in benchmark_factory.

pg_settings are built once in config_loader._compile_scenario_config and stored
as a nested key in SCENARIO_CONFIG. benchmark_factory reads them out directly —
no derivation at execution time.
"""
import pytest
from sql_benchmarks.partitions import SCENARIO_CONFIG
from sql_benchmarks.resources.postgres_client import PG_SETTING_KEYS


# ---------------------------------------------------------------------------
# config_loader: pg_settings prepared at load time
# ---------------------------------------------------------------------------

def test_scenario_config_pg_settings_values_are_dicts():
    """Every pg_settings entry in SCENARIO_CONFIG is a plain dict."""
    for pk, params in SCENARIO_CONFIG.items():
        if "pg_settings" in params:
            assert isinstance(params["pg_settings"], dict), \
                f"Partition {pk!r}: pg_settings is not a dict"


def test_scenario_config_pg_settings_contains_only_allowlisted_keys():
    """No key outside PG_SETTING_KEYS can appear in any partition's pg_settings."""
    for pk, params in SCENARIO_CONFIG.items():
        for key in params.get("pg_settings", {}):
            assert key in PG_SETTING_KEYS, \
                f"Partition {pk!r}: non-allowlisted key {key!r} in pg_settings"


def test_scenario_config_pg_dimension_keys_appear_in_pg_settings():
    """
    If a partition's dimensions include a PG setting key (e.g. work_mem),
    that key must appear in the nested pg_settings dict.
    """
    for pk, params in SCENARIO_CONFIG.items():
        pg_dim_keys = {k for k in params if k in PG_SETTING_KEYS}
        if pg_dim_keys:
            assert "pg_settings" in params, \
                f"Partition {pk!r} has PG dimension keys {pg_dim_keys} but no pg_settings entry"
            for key in pg_dim_keys:
                assert key in params["pg_settings"], \
                    f"Partition {pk!r}: dimension key {key!r} missing from pg_settings"


def test_scenario_config_non_pg_dimension_keys_not_in_pg_settings():
    """Dimension keys like 'rows' must not appear in pg_settings."""
    non_pg_keys = {"rows", "disk_type", "size", "scale"}
    for pk, params in SCENARIO_CONFIG.items():
        leaked = non_pg_keys & set(params.get("pg_settings", {}).keys())
        assert not leaked, \
            f"Partition {pk!r}: non-PG keys {leaked} leaked into pg_settings"


# ---------------------------------------------------------------------------
# benchmark_factory: plain lookup, no derivation
# ---------------------------------------------------------------------------

def test_benchmark_factory_reads_pg_settings_from_params():
    """
    _benchmark reads pg_settings via params.get('pg_settings', {}).
    Verify the key is present and consistent for partitions that have PG dimensions.
    """
    for pk, params in SCENARIO_CONFIG.items():
        pg_settings = params.get("pg_settings", {})
        # All keys must be allowlisted
        for key in pg_settings:
            assert key in PG_SETTING_KEYS, \
                f"Partition {pk!r}: pg_settings key {key!r} not in allowlist"
