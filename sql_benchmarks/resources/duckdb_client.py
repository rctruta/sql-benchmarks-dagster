import duckdb
import os
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional
from ..utils.system import thrash_os_cache
from .base_engine import IBenchmarkEngine

# Note: DuckDBClient does NOT inherit ConfigurableResource

# ---------------------------------------------------------------------------
# Module-level partition tracker (mirrors the TypeDBEngine pattern).
# The first bulk_load call for a given partition deletes the existing .duckdb
# file (clean slate).  Subsequent calls for the same partition just add tables
# via CREATE OR REPLACE TABLE, so multi-table experiments (e.g. hypergraph
# supply chain) work correctly.  Cleared naturally between runs because each
# execute_run.py invocation starts a fresh Python process.
# ---------------------------------------------------------------------------
_INITIALIZED_PARTITIONS: set = set()

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

        # First table for this partition: wipe any stale database file for a
        # clean slate.  Subsequent tables are added to the same file via
        # CREATE OR REPLACE TABLE so all tables coexist.
        if partition_key not in _INITIALIZED_PARTITIONS:
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except OSError as e:
                    print(f"[WARN] Could not remove existing DB file {db_path}: {e}")
            _INITIALIZED_PARTITIONS.add(partition_key)

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        sql = f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet('{filepath}')"

        with duckdb.connect(db_path, read_only=False) as con:
            con.execute(sql)
             
    def run_query(self, 
                  sql: str, 
                  partition_key: str, 
                  scenario_params: Dict[str, Any]) -> Optional[float]:
        
        db_path = self._get_db_path(partition_key)
        
        # Enable RW for Sentinel experiments (CREATE TABLE)
        with duckdb.connect(db_path, read_only=False) as con:
            start = time.time()
            # In DuckDB, multiple statements in one string are executed if separated by semicolon
            # .sql() executes them. 
            con.sql(sql).fetchall()
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