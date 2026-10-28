"""Cold-cache contract for the DuckDB clients.

OS page-cache eviction is not implemented, so every caller must state `cold`,
and a cold request fails instead of silently running warm.
"""
import subprocess
from unittest.mock import patch

import pytest

from sql_benchmarks.resources.duckdb_client import DuckDBClient
from sql_benchmarks.resources.duckdb_version_client import DuckDBVersionClient


def test_duckdb_client_requires_cold_flag(tmp_path):
    with pytest.raises(TypeError, match="cold"):
        DuckDBClient(data_folder=str(tmp_path)).run_query(sql="SELECT 1", partition_key="p1")


def test_version_client_requires_cold_flag(tmp_path):
    client = DuckDBVersionClient(data_folder=str(tmp_path), version="1.5.3")
    with pytest.raises(TypeError, match="cold"):
        client.run_query(sql="SELECT 1", partition_key="p1")


def test_duckdb_client_refuses_cold_request(tmp_path):
    with pytest.raises(NotImplementedError, match="page-cache eviction"):
        DuckDBClient(data_folder=str(tmp_path)).run_query(
            sql="SELECT 1", partition_key="p1", cold=True)


def test_version_client_refuses_cold_request_before_spawning(tmp_path):
    client = DuckDBVersionClient(data_folder=str(tmp_path), version="1.5.3")
    with patch("subprocess.run") as run, \
         pytest.raises(NotImplementedError, match="page-cache eviction"):
        client.run_query(sql="SELECT 1", partition_key="p1", cold=True)
    run.assert_not_called()


# ---------------------------------------------------------------------------
# Version client: a worker that never ran is not a DNF
# ---------------------------------------------------------------------------

def _completed(returncode, stderr):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


def test_version_client_raises_when_worker_did_not_run(tmp_path):
    client = DuckDBVersionClient(data_folder=str(tmp_path), version="9.9.9")
    uv_failure = "error: No solution found when resolving `--with` dependencies"
    with patch("subprocess.run", return_value=_completed(1, uv_failure)):
        with pytest.raises(RuntimeError, match="worker did not run"):
            client.run_query(sql="SELECT 1", partition_key="p1", cold=False)


def test_version_client_returns_none_when_duckdb_rejects_query(tmp_path):
    client = DuckDBVersionClient(data_folder=str(tmp_path), version="2.0.0")
    worker_error = '{"status": "error", "error": "no such function", "error_type": "CatalogException"}'
    with patch("subprocess.run", return_value=_completed(1, worker_error)):
        assert client.run_query(sql="SELECT f()", partition_key="p1", cold=False) is None
