import os
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
from .base_engine import IBenchmarkEngine 
from .duckdb_client import DuckDBClient 
from pydantic import ConfigDict
from ..utils.system import thrash_os_cache

# The Engine is the immutable facade that satisfies the contract.
class DuckDBEngine(ConfigurableResource): 
    # --- CONFIGURATION (Immutable) ---
    data_folder: str # This is the configuration it holds
    version: Optional[str] = None # When set, delegates to isolated DuckDBVersionClient
    engine_name: Optional[str] = None # Custom engine name when running multiple versions
    model_config = ConfigDict(extra='forbid')
    # --- FACTORY METHOD ---
    # This is the Factory Method: It creates the worker/client instance.
    def _get_client(self):
        """Instantiates the stateful client for execution."""
        if self.version:
            from .duckdb_version_client import DuckDBVersionClient
            return DuckDBVersionClient(data_folder=self.data_folder, version=self.version)
        return DuckDBClient(data_folder=self.data_folder)
    
    # --- IBenchmarkEngine Implementation (Delegation) ---

    def get_engine_name(self) -> str:
        if self.engine_name:
            return self.engine_name
        return "duckdb"

    def bulk_load(self, filepath: str, table_name: str, partition_key: str, table_def: dict = None) -> None:
        """Delegates the bulk loading operation to the client."""
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key, table_def)

             
    def run_query(self,
                  sql: str,
                  partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """Delegates the core benchmarking query execution to the client."""
        self.clear_cache()

        client = self._get_client()
        # Delegate the call using the exact method signature
        return client.run_query(sql=sql,
                                partition_key=partition_key,
                                engine_params=engine_params,
                                cold=False  # OS page-cache eviction not implemented
                                )

    # --- Utility Methods ---
    
    def _get_db_path(self, partition_key: str):
        """Calculates the database file path using the partition_key (still required for path lookups)."""
        # NOTE: This method can safely remain here as it only involves string manipulation, not I/O.
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

    def clear_cache(self):
        
        thrash_os_cache()
