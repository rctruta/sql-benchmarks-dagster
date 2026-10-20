"""Tests for scripts/dev/check_taxonomy.py — the category-drift guard.

The important one is `test_current_tree_has_no_taxonomy_drift`: it fails the
suite the moment a suite directory exists on disk without a taxonomy entry.

That failure is worth automating because the symptom is silent. CatalogReader
discovers suites by listing SQL_DIR at request time, so a new suite appears in
list_suites immediately and nothing looks broken — while suites_in_category()
and category_counts() never mention it. The suite is invisible to exactly the
category-first discovery the taxonomy exists to provide.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(REPO_ROOT, "scripts", "dev", "check_taxonomy.py")
    spec = importlib.util.spec_from_file_location("check_taxonomy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = _load()


def test_current_tree_has_no_taxonomy_drift():
    """Every on-disk suite is categorised, and every category is declared.
    If this fails, run `python scripts/dev/check_taxonomy.py` — it prints the
    valid category names and a paste-ready stub."""
    drift = ct.find_drift()
    blocking = {k: v for k, v in drift.items() if k in ct.BLOCKING}
    assert blocking == {}, f"taxonomy drift: {blocking}"


def test_disk_scan_matches_the_catalog_definition_of_a_suite():
    """Must agree with CatalogReader._suite_names, or the guard would police a
    different notion of 'suite' than the API serves."""
    from sql_benchmarks.api.data.catalog_reader import CatalogReader
    assert ct.suites_on_disk() == set(CatalogReader()._suite_names())


def test_new_suite_directory_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "suites_on_disk",
                        lambda: ct.suites_on_disk.__wrapped__() if False
                        else set(ct.load_taxonomy()["suites"]) | {"brand_new_suite"})
    drift = ct.find_drift()
    assert "brand_new_suite" in drift.get("uncategorised_suites", [])


def test_deleted_suite_is_detected(monkeypatch):
    """A renamed or removed suite leaves a stale entry that still contributes
    to category counts for something that no longer exists."""
    real = set(ct.load_taxonomy()["suites"])
    monkeypatch.setattr(ct, "suites_on_disk", lambda: real - {sorted(real)[0]})
    drift = ct.find_drift()
    assert drift.get("stale_suite_entries")


def test_stub_leaves_categories_empty():
    """The stub must NOT guess categories. A guessed assignment is confidently
    wrong and nobody reviews it; an empty one forces a decision."""
    stub = ct.stub_for(["some_new_suite"])
    assert "some_new_suite" in stub
    assert "[]" in stub and "TODO" in stub


def test_unused_category_is_reported_but_not_blocking():
    """Pruning the vocabulary is a judgement call, not a defect."""
    assert "unused_categories" not in ct.BLOCKING


def test_uncategorized_bucket_keeps_new_suites_discoverable():
    """A suite with no entry must not silently vanish from category queries."""
    from sql_benchmarks.api.data import taxonomy
    assert taxonomy.suite_categories("definitely_not_a_real_suite") == \
        [taxonomy.UNCATEGORIZED]
