# sql_benchmarks_dagster/tests/resources/test_client_duckdb.py
import pytest
from unittest.mock import patch, MagicMock
import os
import time
from duckdb import Error

# Adjust import path as necessary
from sql_benchmarks.resources.duckdb_client import DuckDBClient

# --- CONSTANTS ---
TEST_DATA_FOLDER = "/tmp/test_duckdb_data"
TEST_DB_PATH = os.path.join(TEST_DATA_FOLDER, "benchmark_test_part.duckdb")

# --- FIXTURES ---

@pytest.fixture
def clean_data_folder():
    """Ensures a clean folder for DuckDB file creation."""
    if os.path.exists(TEST_DATA_FOLDER):
        for f in os.listdir(TEST_DATA_FOLDER):
            os.remove(os.path.join(TEST_DATA_FOLDER, f))
    os.makedirs(TEST_DATA_FOLDER, exist_ok=True)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture
def test_data_folder_path():
    """Returns the global test data folder path."""
    return TEST_DATA_FOLDER

@pytest.fixture
def mock_db_path(test_data_folder_path):
    """Returns a specific mock database path using the folder fixture."""
    return os.path.join(test_data_folder_path, "mock_test.duckdb")

@pytest.fixture
def mock_duckdb_connect():
    """Mocks duckdb.connect and its connection context manager."""
    with patch("sql_benchmarks.resources.duckdb_client.duckdb") as mock_duckdb:
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [] 
        
        context_manager_mock = mock_duckdb.connect.return_value
        context_manager_mock.__enter__.return_value = mock_conn
        mock_conn.execute.return_value = mock_result
        
        yield mock_duckdb.connect

# --- TESTS ---

def test_duckdb_client_run_query_execution_and_timing(mock_duckdb_connect):
    """
    Validates that the DuckDBClient correctly calls connect/execute and measures time.
    """
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)
    TEST_SQL = "SELECT 1"
    
    with patch('time.time', side_effect=[0, 1.5]): 
        duration = client.run_query(
            sql=TEST_SQL, 
            partition_key="test_part", 
            scenario_params={"flood_size_gb": 0}
        )

    mock_duckdb_connect.assert_called_once()
    mock_duckdb_connect.return_value.__enter__.return_value.execute.assert_called_once()
    assert duration == 1.5

def test_duckdb_client_execute_on_file_delegation(mock_db_path):
    """
    Verifies that execute_on_file correctly delegates to get_connection.
    """
    # Uses mock_db_path fixture defined above
    client = DuckDBClient(data_folder=os.path.dirname(mock_db_path))
    TEST_SQL = "CREATE TABLE T"

    with patch.object(client, 'get_connection') as mock_get_connection:
        mock_conn = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn

        client.execute_on_file(TEST_SQL, mock_db_path)

        mock_get_connection.assert_called_once_with(mock_db_path)
        mock_conn.execute.assert_called_once_with(TEST_SQL)

def test_duckdb_client_propagates_duckdb_error(mock_duckdb_connect):
    """
    Ensures that the client does not hide or wrap a native duckdb error.
    """
    client = DuckDBClient(data_folder=TEST_DATA_FOLDER)
    TEST_SQL = "SELECT * FROM non_existent_table"
    
    mock_conn = mock_duckdb_connect.return_value.__enter__.return_value
    mock_conn.execute.side_effect = Error("Database table not found.")
    
    with pytest.raises(Error) as excinfo:
        client.run_query(
            sql=TEST_SQL, 
            partition_key="test_part", 
            scenario_params={}
        )

    assert "Database table not found." in str(excinfo.value)
    mock_duckdb_connect.assert_called_once()    

def test_duckdb_client_path_calculation(test_data_folder_path):
    """
    Verifies the _get_db_path utility adheres to the partitioning contract.
    """
    client = DuckDBClient(data_folder=test_data_folder_path)
    
    expected_partitioned_path = os.path.join(test_data_folder_path, "benchmark_test_part.duckdb")
    expected_unpartitioned_path = os.path.join(test_data_folder_path, "benchmark.duckdb")
    
    path_partitioned = client._get_db_path("test_part")
    assert path_partitioned == expected_partitioned_path
    
    path_unpartitioned = client._get_db_path(None)
    assert path_unpartitioned == expected_unpartitioned_path
    
    path_other = client._get_db_path("other_part")
    assert path_partitioned != path_other