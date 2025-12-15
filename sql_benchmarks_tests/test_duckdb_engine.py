# sql_benchmarks_dagster/tests/resources/test_duckdb_engine.py
import os
from unittest.mock import patch, MagicMock
from sql_benchmarks.resources.duckdb import DuckDBEngine

TEST_CONN = "/tmp/test_data"

def test_duckdb_path_isolation_contract():
    """
    Verify DuckDB resource correctly uses the symbolic partition key for isolation,
    and handles unpartitioned paths.
    """
    mock_data_folder = "/tmp/data/duckdb_isolation"
    
    # 1. Instantiate the Resource
    db_resource = DuckDBEngine(data_folder=mock_data_folder)

    # 2. Test Partitioned Path (Symbolic Key Contract)
    partition_key_1 = "tiny_ssd_pg"
    path_1 = db_resource._get_db_path(partition_key_1)
    
    # Assert correct structure and use of symbolic key
    expected_path_1 = os.path.join(mock_data_folder, "benchmark_tiny_ssd_pg.duckdb")
    assert path_1 == expected_path_1

    # 3. Test Isolation (Ensures two keys generate distinct paths)
    partition_key_2 = "medium_hdd_duck"
    path_2 = db_resource._get_db_path(partition_key_2)

    expected_path_2 = os.path.join(mock_data_folder, "benchmark_medium_hdd_duck.duckdb")
    assert path_2 == expected_path_2
    assert path_1 != path_2

    # 4. Test Unpartitioned Path (Fallback)
    path_unpartitioned = db_resource._get_db_path(None)
    expected_path_unpartitioned = os.path.join(mock_data_folder, "benchmark.duckdb")
    assert path_unpartitioned == expected_path_unpartitioned        

def test_duckdb_engine_delegates_run_query(mock_duckdb_connect):
    """Verifies that the DuckDBEngine delegates the run_query call to the Client."""
    
    # 1. Mock the Client class where it is defined, to intercept instantiation
    with patch("sql_benchmarks.resources.duckdb.DuckDBClient") as MockClientClass:
        
        # Configure the mock instance that the Engine will use
        mock_instance = MockClientClass.return_value
        mock_instance.run_query.return_value = 2.5 # Set a dummy return value
        
        # 2. Instantiate the Engine
        engine = DuckDBEngine(data_folder=TEST_CONN)
        
        # Define parameters to check if they were passed correctly
        test_params = {"flood_size_gb": 4}
        TEST_SQL = "SELECT count(*)"

        # 3. Execution
        result = engine.run_query(
            sql=TEST_SQL, 
            partition_key="large_ssd", 
            scenario_params=test_params
        )
        
        # 4. Assertions
        
        # Assert the Engine called the Client class factory once with the correct config
        MockClientClass.assert_called_once_with(data_folder=TEST_CONN)
        
        # Assert the Engine delegated the call correctly to the Client instance
        mock_instance.run_query.assert_called_once_with(
            sql=TEST_SQL,
            partition_key="large_ssd",
            scenario_params=test_params
        )
        
        # Assert the result came from the Client
        assert result == 2.5

def test_duckdb_engine_returns_correct_name():
    """Verifies the Engine fulfills the IBenchmarkEngine contract for naming."""
    engine = DuckDBEngine(data_folder="/tmp/data")
    assert engine.get_engine_name() == "duckdb"

def test_duckdb_path_isolation_contract():
    """
    Verify DuckDB resource correctly uses the symbolic partition key for isolation,
    and handles unpartitioned paths. This unit tests the Engine's internal path 
    calculation utility, confirming isolation integrity.
    """
    
    mock_data_folder = "/tmp/data/duckdb_isolation"
    
    # 1. Instantiate the Resource
    db_resource = DuckDBEngine(data_folder=mock_data_folder)

    # 2. Test Partitioned Path (Symbolic Key Contract)
    partition_key_1 = "tiny_ssd_pg"
    path_1 = db_resource._get_db_path(partition_key_1)
    
    # Assert correct structure and use of symbolic key
    expected_path_1 = os.path.join(mock_data_folder, "benchmark_tiny_ssd_pg.duckdb")
    assert path_1 == expected_path_1

    # 3. Test Isolation (Ensures two keys generate distinct paths)
    partition_key_2 = "medium_hdd_duck"
    path_2 = db_resource._get_db_path(partition_key_2)

    expected_path_2 = os.path.join(mock_data_folder, "benchmark_medium_hdd_duck.duckdb")
    assert path_2 == expected_path_2
    assert path_1 != path_2

    # 4. Test Unpartitioned Path (Fallback)
    path_unpartitioned = db_resource._get_db_path(None)
    expected_path_unpartitioned = os.path.join(mock_data_folder, "benchmark.duckdb")
    assert path_unpartitioned == expected_path_unpartitioned            