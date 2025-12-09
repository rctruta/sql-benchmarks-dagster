import pytest
import polars as pl
from unittest.mock import patch, MagicMock
from sql_benchmarks.resources.postgres import PostgresResource

TEST_CONN = "postgresql://postgres:password@localhost:5432/postgres"

def test_execute_query_runs_sql():
    """
    Verifies DDL execution logic.
    Strategy: Patch 'create_engine' (the import), NOT the Pydantic field.
    """
    pg = PostgresResource(connection_string=TEST_CONN)
    
    with patch("sql_benchmarks.resources.postgres.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create.return_value = mock_engine
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        
        pg.execute_query("DROP TABLE t1")
        
        assert mock_conn.execute.called
        # Verify the arguments passed to sqlalchemy.text()
        args = str(mock_conn.execute.call_args[0][0]) 
        assert "DROP TABLE t1" in args

def test_benchmark_query_returns_float():
    """
    Verifies benchmark timing logic.
    """
    pg = PostgresResource(connection_string=TEST_CONN)
    
    with patch("sql_benchmarks.resources.postgres.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        duration = pg.benchmark_query("SELECT 1")
        
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
    
    pg = PostgresResource(connection_string=TEST_CONN)
    
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
        with patch.object(PostgresResource, "_create_schema"):
            with patch.object(PostgresResource, "execute_query"):
                
                pg.bulk_load(str(valid_parquet), "test_table")
        
        # 4. Verify SQL construction
        assert mock_cursor.copy_expert.called
        sql_arg = mock_cursor.copy_expert.call_args[0][0]
        assert "COPY test_table FROM STDIN" in sql_arg

def test_check_port_available_logic():
    """
    Unit test the port check logic (pure python, no Pydantic conflict).
    """
    pg = PostgresResource(connection_string=TEST_CONN)
    
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        
        mock_sock.connect_ex.return_value = 111 # Non-zero = Free
        assert pg._check_port_available(5432) is True