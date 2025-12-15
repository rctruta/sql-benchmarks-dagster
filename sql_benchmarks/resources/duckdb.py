import duckdb
import os
import time
from dagster import ConfigurableResource
from contextlib import contextmanager
from typing import Dict, Any, Optional
# from .base_engine import IBenchmarkEngine 
from ..utils.system import thrash_os_cache 

class DuckDBEngine(ConfigurableResource): 

    data_folder: str
    
    def get_engine_name(self) -> str:
        return "duckdb"

    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str) -> None:
        """
        Implementation for ingestion, mapping data to the partitioned DuckDB file.
        """
        # Determine the target DB path using the partition key
        db_path = self._get_db_path(partition_key)
        
        # Ensure directory exists for creation
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # SQL to load Parquet directly into the target table name
        sql = f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet('{filepath}')"
        
        # Execute against the partitioned DB file
        with duckdb.connect(db_path, read_only=False) as con:
             con.execute(sql)
             
    def run_query(self, 
                  sql: str, 
                  partition_key: str, 
                  scenario_params: Dict[str, Any]) -> Optional[float]:
        """
        Core benchmarking method required by the ABC.
        Encapsulates the DuckDB-specific OS cache thrashing.
        """
        db_path = self._get_db_path(partition_key)
        
        flood_size_gb = scenario_params.get("flood_size_gb")
        thrash_os_cache(override_gb=flood_size_gb)
        
        # 2. Execution Logic
        with duckdb.connect(db_path, read_only=True) as con:
            start = time.time()
            result = con.execute(sql)
            
            # Force data transfer to measure actual execution time
            result.fetchall()
            end = time.time()
            
            return end - start # Return the duration, though the factory will usually time it again
            
    # --- Internal/Utility Methods (Keep them for now) ---
    
    def _get_db_path(self, partition_key: str):
        """Calculates the database file path using the partition_key."""
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

    # Note: Legacy methods like execute_query, benchmark_query, etc. 
    # should be removed/deprecated to enforce the use of IBenchmarkEngine methods. 
    # For now, we leave them but rely on run_query and bulk_load.
    def benchmark_query(self, sql: str, partition_key: str = None):
        """LEGACY METHOD: Call the stable execute_query instead."""
        # This is the stable way to deprecate: call the new method internally.
        self.execute_query(sql, partition_key=partition_key, read_only=True, is_benchmark=True) 

    # --- FIX: Make execute_query the central, stable I/O point ---
    def execute_query(self, sql: str, partition_key: str = None, read_only: bool = False, is_benchmark: bool = False):
        db_path = self._get_db_path(partition_key)
        
        # Ensure directory exists only for write/creation operations
        if not read_only:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        with duckdb.connect(db_path, read_only=read_only) as con:
            result = con.execute(sql)
            
            # If this is a benchmark (read-only query), force fetchall for execution timing
            if is_benchmark:
                result.fetchall()
    
    @contextmanager
    def get_connection(self, db_path: str, read_only: bool = False):
        """
        NEW: Yields a connection to a specific path. 
        This breaks the dependency on 'data_folder'.
        """
        con = duckdb.connect(db_path, read_only=read_only)
        try:
            yield con
        finally:
            con.close()

    def execute_on_file(self, sql: str, target_path: str):
        """
        NEW: Execute SQL against a specific file path provided by the caller.
        """
        with self.get_connection(target_path) as con:
            con.execute(sql)    