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
        
 