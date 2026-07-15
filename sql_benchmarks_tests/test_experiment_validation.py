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
                "skewed_data": {
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
    config["dataset"]["tables"]["skewed_data"]["rows"] = 100_000
    with pytest.raises(ValueError, match=r"literal 'rows: 100000'"):
        validate_experiment_config(config, source_label="api_submission")


def test_literal_table_rows_error_names_the_fix():
    """The rejection message must be actionable — it tells the caller exactly
    what to change, so the agent's coaching path (PR #106) can route back."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["skewed_data"]["rows"] = 5000
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
    del config["dataset"]["tables"]["skewed_data"]["rows"]
    validate_experiment_config(config)


def test_boolean_rows_not_treated_as_int():
    """Guard against `isinstance(True, int)` in Python. Booleans in rows are
    semantically invalid but this specific check shouldn't be the one to
    catch them — that's the schema layer's job."""
    config = _minimal_valid_config()
    config["dataset"]["tables"]["skewed_data"]["rows"] = True
    # This might fail the schema check, but our literal-rejection message
    # about integers shouldn't fire on a bool (Python quirk: bool is a
    # subclass of int).
    try:
        validate_experiment_config(config)
    except ValueError as e:
        # If it does raise, it should NOT be with our "literal 'rows: True'"
        # message — the check explicitly filters out booleans.
        assert "literal 'rows: True'" not in str(e)


# ---------------------------------------------------------------------------
# Host-memory guard (fail-closed) — observed live 2026-07-06: a 16GB
# duckdb.memory_limit lane on a 16GB machine froze the host hard.
# ---------------------------------------------------------------------------

import pytest as _pytest

from sql_benchmarks import validation as _validation
from sql_benchmarks.validation import (
    _check_memory_limits_fit_host, _parse_memory_bytes,
)


def test_parse_memory_bytes_units():
    assert _parse_memory_bytes("512MB") == 512 * 1024**2
    assert _parse_memory_bytes("16GB") == 16 * 1024**3
    assert _parse_memory_bytes("1.5GiB") == int(1.5 * 1024**3)
    assert _parse_memory_bytes("fast") is None
    assert _parse_memory_bytes(4) is None


def _cfg(matrix_limits=None, engine_params=None, allow=False):
    cfg = {"execution": {"matrix": {}}, "meta": {}}
    if matrix_limits:
        cfg["execution"]["matrix"]["duckdb.memory_limit"] = matrix_limits
    if engine_params:
        cfg["engine_params"] = engine_params
    if allow:
        cfg["meta"]["allow_high_memory"] = True
    return cfg


def test_memory_limit_above_half_host_ram_rejected(monkeypatch):
    """The exact freeze config: 16GB lane on a 16GB host."""
    monkeypatch.setattr(_validation, "_host_memory_bytes", lambda: 16 * 1024**3)
    with _pytest.raises(ValueError, match="exceeds 50%"):
        _check_memory_limits_fit_host(_cfg(matrix_limits=["512MB", "16GB"]), "t")


def test_memory_limit_within_cap_accepted(monkeypatch):
    monkeypatch.setattr(_validation, "_host_memory_bytes", lambda: 16 * 1024**3)
    _check_memory_limits_fit_host(_cfg(matrix_limits=["512MB", "8GB"]), "t")


def test_engine_params_memory_limit_also_guarded(monkeypatch):
    monkeypatch.setattr(_validation, "_host_memory_bytes", lambda: 16 * 1024**3)
    with _pytest.raises(ValueError, match="engine_params.duckdb.memory_limit"):
        _check_memory_limits_fit_host(
            _cfg(engine_params={"duckdb": {"memory_limit": "12GB"}}), "t")


def test_explicit_override_allows_high_memory(monkeypatch):
    """Fail-closed with a loud, explicit opt-in — not a hidden default."""
    monkeypatch.setattr(_validation, "_host_memory_bytes", lambda: 16 * 1024**3)
    _check_memory_limits_fit_host(
        _cfg(matrix_limits=["16GB"], allow=True), "t")


def test_non_memory_matrix_dimensions_ignored(monkeypatch):
    monkeypatch.setattr(_validation, "_host_memory_bytes", lambda: 16 * 1024**3)
    cfg = {"execution": {"matrix": {"rows": ["small", "large"],
                                    "duckdb.threads": [1, 8]}}, "meta": {}}
    _check_memory_limits_fit_host(cfg, "t")  # no raise
