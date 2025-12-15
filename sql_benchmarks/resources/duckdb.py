import os
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
from .base_engine import IBenchmarkEngine 
from .duckdb_client import DuckDBClient 
from pydantic import ConfigDict

# The Engine is the immutable facade that satisfies the contract.
class DuckDBEngine(ConfigurableResource): 
    # --- CONFIGURATION (Immutable) ---
    data_folder: str # This is the only configuration it holds
    model_config = ConfigDict(extra='forbid')
    # --- FACTORY METHOD ---
    # This is the Factory Method: It creates the worker/client instance.
    def _get_client(self) -> 'DuckDBClient':
        """Instantiates the stateful client for execution."""
        return DuckDBClient(data_folder=self.data_folder)
    
    # --- IBenchmarkEngine Implementation (Delegation) ---

    def get_engine_name(self) -> str:
        return "duckdb"

    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str) -> None:
        """Delegates the bulk loading operation to the client."""
        client = self._get_client()
        client.bulk_load(filepath, target_table_name, partition_key)
             
    def run_query(self, 
                  sql: str, 
                  partition_key: str, 
                  scenario_params: Dict[str, Any]) -> Optional[float]:
        """Delegates the core benchmarking query execution to the client."""
        client = self._get_client()
        # Delegate the call using the exact method signature
        return client.run_query(sql=sql, 
                                partition_key=partition_key, 
                                scenario_params=scenario_params
                                )

    # --- Utility Methods ---
    
    def _get_db_path(self, partition_key: str):
        """Calculates the database file path using the partition_key (still required for path lookups)."""
        # NOTE: This method can safely remain here as it only involves string manipulation, not I/O.
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

