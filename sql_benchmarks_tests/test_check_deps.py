"""Tests for scripts/dev/check_deps.py — the dependency-drift guard.

The most important test is `test_current_tree_has_no_drift`: it is the automatic
regression that fails the suite the moment code imports (or runtime-loads) a
package that isn't declared — the exact failure that let the ADBC drivers go
undeclared.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(REPO_ROOT, "scripts", "dev", "check_deps.py")
    spec = importlib.util.spec_from_file_location("check_deps", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load()


def test_norm():
    assert cd._norm("ADBC_Driver-Quack") == "adbc-driver-quack"
    assert cd._norm("Jinja2") == "jinja2"


def test_current_tree_has_no_drift():
    """Every imported + runtime-loaded package in the repo is declared. If this
    fails, run `python scripts/dev/check_deps.py` to see what slipped through."""
    missing_import, missing_runtime = cd.find_missing()
    assert missing_import == {}, f"undeclared imports: {missing_import}"
    assert missing_runtime == {}, f"undeclared runtime-loaded drivers: {missing_runtime}"


def test_runtime_trigger_flags_undeclared_driver(monkeypatch):
    monkeypatch.setattr(cd, "_declared_names", lambda: set())
    monkeypatch.setattr(cd, "_local_modules", lambda: set())
    monkeypatch.setattr(cd, "_imported_top_levels", lambda: set())
    monkeypatch.setattr(cd, "_source_text",
                        lambda: 'pl.read_database_uri(q, uri, engine="adbc")')
    _, missing_runtime = cd.find_missing()
    assert "adbc-driver-postgresql" in missing_runtime
    assert "adbc-driver-manager" in missing_runtime


def test_runtime_trigger_silent_when_declared(monkeypatch):
    monkeypatch.setattr(cd, "_declared_names",
                        lambda: {"adbc-driver-postgresql", "adbc-driver-manager"})
    monkeypatch.setattr(cd, "_local_modules", lambda: set())
    monkeypatch.setattr(cd, "_imported_top_levels", lambda: set())
    monkeypatch.setattr(cd, "_source_text",
                        lambda: 'pl.read_database_uri(q, uri, engine="adbc")')
    _, missing_runtime = cd.find_missing()
    assert missing_runtime == {}


def test_import_flags_undeclared_not_installed(monkeypatch):
    monkeypatch.setattr(cd, "_declared_names", lambda: set())
    monkeypatch.setattr(cd, "_local_modules", lambda: set())
    monkeypatch.setattr(cd, "_imported_top_levels", lambda: {"totallynotapkg_xyz"})
    monkeypatch.setattr(cd, "_source_text", lambda: "")
    missing_import, _ = cd.find_missing()
    assert "totallynotapkg-xyz" in missing_import


def test_import_silent_when_declared_by_name(monkeypatch):
    monkeypatch.setattr(cd, "_declared_names", lambda: {"totallynotapkg-xyz"})
    monkeypatch.setattr(cd, "_local_modules", lambda: set())
    monkeypatch.setattr(cd, "_imported_top_levels", lambda: {"totallynotapkg_xyz"})
    monkeypatch.setattr(cd, "_source_text", lambda: "")
    missing_import, _ = cd.find_missing()
    assert missing_import == {}
