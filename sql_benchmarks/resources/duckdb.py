import duckdb
import os
from dagster import ConfigurableResource
from contextlib import contextmanager

class DuckDBResource(ConfigurableResource):
    data_folder: str

    def _get_db_path(self, partition_key: str):
        """
        Calculates the database file path using the 
        SYMBOLIC partition_key, enforcing the clean contract.
        """
        # The key is expected to be symbolic (e.g., 'tiny_ssd')
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

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