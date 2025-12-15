import pytest
import os
import polars as pl
from unittest.mock import patch, MagicMock
from sqlalchemy import text
from sql_benchmarks.resources.base_engine import IBenchmarkEngine 
from sql_benchmarks.resources.postgres import PostgresEngine
from sql_benchmarks.resources.postgres_client import PostgresClient
from sql_benchmarks.resources.duckdb import DuckDBEngine

TEST_CONN = "postgresql://postgres:password@localhost:5432/postgres"


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


@pytest.fixture
def mock_postgres_conn():
    """Fixture to mock the creation of PostgresClient and its connection."""
    
    # 1. Mock the PostgresClient class where it is defined.
    # We are mocking the class definition itself, NOT the module.
    # The Engine calls PostgresClient(...), so we control the class.
    with patch("sql_benchmarks.resources.postgres_client.PostgresClient") as MockClientClass:
        
        # 2. Set up the expected mocks
        mock_instance = MagicMock() # This represents the PostgresClient instance
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        
        # When PostgresClient() is called, return our mock instance
        MockClientClass.return_value = mock_instance
        
        # Configure the mock instance to return the desired objects
        # Set the mock engine attribute
        mock_instance.engine = mock_engine
        
        # Set up the connection context manager for the client's internal methods
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        # 3. Yield the connection object for assertion checks in your tests
        yield mock_conn 

        # NOTE: Your tests must now assert that the mock_conn was called 
        # (which happens implicitly via the yielded value).

def get_executed_sqls(mock_conn):
    """Extracts the string content from all executed sqlalchemy.text() objects."""
    sqls = []
    for call in mock_conn.execute.call_args_list:
        # Extracts the string from the sqlalchemy.text() object
        sqls.append(str(call[0][0]).strip())
    return sqls        

def test_postgres_engine_delegates_run_query():
    """Verifies that the PostgresEngine delegates the run_query call to the Client."""
    
    TEST_CONN = "postgresql://user:pass@host/db"
    
    # 1. Mock the Client class where it is defined, to intercept instantiation
    with patch("sql_benchmarks_dagster.resources.postgres_client.PostgresClient") as MockClientClass:
        
        # Configure the mock instance that the Engine will use
        mock_instance = MockClientClass.return_value
        mock_instance.run_query.return_value = 5.0  # Set a dummy return value
        
        # 2. Instantiate the Engine (which will internally call the mocked Client class)
        engine = PostgresEngine(connection_string=TEST_CONN)
        
        # 3. Execution
        result = engine.run_query(
            sql="SELECT 1", 
            partition_key="key", 
            scenario_params={"pg_settings": {"work_mem": "1GB"}}
        )
        
        # 4. Assertions
        
        # Assert the Engine called the Client class factory once
        MockClientClass.assert_called_once_with(connection_string=TEST_CONN)
        
        # Assert the Engine delegated the call correctly to the Client instance
        mock_instance.run_query.assert_called_once_with(
            sql="SELECT 1",
            scenario_params={"pg_settings": {"work_mem": "1GB"}}
        )
        
        # Assert the result came from the Client
        assert result == 5.0

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
    resource = DuckDBEngine(data_folder=DATA_FOLDER)

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

def test_postgres_engine_delegates_run_query():
    """
    Validates that the immutable PostgresEngine resource delegates the run_query call 
    to a newly created PostgresClient instance.
    """
    TEST_CONN = "postgresql://mock:mock@mock:5432/mock"
    engine = PostgresEngine(connection_string=TEST_CONN)
    
    # Mock the creation of the PostgresClient itself
    with patch("sql_benchmarks.resources.postgres.PostgresClient") as MockClientClass:
        mock_client = MockClientClass.return_value
        
        sql = "SELECT 1"
        params = {"key": "value"}
        
        # ACT
        engine.run_query(sql=sql, partition_key="p1", scenario_params=params)
        
        # ASSERT 1: The engine MUST create a client instance
        MockClientClass.assert_called_once_with(TEST_CONN)
        
        # ASSERT 2: The engine MUST delegate the call to the client
        mock_client.run_query.assert_called_once_with(sql=sql, scenario_params=params)
        
 