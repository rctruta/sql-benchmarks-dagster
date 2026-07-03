"""Tests for capsule_registry.check_registry — the three-way collision classifier.

The rule under test: same 8-char exp_id means "already ran" ONLY if the
archived config parses to the same dict (minus meta) as the submitted one.
Otherwise it's a genuine hash collision and must be refused.
"""
import os

import pytest
import yaml

from sql_benchmarks.capsule_registry import check_registry


def _write_archived(archive_dir: str, exp_id: str, config: dict) -> None:
    os.makedirs(archive_dir, exist_ok=True)
    with open(os.path.join(archive_dir, f"config_{exp_id}.yaml"), "w") as f:
        yaml.dump(config, f, sort_keys=False)


def test_fresh_when_no_archive(tmp_path):
    """No file for this exp_id → status 'fresh', submission proceeds."""
    status = check_registry("abc12345", {"execution": {"engines": ["duckdb"]}}, str(tmp_path))
    assert status == "fresh"


def test_duplicate_on_identical_config(tmp_path):
    """Same dict (minus meta) → 'duplicate' → the safe path today."""
    config = {"execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}}}
    _write_archived(str(tmp_path), "abc12345", config)
    assert check_registry("abc12345", config, str(tmp_path)) == "duplicate"


def test_duplicate_ignores_meta_differences(tmp_path):
    """meta is excluded from the hash (utils/hasher.py:51). Two YAMLs that
    differ ONLY in meta.name should classify as 'duplicate', not 'collision'.
    Otherwise renaming an experiment would trip a false collision alarm."""
    archived = {
        "meta": {"name": "old name", "description": "old"},
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}},
    }
    submitted = {
        "meta": {"name": "new name", "description": "renamed"},
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}},
    }
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "duplicate"


def test_duplicate_ignores_meta_when_only_one_side_has_it(tmp_path):
    """Archived has meta, submitted doesn't (or vice versa) — still duplicate
    if the non-meta content matches."""
    archived = {
        "meta": {"name": "x"},
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}},
    }
    submitted = {
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}},
    }
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "duplicate"


def test_duplicate_across_key_reordering(tmp_path):
    """Python dicts compare equal regardless of key insertion order — same
    experiment written with keys reordered is still a duplicate."""
    archived = {"execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}}}
    submitted = {"execution": {"matrix": {"rows": [1000]}, "engines": ["duckdb"]}}
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "duplicate"


def test_collision_on_different_content(tmp_path):
    """Actually different configs at the same exp_id → 'collision'."""
    archived = {"execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}}}
    submitted = {"execution": {"engines": ["postgres"], "matrix": {"rows": [1000]}}}
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "collision"


def test_collision_on_extra_key(tmp_path):
    """Submitted config has an extra key the archived one doesn't → collision.
    (In a real hash-collision scenario, this is the shape of the false-duplicate
    the old existence-check would silently return the wrong capsule for.)"""
    archived = {"execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}}}
    submitted = {
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}},
        "definitions": {"rows": {"tiny": 100}},
    }
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "collision"


def test_collision_on_type_difference(tmp_path):
    """`100` (int) vs `"100"` (string): different Python types → not equal →
    collision. Correctly, because the hasher's json.dumps(sort_keys=True) also
    emits them differently."""
    archived = {"execution": {"engines": ["duckdb"], "matrix": {"rows": [1000]}}}
    submitted = {"execution": {"engines": ["duckdb"], "matrix": {"rows": ["1000"]}}}
    _write_archived(str(tmp_path), "abc12345", archived)
    assert check_registry("abc12345", submitted, str(tmp_path)) == "collision"


def test_unparseable_archive_returns_collision(tmp_path):
    """A corrupt archived config that we cannot verify → 'collision' → refuse.
    Never silently overwrite what we can't compare against."""
    archive_dir = str(tmp_path)
    with open(os.path.join(archive_dir, "config_abc12345.yaml"), "w") as f:
        f.write("meta: {\n  broken: [unclosed\n")  # invalid yaml
    submitted = {"execution": {"engines": ["duckdb"]}}
    assert check_registry("abc12345", submitted, archive_dir) == "collision"
