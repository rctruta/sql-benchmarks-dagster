"""Tests for the datagen↔reality contract (sql_benchmarks/utils/datagen_contract.py).

These are the verification that was MISSING when generated data could silently
drift from what the config declared (the "stats say String / Postgres has jsonb"
gap). Each check has a passing case and a failing case — the failing case is the
point: the contract must catch drift, not just record it.
"""
from sql_benchmarks.utils.datagen_contract import (
    verify_stats_against_config,
    verify_pg_schema,
    expected_pg_type,
)


# --------------------------------------------------------------------------
# Staging contract: declared providers / null rates vs observed stats
# --------------------------------------------------------------------------

def _stats(rows, cols):
    return {"rows": rows, "columns": cols}


def test_stats_contract_clean_passes():
    table_def = {"columns": [
        {"name": "id", "provider": "sequence"},
        {"name": "payload", "provider": "json_blob", "type": "jsonb"},
        {"name": "tags", "provider": "int_array", "type": "integer[]"},
    ]}
    stats = _stats(1000, {
        "id": {"dtype": "Int64", "null_percent": 0.0},
        # json_blob / int_array are TEXT in staging — the type: override is DB-only
        "payload": {"dtype": "String", "null_percent": 0.0},
        "tags": {"dtype": "String", "null_percent": 0.0},
    })
    violations, _ = verify_stats_against_config(table_def, stats)
    assert violations == []


def test_stats_contract_catches_wrong_dtype():
    table_def = {"columns": [{"name": "n", "provider": "random_int"}]}
    stats = _stats(1000, {"n": {"dtype": "String", "null_percent": 0.0}})
    violations, _ = verify_stats_against_config(table_def, stats)
    assert any("expected staging dtype Int64" in v for v in violations)


def test_stats_contract_catches_missing_column():
    table_def = {"columns": [{"name": "ghost", "provider": "sequence"}]}
    stats = _stats(1000, {"other": {"dtype": "Int64", "null_percent": 0.0}})
    violations, _ = verify_stats_against_config(table_def, stats)
    assert any("absent from generated data" in v for v in violations)


def test_stats_contract_catches_null_rate_drift():
    table_def = {"columns": [{"name": "c", "provider": "random_int",
                              "null_probability": 0.3}]}
    stats = _stats(10000, {"c": {"dtype": "Int64", "null_percent": 0.0}})
    violations, _ = verify_stats_against_config(table_def, stats)
    assert any("null" in v.lower() for v in violations)


def test_stats_contract_null_rate_within_tolerance_passes():
    table_def = {"columns": [{"name": "c", "provider": "random_int",
                              "null_probability": 0.3}]}
    stats = _stats(10000, {"c": {"dtype": "Int64", "null_percent": 0.31}})
    violations, _ = verify_stats_against_config(table_def, stats)
    assert violations == []


def test_stats_contract_skips_data_dependent_provider():
    table_def = {"columns": [{"name": "c", "provider": "choice"}]}
    stats = _stats(1000, {"c": {"dtype": "Int64", "null_percent": 0.0}})
    violations, skipped = verify_stats_against_config(table_def, stats)
    assert violations == []
    assert any("c:" in s for s in skipped)


# --------------------------------------------------------------------------
# Postgres type-override mapping + live-schema contract
# --------------------------------------------------------------------------

def test_expected_pg_type_jsonb_and_array():
    assert expected_pg_type("jsonb") == ("jsonb", None)
    assert expected_pg_type("integer[]") == ("ARRAY", "_int4")
    assert expected_pg_type("bigint") == ("bigint", None)


def test_pg_schema_contract_clean_passes():
    table_def = {"columns": [
        {"name": "payload", "provider": "json_blob", "type": "jsonb"},
        {"name": "tags", "provider": "int_array", "type": "integer[]"},
        {"name": "n", "provider": "random_int"},  # no override -> not checked
    ]}
    pg_columns = {
        "payload": {"data_type": "jsonb", "udt_name": "jsonb"},
        "tags": {"data_type": "ARRAY", "udt_name": "_int4"},
        "n": {"data_type": "bigint", "udt_name": "int8"},
    }
    assert verify_pg_schema(table_def, pg_columns) == []


def test_pg_schema_contract_catches_degraded_jsonb():
    # The exact bug class: type: jsonb declared, but the column landed as text.
    table_def = {"columns": [{"name": "payload", "provider": "json_blob",
                              "type": "jsonb"}]}
    pg_columns = {"payload": {"data_type": "text", "udt_name": "text"}}
    violations = verify_pg_schema(table_def, pg_columns)
    assert any("jsonb" in v and "text" in v for v in violations)


def test_pg_schema_contract_catches_missing_column():
    table_def = {"columns": [{"name": "payload", "provider": "json_blob",
                              "type": "jsonb"}]}
    violations = verify_pg_schema(table_def, {})
    assert any("absent from the loaded Postgres table" in v for v in violations)
