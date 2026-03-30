"""
Tests for benchmark_factory module-level state and pg_settings pre-computation.

PG_SETTINGS_BY_PARTITION is computed once at module load from SCENARIO_CONFIG
and FULL_CONFIG. These tests verify the structural guarantees of that mapping
without touching Dagster asset materialisation.
"""
import pytest
from sql_benchmarks.assets.benchmark_factory import PG_SETTINGS_BY_PARTITION
from sql_benchmarks.partitions import SCENARIO_CONFIG
from sql_benchmarks.resources.postgres_client import PG_SETTING_KEYS


# ---------------------------------------------------------------------------
# PG_SETTINGS_BY_PARTITION structure
# ---------------------------------------------------------------------------

def test_pg_settings_by_partition_covers_all_scenario_keys():
    """Every partition key in SCENARIO_CONFIG has an entry in the mapping."""
    assert set(PG_SETTINGS_BY_PARTITION.keys()) == set(SCENARIO_CONFIG.keys())


def test_pg_settings_by_partition_values_are_dicts():
    """Each entry is a plain dict (no lambdas, no builders, nothing deferred)."""
    for pk, settings in PG_SETTINGS_BY_PARTITION.items():
        assert isinstance(settings, dict), f"Partition {pk!r} value is not a dict"


def test_pg_settings_by_partition_contains_only_allowlisted_keys():
    """No key that isn't in PG_SETTING_KEYS can appear in any partition's settings."""
    for pk, settings in PG_SETTINGS_BY_PARTITION.items():
        for key in settings:
            assert key in PG_SETTING_KEYS, (
                f"Partition {pk!r} has non-allowlisted key {key!r} in pg_settings"
            )


def test_pg_settings_by_partition_captures_dimension_pg_keys():
    """
    For any partition whose SCENARIO_CONFIG entry contains a key that is also
    a PG setting (e.g. work_mem, max_parallel_workers_per_gather), that key
    must appear in PG_SETTINGS_BY_PARTITION for that partition.
    """
    for pk, scenario in SCENARIO_CONFIG.items():
        pg_dim_keys = {k for k in scenario if k in PG_SETTING_KEYS}
        actual_keys = set(PG_SETTINGS_BY_PARTITION.get(pk, {}).keys())
        assert pg_dim_keys.issubset(actual_keys), (
            f"Partition {pk!r}: expected {pg_dim_keys} in pg_settings, got {actual_keys}"
        )


def test_pg_settings_by_partition_excludes_non_pg_dimension_keys():
    """
    Dimension keys such as 'rows' or 'disk_type' must never bleed into
    pg_settings, regardless of what the scenario config contains.
    """
    non_pg_keys = {"rows", "disk_type", "size", "scale", "engine"}
    for pk, settings in PG_SETTINGS_BY_PARTITION.items():
        leaked = non_pg_keys & settings.keys()
        assert not leaked, (
            f"Partition {pk!r} leaked non-PG dimension keys into pg_settings: {leaked}"
        )
