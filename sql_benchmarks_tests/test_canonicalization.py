"""Tests for the SET_LIKE_PATHS canonicalization mechanism.

Locks in the contract for `sql_benchmarks/canonicalization.py`:
  - engines list is sorted
  - matrix dimension values are sorted
  - meta is not touched (canonicalize doesn't declare a path into meta)
  - non-declared lists (like table columns) are NOT sorted (order matters there)
  - input is never mutated (canonicalize returns a copy)
  - wildcard * expands to every dict key at that level
"""
from sql_benchmarks.canonicalization import SET_LIKE_PATHS, canonicalize


def test_engines_list_gets_sorted():
    config = {"execution": {"engines": ["postgres", "duckdb", "actian"]}}
    out = canonicalize(config)
    assert out["execution"]["engines"] == ["actian", "duckdb", "postgres"]


def test_matrix_dim_values_get_sorted_via_wildcard():
    """The * wildcard: every matrix dimension's value list gets sorted,
    without having to name each dimension in SET_LIKE_PATHS."""
    config = {
        "execution": {
            "matrix": {
                "rows": ["medium", "large", "small"],
                "postgres.work_mem": ["16MB", "4MB", "64MB"],
            }
        }
    }
    out = canonicalize(config)
    assert out["execution"]["matrix"]["rows"] == ["large", "medium", "small"]
    assert out["execution"]["matrix"]["postgres.work_mem"] == ["16MB", "4MB", "64MB"]


def test_meta_block_is_not_touched():
    """No path in SET_LIKE_PATHS routes through meta. A list inside meta
    (e.g., tags) stays in author order."""
    config = {
        "meta": {"tags": ["z", "a", "m"]},
        "execution": {"engines": ["duckdb"]},
    }
    out = canonicalize(config)
    assert out["meta"]["tags"] == ["z", "a", "m"]


def test_column_lists_are_not_touched():
    """dataset.tables.<t>.columns is a SEQUENCE — position matters (DDL
    column order, primary key column order, composite index prefix). Not
    in SET_LIKE_PATHS. Must not be sorted."""
    config = {
        "dataset": {
            "tables": {
                "t1": {
                    "rows": 1000,
                    "columns": [
                        {"name": "z_id", "provider": "sequence", "primary_key": True},
                        {"name": "a_val", "provider": "random_int"},
                        {"name": "m_cat", "provider": "choice", "options": ["A", "B"]},
                    ],
                }
            }
        }
    }
    out = canonicalize(config)
    # Order preserved: z_id, a_val, m_cat.
    col_names = [c["name"] for c in out["dataset"]["tables"]["t1"]["columns"]]
    assert col_names == ["z_id", "a_val", "m_cat"]


def test_canonicalize_does_not_mutate_input():
    original = {"execution": {"engines": ["postgres", "duckdb"]}}
    snapshot = {"execution": {"engines": ["postgres", "duckdb"]}}
    _ = canonicalize(original)
    assert original == snapshot, "canonicalize must return a copy, not mutate"


def test_missing_paths_are_no_op():
    """A config that doesn't have the declared paths should pass through
    unchanged — no crash on incomplete configs."""
    config = {"meta": {"name": "minimal"}}
    out = canonicalize(config)
    assert out == config


def test_scalar_at_set_like_path_is_left_alone():
    """If a set-like path resolves to a non-list (e.g., a typo made
    engines a string), canonicalize leaves it as-is. Validation will
    catch the type error later; canonicalize's job is to sort lists."""
    config = {"execution": {"engines": "duckdb"}}  # wrong type
    out = canonicalize(config)
    assert out["execution"]["engines"] == "duckdb"


def test_int_values_sort_numerically():
    """Homogeneous numeric matrix dims sort as numbers, not as strings.
    (Avoids the classic [9, 10, 100] → ['10', '100', '9'] pitfall.)"""
    config = {"execution": {"matrix": {"rows": [100, 9, 10]}}}
    out = canonicalize(config)
    assert out["execution"]["matrix"]["rows"] == [9, 10, 100]


def test_registered_paths_are_the_documented_set():
    """The SET_LIKE_PATHS registry is the authoritative list. When adding
    a new set-like field, add a path here — nowhere else. This test
    pins the current set so an accidental removal is caught."""
    assert set(SET_LIKE_PATHS) == {
        "execution.engines",
        "execution.matrix.*",
    }
