import duckdb
import os
from dagster import ConfigurableResource
from contextlib import contextmanager

class DuckDBResource(ConfigurableResource):
    data_folder: str

    def _get_db_path(self, partition_key: str):
        return os.path.join(self.data_folder, f"benchmark_{partition_key}.duckdb")

    def execute_query(self, sql: str, partition_key: str = None):
        """Legacy method: uses hardcoded paths based on data_folder."""
        if partition_key is None:
            db_path = os.path.join(self.data_folder, "benchmark.duckdb")
        else:
            db_path = self._get_db_path(partition_key)
        
        with duckdb.connect(db_path) as con:
            con.execute(sql)

    def benchmark_query(self, sql: str, partition_key: str = None):
        """Legacy method for benchmarking."""
        if partition_key is None:
            db_path = os.path.join(self.data_folder, "benchmark.duckdb")
        else:
            db_path = self._get_db_path(partition_key)
        
        with duckdb.connect(db_path, read_only=True) as con:
            # Added fetchall to ensure execution completes for timing
            con.execute(sql).fetchall()

    
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