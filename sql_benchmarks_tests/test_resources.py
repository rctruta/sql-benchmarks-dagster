import pytest
import os
import duckdb
import pandas as pd
import polars as pl  # Import polars to patch it correctly
from unittest.mock import MagicMock, patch
from sql_benchmarks.resources.postgres import PostgresResource
from sql_benchmarks.resources.duckdb import DuckDBResource

# ==========================================
# 1. DUCKDB (Integration Test)
# ==========================================
def test_duckdb_resource_execution(tmp_path):
    """Verify DuckDB resource actually writes to a file."""
    db_folder = str(tmp_path)
    resource = DuckDBResource(data_folder=db_folder)
    
    # 1. Ingest (CREATE TABLE)
    resource.execute_query("CREATE TABLE test (i INTEGER)", partition_key="small")
    
    # 2. Verify File Exists
    expected_db = os.path.join(db_folder, "benchmark_small.duckdb")
    assert os.path.exists(expected_db)
    
    # 3. Verify Data
    con = duckdb.connect(expected_db)
    assert "test" in con.execute("SHOW TABLES").fetchall()[0]

# ==========================================
# 2. POSTGRES (Mocked Unit Test)
# ==========================================
# KEY FIX: Patch the class method on the library itself
@patch("polars.DataFrame.write_database")
@patch("sql_benchmarks.resources.postgres.create_engine")
def test_postgres_bulk_load_calls_copy(mock_create_engine, mock_write_db):
    """
    Verify bulk_load calls COPY.
    We mock Polars write_database to prevent real DB connection attempts.
    """
    # Setup Mock Network
    mock_engine = MagicMock()
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    
    # Wire up the mocks
    mock_create_engine.return_value = mock_engine
    mock_engine.raw_connection.return_value = mock_connection
    mock_connection.cursor.return_value = mock_cursor
    
    # Init Resource
    resource = PostgresResource(connection_string="postgresql://fake")
    
    # Create a dummy CSV
    df = pd.DataFrame({"a": [1, 2, 3]})
    df.to_csv("test.csv", index=False)
    
    try:
        # Call the method
        resource.bulk_load("test.csv", "target_table")
        
        # VERIFY 1: Did we try to infer schema?
        # The code uses pl.scan_csv()...collect().write_database()
        # Since collect() returns a DataFrame, our patch on DataFrame.write_database catches it.
        assert mock_write_db.called

        # VERIFY 2: Did we call COPY ... FROM STDIN?
        mock_cursor.copy_expert.assert_called()
        call_args = mock_cursor.copy_expert.call_args[0]
        sql_command = call_args[0]
        
        assert "COPY target_table FROM STDIN" in sql_command
        assert "FORMAT CSV" in sql_command
        
    finally:
        if os.path.exists("test.csv"): os.remove("test.csv")