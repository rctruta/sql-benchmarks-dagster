# sql_benchmarks_dagster/resources/postgres_client.py (Execution and State)
import time
from sqlalchemy import create_engine, text
from typing import Dict, Any, Optional

class PostgresClient:
    """
    STATEFUL CLIENT: Holds the live engine and performs all mutable, connection-based operations.
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine = create_engine(connection_string) 

    # --- CORE CONTRACT EXECUTION ---
    def run_query(self, sql: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        """Handles settings decoupling and query execution."""
        pg_settings = scenario_params.get("pg_settings", {})
        
        with self.engine.connect() as conn:
            if pg_settings:
                for key, val in pg_settings.items():
                    conn.execute(text(f"SET {key} = '{val}'"))
            
            start = time.time()
            conn.execute(text(sql)) 
            return time.time() - start
            
    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        """Core bulk load logic."""
        self._create_schema()
        # NOTE: Placeholder DDL. Replace with your actual table creation DDL.
        self._execute_internal(f"CREATE TABLE IF NOT EXISTS {table_name} (id INT, val TEXT);") 
        self._stream_parquet(filepath, table_name)
        self._execute_internal(f"ANALYZE {table_name};")
        
    # --- INTERNAL HELPERS (Must use connection) ---
    
    def _execute_internal(self, sql: str):
        """Helper for DDL/control queries."""
        with self.engine.connect() as conn:
            conn.execute(text(sql))
            
    def _create_schema(self): 
        """Original logic for creating the benchmark schema."""
        self._execute_internal("CREATE SCHEMA IF NOT EXISTS benchmark")
        
    def _stream_parquet(self, filepath: str, table_name: str):
        """Original logic for using raw_connection for the COPY command."""
        # NOTE: This assumes your original raw connection/copy logic.
        with self.engine.raw_connection() as conn:
            with conn.cursor() as cursor:
                sql = f"COPY {table_name} FROM STDIN (FORMAT 'parquet')"
                cursor.copy_expert(sql, open(filepath, 'rb'))