"""Tests for the storage abstraction and the query-placeholder binding gate.

Both exist because of live failures during the malloy engine bring-up
(2026-07-15): ingestion writing where the server container couldn't see, and
a placeholder-free query file silently detaching from the ingestion DAG.
"""
import os
from unittest import mock

import pytest

from sql_benchmarks.resources.storage import LocalDirStore, MountedVolumeStore
from sql_benchmarks.validation import _check_query_placeholders_bind


# --- storage ---------------------------------------------------------------

def test_local_store_put_file_and_text(tmp_path):
    src = tmp_path / "src.parquet"
    src.write_bytes(b"data")
    store = LocalDirStore(str(tmp_path / "root"))
    dest = store.put_file(str(src), "t.parquet")
    assert open(dest, "rb").read() == b"data"
    dest = store.put_text("hello", "m.malloy")
    assert open(dest).read() == "hello"
    assert store.describe().startswith("LocalDirStore")


def test_mounted_store_verifies_before_first_write(tmp_path):
    store = MountedVolumeStore(str(tmp_path), "/container/dir", "some-container")
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0)
        store.put_text("x", "a.txt")
        store.put_text("y", "b.txt")
    # probe ran exactly once (verified is cached), against the container path
    assert run.call_count == 1
    args = run.call_args[0][0]
    assert args[:3] == ["docker", "exec", "some-container"]
    assert args[-1] == "/container/dir/.sbd_mount_probe"
    # probe file cleaned up host-side
    assert not os.path.exists(tmp_path / ".sbd_mount_probe")


def test_mounted_store_fails_loudly_when_container_cannot_see(tmp_path):
    store = MountedVolumeStore(str(tmp_path), "/container/dir", "some-container")
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=1)
        with pytest.raises(RuntimeError, match="NOT visible"):
            store.put_text("x", "a.txt")
    # nothing was delivered
    assert not os.path.exists(tmp_path / "a.txt")


# --- placeholder binding gate ------------------------------------------------

def _config(engines):
    return {
        "dataset": {"tables": {"analytical_data": {"rows": "rows"}}},
        "execution": {"test_suite": "gate_suite", "engines": engines,
                      "matrix": {"rows": ["small"]}},
        "definitions": {"rows": {"small": 100}},
    }


@pytest.fixture
def suite(tmp_path, monkeypatch):
    """A temp suite dir the validator resolves via SQL_DIR."""
    import sql_benchmarks.utils.common as common
    monkeypatch.setattr(common, "SQL_DIR", str(tmp_path))
    d = tmp_path / "gate_suite"
    (d / "duckdb").mkdir(parents=True)
    return d


def test_bound_query_passes(suite):
    (suite / "duckdb" / "q.sql").write_text(
        "SELECT count(*) FROM {{ analytical_data_table }}")
    _check_query_placeholders_bind(_config(["duckdb"]), "test")


def test_placeholderless_query_rejected(suite):
    (suite / "duckdb" / "q.sql").write_text(
        "SELECT count(*) FROM analytical_data")
    with pytest.raises(ValueError, match="dependency edge"):
        _check_query_placeholders_bind(_config(["duckdb"]), "test")


def test_unknown_table_placeholder_rejected(suite):
    (suite / "duckdb" / "q.sql").write_text(
        "SELECT 1 FROM {{ ghost_table }}")
    with pytest.raises(ValueError, match="ghost"):
        _check_query_placeholders_bind(_config(["duckdb"]), "test")


def test_missing_dialect_dir_rejected(suite):
    (suite / "duckdb" / "q.sql").write_text(
        "SELECT 1 FROM {{ analytical_data_table }}")
    with pytest.raises(ValueError, match="no query files"):
        _check_query_placeholders_bind(_config(["duckdb", "malloy"]), "test")


def test_empty_query_file_rejected(suite):
    (suite / "duckdb" / "q.sql").write_text("")
    with pytest.raises(ValueError, match="no query files"):
        _check_query_placeholders_bind(_config(["duckdb"]), "test")
