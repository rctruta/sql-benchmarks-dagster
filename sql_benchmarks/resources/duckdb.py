import duckdb
import os
from dagster import ConfigurableResource

class DuckDBResource(ConfigurableResource):
    # 1. We accept the FOLDER path
    data_folder: str

    def _get_db_path(self, partition_key: str):
        # 2. We calculate the specific file for this partition
        return os.path.join(self.data_folder, f"benchmark_{partition_key}.duckdb")

    def execute_query(self, sql: str, partition_key: str = None):
        """Used for Ingestion."""
        if partition_key is None:
            db_path = os.path.join(self.data_folder, "benchmark.duckdb")
        else:
            db_path = self._get_db_path(partition_key)
        
        with duckdb.connect(db_path) as con:
            con.execute(sql)

    def benchmark_query(self, sql: str, partition_key: str = None):
        """Used for Benchmarking. Forces fetchall for timing."""
        if partition_key is None:
            db_path = os.path.join(self.data_folder, "benchmark.duckdb")
        else:
            db_path = self._get_db_path(partition_key)
        
        # FIX: Enable read_only=True to allow concurrent benchmarks on the same file
        with duckdb.connect(db_path, read_only=True) as con:
            con.execute(sql).fetchall()