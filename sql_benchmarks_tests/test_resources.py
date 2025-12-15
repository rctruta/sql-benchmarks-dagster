import pytest
import os
import polars as pl
from unittest.mock import patch, MagicMock
from sqlalchemy import text
from sql_benchmarks.resources.base_engine import IBenchmarkEngine 
from sql_benchmarks.resources.postgres import PostgresEngine
from sql_benchmarks.resources.duckdb import DuckDBEngine

TEST_CONN = "postgresql://postgres:password@localhost:5432/postgres"

def test_execute_query_runs_sql():
    pg = PostgresEngine(connection_string=TEST_CONN)
    
    # 1. Patch the internal engine accessor
    with patch.object(pg, "get_sql_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_get_engine.return_value = mock_engine
        
        # 2. Mock the connection context manager used inside _execute_internal
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        pg._execute_internal("DROP TABLE t1")
        
        assert mock_conn.execute.called
        # Verify the arguments passed to sqlalchemy.text()
        args = str(mock_conn.execute.call_args[0][0]) 
        assert "DROP TABLE t1" in args

def test_benchmark_query_returns_float():
    pg = PostgresEngine(connection_string=TEST_CONN)
    
    # Patch create_engine inside the module being tested
    with patch("sql_benchmarks.resources.postgres.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        # Define minimal scenario_params required by run_query
        scenario_params = {} 
        
        # ACT: Use the new public contract method
        duration = pg.run_query("SELECT 1", partition_key="test", scenario_params=scenario_params)
        
        assert isinstance(duration, float)
        assert mock_conn.execute.called
        
def test_postgres_bulk_load_calls_copy(tmp_path):
    """
    Verifies that bulk_load correctly formats the COPY command.
    """
    # 1. Create Valid Parquet
    valid_parquet = tmp_path / "test.parquet"
    df = pl.DataFrame({"id": [1], "val": ["a"]})
    df.write_parquet(valid_parquet)
    
    pg = PostgresEngine(connection_string=TEST_CONN)
    
    # 2. Patch create_engine to catch the COPY command
    with patch("sql_benchmarks.resources.postgres.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_create.return_value = mock_engine
        mock_engine.raw_connection.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # 3. Patch internal logic helper methods
        # This is safe because we patch the CLASS, not the instance
        with patch.object(PostgresEngine, "_create_schema"):
            # The public run_query is now the replacement for the old execute_query
            with patch.object(PostgresEngine, "run_query"): 
                
                # ACT: Must include the required partition_key argument
                pg.bulk_load(str(valid_parquet), "test_table", partition_key="test")
        
        # 4. Verify SQL construction
        assert mock_cursor.copy_expert.called
        sql_arg = mock_cursor.copy_expert.call_args[0][0]
        assert "COPY test_table FROM STDIN" in sql_arg

def test_check_port_available_logic():
    """
    Unit test the port check logic (pure python, no Pydantic conflict).
    """
    pg = PostgresEngine(connection_string=TEST_CONN)
    
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        
        mock_sock.connect_ex.return_value = 111 
        assert pg._check_port_available(5432) is True


