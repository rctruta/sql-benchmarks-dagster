"""Tests for the shared validate_experiment_config contract.

Called by both the API submission handler (sql_benchmarks/api/routers/experiments.py)
and the executor entry (sql_benchmarks/config_loader.py). Both surfaces enforce
the same contract — no config that would crash the executor at run time can be
accepted at submission time.
"""
import pytest

from sql_benchmarks.validation import validate_experiment_config


def _minimal_valid_config():
    """Smallest config that passes both schema and semantic validation."""
    return {
        "meta": {"name": "test"},
        "dataset": {
            "source": "sql_benchmarks.plugins.data_sources.declarative_gen",
            "tables": {
                "t1": {
                    "rows": 1000,
                    "columns": [
                        {"name": "id", "provider": "sequence", "primary_key": True},
                    ],
                },
            },
        },
        "execution": {
            "engines": ["duckdb"],
            "test_suite": "selectivity",
            "matrix": {"rows": [1000]},
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
        "rows": 100,
        "columns": [
            {"name": "t1_id", "provider": "foreign_key", "target_table": "nonexistent"},
        ],
    }
    with pytest.raises(ValueError, match=r"[Ff]oreign|FK|nonexistent"):
        validate_experiment_config(config)
