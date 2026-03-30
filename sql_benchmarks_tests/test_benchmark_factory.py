"""
Tests for benchmark_factory pg_settings derivation logic.

pg_settings are derived at execution time from the partition's params:
static execution.pg_settings from the YAML merged with any dimension keys
that are also Postgres session settings.
"""
import pytest
from sql_benchmarks.assets.benchmark_factory import _STATIC_PG
from sql_benchmarks.resources.postgres_client import PG_SETTING_KEYS


# ---------------------------------------------------------------------------
# _STATIC_PG — module-level constant, same for all partitions
# ---------------------------------------------------------------------------

def test_static_pg_is_dict():
    assert isinstance(_STATIC_PG, dict)


def test_static_pg_contains_only_allowlisted_keys():
    """Static pg_settings from the YAML must only use allowlisted keys."""
    for key in _STATIC_PG:
        assert key in PG_SETTING_KEYS, f"Static pg_setting {key!r} is not in the allowlist"


# ---------------------------------------------------------------------------
# pg_settings derivation logic (tested as a pure function)
# ---------------------------------------------------------------------------

def derive_pg_settings(params):
    """Mirror of the one-liner in _benchmark — tested independently."""
    return {**_STATIC_PG, **{k: v for k, v in params.items() if k in PG_SETTING_KEYS}}


def test_pg_dimension_keys_are_included():
    """Dimension keys that are PG settings appear in the derived pg_settings."""
    params = {"rows": 1_000_000, "work_mem": "64MB", "max_parallel_workers_per_gather": 4}
    result = derive_pg_settings(params)
    assert result["work_mem"] == "64MB"
    assert result["max_parallel_workers_per_gather"] == 4


def test_non_pg_dimension_keys_are_excluded():
    """Dimension keys that are not PG settings must not bleed into pg_settings."""
    params = {"rows": 1_000_000, "disk_type": "ssd", "work_mem": "4MB"}
    result = derive_pg_settings(params)
    assert "rows" not in result
    assert "disk_type" not in result


def test_static_pg_is_merged_with_dimension_pg_keys():
    """Dimension PG values override static ones; static keys not in dims are preserved."""
    import sql_benchmarks.assets.benchmark_factory as factory
    original = factory._STATIC_PG.copy()

    # Inject a known static setting for this test
    factory._STATIC_PG["random_page_cost"] = 4.0
    factory._STATIC_PG["work_mem"] = "4MB"

    params = {"work_mem": "256MB", "rows": 500}
    result = derive_pg_settings(params)

    assert result["random_page_cost"] == 4.0   # preserved from static
    assert result["work_mem"] == "256MB"        # dimension overrides static

    # Restore
    factory._STATIC_PG.clear()
    factory._STATIC_PG.update(original)


def test_empty_params_returns_only_static():
    """With no dimensions, pg_settings is just the static config."""
    result = derive_pg_settings({})
    assert result == _STATIC_PG


def test_no_pg_dimension_keys_returns_only_static():
    """Params with no PG-setting keys produce only the static config."""
    params = {"rows": 100, "disk_type": "ssd"}
    result = derive_pg_settings(params)
    assert result == _STATIC_PG
