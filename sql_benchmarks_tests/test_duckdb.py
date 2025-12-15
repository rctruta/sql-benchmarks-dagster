import pytest
from unittest.mock import patch, MagicMock
import os
from sql_benchmarks.resources.base_engine import IBenchmarkEngine 
from sql_benchmarks.resources.duckdb import DuckDBEngine 

# Mock the entire duckdb library and the thrash_os_cache utility
@patch('sql_benchmarks.resources.duckdb.duckdb')
@patch('sql_benchmarks.resources.duckdb.thrash_os_cache')
def test_duckdb_resource_run_query_decoupled(mock_thrash_os_cache, mock_duckdb):
    """
    Validates that DuckDBResource correctly implements the IBenchmarkEngine contract 
    and handles engine-specific parameters (OS thrash) internally.
    """
    
    # 1. Setup
    PARTITION_KEY = "medium_ssd"
    TEST_SQL = "SELECT count(*) FROM test_table"
    DATA_FOLDER = "/tmp/duckdb_data"
    
    # Mock the connection and cursor to avoid hitting the filesystem
    mock_conn = mock_duckdb.connect.return_value.__enter__.return_value
    mock_result = mock_conn.execute.return_value
    mock_result.fetchall.return_value = [] # Mock fetching results

    # Resource instance
    resource = DuckDBResource(data_folder=DATA_FOLDER)

    # 2. Test Case 1: With explicit flood size
    scenario_params_1 = {"flood_size_gb": 4.0, "other_param": 100}
    resource.run_query(
        sql=TEST_SQL, 
        partition_key=PARTITION_KEY, 
        scenario_params=scenario_params_1
    )

    # 3. Assertions (Decoupling Validation)

    # A. ASSERT 1: thrash_os_cache was called with the correct extracted parameter
    mock_thrash_os_cache.assert_called_once_with(override_gb=4.0)

    # B. ASSERT 2: The correct partitioned DB path was used
    expected_db_path = os.path.join(DATA_FOLDER, f"benchmark_{PARTITION_KEY}.duckdb")
    mock_duckdb.connect.assert_called_once_with(expected_db_path, read_only=True)

    # C. ASSERT 3: The SQL was executed and fetched
    mock_conn.execute.assert_called_once_with(TEST_SQL)
    mock_result.fetchall.assert_called_once()
    
    # 4. Cleanup/Reset (If using `unittest` or similar manual mocks)
    mock_thrash_os_cache.reset_mock()
    mock_duckdb.connect.reset_mock()

    # 5. Test Case 2: Without flood size
    scenario_params_2 = {"other_param": 200}
    resource.run_query(
        sql=TEST_SQL, 
        partition_key=PARTITION_KEY, 
        scenario_params=scenario_params_2
    )

    # ASSERT 4: thrash_os_cache was called with None (letting the utility auto-detect)
    mock_thrash_os_cache.assert_called_once_with(override_gb=None)
    
    # ASSERT 5: The engine adheres to the ABC interface
    assert isinstance(resource, IBenchmarkEngine)