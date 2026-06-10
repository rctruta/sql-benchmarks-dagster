import pytest
from unittest.mock import patch, MagicMock
import os
from duckdb import Error

from sql_benchmarks.resources.duckdb_client import DuckDBClient

TEST_DATA_FOLDER = "/tmp/test_duckdb_data"


@pytest.fixture
def mock_duckdb_connect():
    """Mocks duckdb.connect and its connection context manager."""
    with patch("sql_benchmarks.resources.duckdb_client.duckdb") as mock_duckdb:
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []

        ctx = mock_duckdb.connect.return_value
        ctx.__enter__.return_value = mock_conn
        mock_conn.sql.return_value = mock_result

        yield mock_duckdb.connect


@pytest.fixture
def test_data_folder_path():
    return TEST_DATA_FOLDER


# ---------------------------------------------------------------------------
# run_query interface
# ---------------------------------------------------------------------------

def test_run_query_executes_and_returns_duration(mock_duckdb_connect):
    """run_query opens a connection, calls .sql().fetchall(), and returns elapsed time."""
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)

    with patch("time.time", side_effect=[0.0, 1.5]):
        duration = client.run_query(sql="SELECT 1", partition_key="test_part")

    mock_conn = mock_duckdb_connect.return_value.__enter__.return_value
    mock_conn.sql.assert_called_once_with("SELECT 1")
    mock_conn.sql.return_value.fetchall.assert_called_once()
    assert duration == pytest.approx(1.5)


def test_run_query_accepts_pg_settings_and_ignores_them(mock_duckdb_connect):
    """pg_settings is accepted for interface symmetry but has no effect on execution."""
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)
    pg_settings = {"work_mem": "256MB", "max_parallel_workers_per_gather": 4}

    with patch("time.time", side_effect=[0.0, 0.2]):
        duration = client.run_query(sql="SELECT 1", partition_key="test_part", pg_settings=pg_settings)

    # No extra calls — settings must not have triggered any SET commands
    mock_conn = mock_duckdb_connect.return_value.__enter__.return_value
    mock_conn.sql.assert_called_once_with("SELECT 1")
    assert duration == pytest.approx(0.2)


def test_run_query_propagates_duckdb_error(mock_duckdb_connect):
    """Native duckdb errors are not swallowed or wrapped."""
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)

    mock_conn = mock_duckdb_connect.return_value.__enter__.return_value
    mock_conn.sql.side_effect = Error("Table not found.")

    with pytest.raises(Error, match="Table not found."):
        client.run_query(sql="SELECT * FROM missing", partition_key="test_part")


# ---------------------------------------------------------------------------
# Path calculation
# ---------------------------------------------------------------------------

def test_get_db_path_partitioned(test_data_folder_path):
    client = DuckDBClient(data_folder=test_data_folder_path)
    path = client._get_db_path("medium__work_mem_64MB")
    assert path == os.path.join(test_data_folder_path, "benchmark_medium__work_mem_64MB.duckdb")


def test_get_db_path_unpartitioned(test_data_folder_path):
    client = DuckDBClient(data_folder=test_data_folder_path)
    path = client._get_db_path(None)
    assert path == os.path.join(test_data_folder_path, "benchmark.duckdb")


def test_get_db_path_different_keys_differ(test_data_folder_path):
    client = DuckDBClient(data_folder=test_data_folder_path)
    assert client._get_db_path("part_a") != client._get_db_path("part_b")


# ---------------------------------------------------------------------------
# execute_on_file delegation
# ---------------------------------------------------------------------------

def test_execute_on_file_delegates_to_get_connection():
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)
    db_path = os.path.join(TEST_DATA_FOLDER, "mock.duckdb")

    with patch.object(client, "get_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        client.execute_on_file("CREATE TABLE t (id INT)", db_path)

        mock_get_conn.assert_called_once_with(db_path)
        mock_conn.execute.assert_called_once_with("CREATE TABLE t (id INT)")
