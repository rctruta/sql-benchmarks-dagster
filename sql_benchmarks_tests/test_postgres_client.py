# sql_benchmarks_tests/test_postgres_client.py (New File)
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import text
from sql_benchmarks.resources.postgres_client import PostgresClient # Assuming the new path

TEST_CONN = "postgresql://postgres:password@localhost:5432/postgres"

@pytest.fixture
def mock_postgres_client_conn():
    """Fixture to mock the connection process for the client."""
    # We are mocking the client's internal engine creation/connection
    with patch("sql_benchmarks.resources.postgres_client.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        
        # Mock engine.connect() context manager
        mock_create.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        # Ensure the client instance uses this mock engine
        mock_engine.execute.return_value = None 
        
        yield mock_conn # Yield the connection object for direct assertion

def get_executed_sqls(mock_conn):
    # Local utility for reading SQL text from mock calls
    sqls = []
    for call in mock_conn.execute.call_args_list:
        sqls.append(str(call[0][0]).strip())
    return sqls

def test_postgres_client_run_query_decouples_pg_settings(mock_postgres_client_conn):
    """
    Validates that PostgresClient correctly extracts and applies pg_settings.
    """
    # 1. Setup
    TEST_SQL = "SELECT count(*) FROM t_recursivity"
    
    # 2. Instantiate the client (This will trigger the mocked create_engine)
    client = PostgresClient(connection_string=TEST_CONN) 
    
    # 3. Scenario Parameters
    scenario_params = {
        "pg_settings": { 
            "work_mem": "256MB", 
            "random_page_cost": 1.1,
            "enable_seqscan": False 
        }
    }
    
    # 4. Execution
    client.run_query(sql=TEST_SQL, scenario_params=scenario_params)

    # 5. Assertions (The final, correct check)
    executed_sqls = get_executed_sqls(mock_postgres_client_conn)
    
    # Ensure all SET commands were executed via the mocked connection
    assert "SET work_mem = '256MB'" in executed_sqls
    assert "SET random_page_cost = '1.1'" in executed_sqls
    assert "SET enable_seqscan = 'False'" in executed_sqls
    assert TEST_SQL in executed_sqls
    assert len(executed_sqls) == 4