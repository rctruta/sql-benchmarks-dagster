import duckdb
import os
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional
from ..utils.system import thrash_os_cache 
from .base_engine import IBenchmarkEngine 

# Note: DuckDBClient does NOT inherit ConfigurableResource

class DuckDBClient: 
    """
    STATEFUL CLIENT: Holds the execution logic and performs all I/O operations,
    ensuring the Engine resource remains immutable.
    """
    
    def __init__(self, data_folder: str):
        # Configuration required for execution, held on the stateful object
        self.data_folder = data_folder
    
    # --- IBenchmarkEngine Implementation (Execution Logic) ---
    
    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str) -> None:
        db_path = self._get_db_path(partition_key)
        # Ensure directory exists only for write/creation operations
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        sql = f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet('{filepath}')"
        
        with duckdb.connect(db_path, read_only=False) as con:
             con.execute(sql)
             
    def run_query(self, 
                  sql: str, 
                  partition_key: str, 
                  scenario_params: Dict[str, Any]) -> Optional[float]:
        
        db_path = self._get_db_path(partition_key)
        
        # NOTE: thrash_os_cache is I/O logic, so it is correctly moved here.
        flood_size_gb = scenario_params.get("flood_size_gb")
        thrash_os_cache(override_gb=flood_size_gb)
        
        with duckdb.connect(db_path, read_only=True) as con:
            start = time.time()
            result = con.execute(sql)
            result.fetchall()
            end = time.time()
            
            return end - start
            
    # --- Internal/Utility Methods (Moved here) ---
    
    def _get_db_path(self, partition_key: str):
        """Calculates the database file path using the partition_key."""
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

    # --- Utility Methods ---
    # execute_query, get_connection, and execute_on_file are moved here
    # as they all involve I/O and state.

    def execute_query(self, sql: str, partition_key: str = None, read_only: bool = False, is_benchmark: bool = False):
        db_path = self._get_db_path(partition_key)
        
        if not read_only:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        with duckdb.connect(db_path, read_only=read_only) as con:
            result = con.execute(sql)
            if is_benchmark:
                result.fetchall()
    
    @contextmanager
    def get_connection(self, db_path: str, read_only: bool = False):
        con = duckdb.connect(db_path, read_only=read_only)
        try:
            yield con
        finally:
            con.close()

    def execute_on_file(self, sql: str, target_path: str):
        with self.get_connection(target_path) as con:
            con.execute(sql)