"""Tests for the shared validate_experiment_config contract.

Called by both the API submission handler (sql_benchmarks/api/routers/experiments.py)
and the executor entry (sql_benchmarks/config_loader.py). Both surfaces enforce
the same contract — no config that would crash the executor at run time can be
accepted at submission time.
"""
import pytest

from sql_benchmarks.validation import validate_experiment_config


def _minimal_valid_config():
    """Smallest config that passes both schema and semantic validation.

    Uses the alias form for `table.rows` — literals are rejected (see
    test_literal_table_rows_rejected below and validation._check_table_rows_are_aliases)."""
    return {
        "meta": {"name": "test"},
        "dataset": {
            "source": "sql_benchmarks.plugins.data_sources.declarative_gen",
            "tables": {
                "t1": {
                    "rows": "rows",
                    "columns": [
                        {"name": "id", "provider": "sequence", "primary_key": True},
                    ],
                },
            },
        },
        "definitions": {
            "rows": {"medium": 1000},
        },
        "execution": {
            "engines": ["duckdb"],
            "test_suite": "selectivity",
            "matrix": {"rows": ["medium"]},
        },
    }


def test_valid_config_passes():
    validate_experiment_config(_minimal_valid_config())


def test_missing_matrix_rejected():
    """The exact failure yesterday: agent submitted YAML without execution.matrix,
    got 202 Accepted, then executor crashed. After TODO #1 fix, submission itself
    is rejected with a semantic-error message."""
    config = _minimal_valid_config()
    del config["execution"]["matrix"]
    with pytest.raises(ValueError, match=r"matrix"):
        validate_experiment_config(config, source_label="api_submission")


def test_unresolvable_alias_rejected():
    """String matrix values must resolve through the corresponding definitions
    block if one exists — used to be a ConfigLoader-only check."""
    config = _minimal_valid_config()
    config["execution"]["matrix"] = {"rows": ["tiny", "small"]}
    config["definitions"] = {"rows": {"tiny": 100}}  # 'small' is missing
    with pytest.raises(ValueError, match=r"small.*rows"):
        validate_experiment_config(config, source_label="test")


def test_alias_with_no_definitions_treated_as_literal():
    """String matrix values with NO corresponding definitions block are treated
    as literals (matches ConfigLoader behavior). Should not raise."""
    config = _minimal_valid_config()
    config["execution"]["matrix"] = {"partition_disk": ["ssd", "hdd"]}
    # No definitions.partition_disk block — values are literal partition keys
    validate_experiment_config(config)


def test_engine_namespace_matrix_dim_ok():
    """Namespaced engine params (e.g., 'postgres.work_mem') are matrix dimensions
    that don't resolve through definitions; must validate without raising."""
    config = _minimal_valid_config()
    config["execution"]["matrix"] = {
        "rows": [1000],
        "postgres.work_mem": ["4MB", "16MB"],
    }
    validate_experiment_config(config)


def test_schema_layer_still_enforced():
    """The schema layer (ExperimentValidator) is still called first — a config
    with negative rows should be rejected there, not silently pass."""
    config = _minimal_valid_config()
    config["execution"]["matrix"] = {"rows": [-100]}
    with pytest.raises(ValueError):
        validate_experiment_config(config)


def test_broken_foreign_key_rejected():
    """Foreign key validation from ExperimentValidator must still fire through
    the shared function."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["t2"] = {
        "rows": "rows",   # alias — literals now rejected by _check_table_rows_are_aliases
        "columns": [
            {"name": "t1_id", "provider": "foreign_key", "target_table": "nonexistent"},
        ],
    }
    with pytest.raises(ValueError, match=r"[Ff]oreign|FK|nonexistent"):
        validate_experiment_config(config)


def test_literal_table_rows_rejected():
    """`dataset.tables.<name>.rows` must be a string alias, not a literal int.
    Reason: literals silently break the SQL template substitution pipeline
    (see validation._check_table_rows_are_aliases). Rejected at submission
    with a message naming the fix."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["t1"]["rows"] = 100_000
    with pytest.raises(ValueError, match=r"literal 'rows: 100000'"):
        validate_experiment_config(config, source_label="api_submission")


def test_literal_table_rows_error_names_the_fix():
    """The rejection message must be actionable — it tells the caller exactly
    what to change, so the agent's coaching path (PR #106) can route back."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["t1"]["rows"] = 5000
    try:
        validate_experiment_config(config, source_label="test")
    except ValueError as e:
        msg = str(e)
        assert "definitions.rows" in msg
        assert "rows: my_scale" in msg or "alias" in msg
    else:
        pytest.fail("expected ValueError")


def test_table_rows_none_ok():
    """A table with `rows` omitted entirely is not covered by this rule.
    Some tables may be file-backed (paths:) or otherwise not size-driven."""
    config = _minimal_valid_config()
    del config["dataset"]["tables"]["t1"]["rows"]
    validate_experiment_config(config)


def test_boolean_rows_not_treated_as_int():
    """Guard against `isinstance(True, int)` in Python. Booleans in rows are
    semantically invalid but this specific check shouldn't be the one to
    catch them — that's the schema layer's job."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["t1"]["rows"] = True
    # This might fail the schema check, but our literal-rejection message
    # about integers shouldn't fire on a bool (Python quirk: bool is a
    # subclass of int).
    try:
        validate_experiment_config(config)
    except ValueError as e:
        # If it does raise, it should NOT be with our "literal 'rows: True'"
        # message — the check explicitly filters out booleans.
        assert "literal 'rows: True'" not in str(e)
