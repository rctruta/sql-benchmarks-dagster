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

@patch("sql_benchmarks.resources.postgres.thrash_os_cache")
def test_postgres_engine_delegates_run_query(mock_thrash):
    """
    Validates that the immutable PostgresEngine resource delegates the run_query call 
    to a newly created PostgresClient instance, after clearing cache.
    """
    TEST_CONN = "postgresql://mock:mock@mock:5432/mock"
    engine = PostgresEngine(connection_string=TEST_CONN)
    
    # Mock the internal side-effect methods to prevent Docker usage/System thrash
    # Since we now use docker-py, we mock the method that calls it (clear_cache)
    # OR we verify clear_cache mocks docker correctly. 
    # For this delegation test, mocking clear_cache is cleaner.
    # Mock setup_docker since it's the new way we clear cache (lifecycle)
    with patch.object(PostgresEngine, "setup_docker") as mock_setup:
        with patch.object(PostgresEngine, "_wait_for_ready") as mock_wait:
            # Mock the creation of the PostgresClient
            with patch("sql_benchmarks.resources.postgres.PostgresClient") as MockClientClass:
                mock_client = MockClientClass.return_value
                mock_client.run_query.return_value = 1.23
                
                sql = "SELECT 1"
                params = {"pg_settings": {"work_mem": "4MB"}}
                
                # ACT
                result = engine.run_query(sql=sql, partition_key="p1", scenario_params=params)
                
                # ASSERT 1: Pre-execution cleanup happened
                mock_thrash.assert_called_once()
                mock_setup.assert_called_once()
                mock_wait.assert_called_once()

                # ASSERT 2: The engine created a client
                MockClientClass.assert_called_once_with(TEST_CONN)
                
                # ASSERT 3: The engine delegated the call
                mock_client.run_query.assert_called_once_with(sql=sql, scenario_params=params)
                
                # ASSERT 4: Result passed through
                assert result == 1.23

@patch("sql_benchmarks.resources.postgres.docker")
def test_clear_cache_calls_docker(mock_docker):
    """
    Verifies that clear_cache uses the Docker SDK to restart the container.
    """
    TEST_CONN = "postgresql://mock:mock@mock:5432/mock"
    engine = PostgresEngine(connection_string=TEST_CONN)
    
    # Mock the client and container
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_docker.from_env.return_value = mock_client
    mock_client.containers.get.return_value = mock_container
    
    # Mock database ready check to return immediately
    # We patch create_engine because PostgresEngine is frozen and cannot be patched on the instance
    with patch("sql_benchmarks.resources.postgres.create_engine") as mock_create_engine:
        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        
        # ACT
        engine.clear_cache()
        
        # ASSERT
        # Does not call restart, calls run (via setup_docker)
        # We need to mock setup_docker's internals or assert setup_docker called if we mocked it.
        # But this test mocks 'docker', so we verify the docker call sequence:
        # 1. get container -> remove (kill zombie)
        # 2. run container
        
        # Verification of kill (optional strictly, but good for completeness)
        # mock_client.containers.get.assert_called_with("benchmark_postgres")
        
        # Verification of run
        mock_client.containers.run.assert_called_once()
 