"""
Tests for the duckdb engine_params namespace: SET application, allowlist
enforcement, and value validation. Uses real in-memory DuckDB connections —
no mocks needed for this layer.
"""
import duckdb
import pytest

from sql_benchmarks.resources.duckdb_client import (
    DUCKDB_SETTING_KEYS,
    _apply_engine_params,
)


def test_threads_setting_is_applied():
    con = duckdb.connect()
    _apply_engine_params(con, {"threads": 2})
    (value,) = con.sql("SELECT current_setting('threads')").fetchone()
    assert int(value) == 2


def test_memory_limit_setting_is_applied():
    con = duckdb.connect()
    (before,) = con.sql("SELECT current_setting('memory_limit')").fetchone()
    _apply_engine_params(con, {"memory_limit": "1GB"})
    (after,) = con.sql("SELECT current_setting('memory_limit')").fetchone()
    # DuckDB normalizes units (1GB -> '953.6 MiB'); assert the setting moved.
    assert after != before


def test_unknown_key_fails_loudly():
    con = duckdb.connect()
    with pytest.raises(ValueError, match="Unknown duckdb engine_params key 'work_mem'"):
        _apply_engine_params(con, {"work_mem": "4MB"})  # postgres vocab, wrong namespace


def test_unsafe_value_rejected():
    con = duckdb.connect()
    with pytest.raises(ValueError, match="Unsafe value"):
        _apply_engine_params(con, {"threads": "2'; DROP TABLE x; --"})


def test_empty_and_none_params_are_noops():
    con = duckdb.connect()
    _apply_engine_params(con, {})
    _apply_engine_params(con, None)


def test_allowlist_is_intentionally_small():
    """Growing the vocabulary is a deliberate act, not an accident."""
    assert DUCKDB_SETTING_KEYS == {"threads", "memory_limit"}
