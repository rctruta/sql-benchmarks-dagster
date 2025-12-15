# sql_benchmarks_dagster/resources/postgres.py (Configuration and Delegation)
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
import socket 
from .base_engine import IBenchmarkEngine # We import it for type hinting, but don't inherit
from .postgres_client import PostgresClient 
from pydantic import ConfigDict

# Inheritance is simplified to prevent MRO conflicts. It satisfies IBenchmarkEngine via Protocol.
class PostgresEngine(ConfigurableResource): 
    
    # --- CONFIGURATION (Immutable) ---
    connection_string: str
    container_name: str = "benchmark_postgres"
    model_config = ConfigDict(extra='forbid')
    
    # --- FACTORY METHOD ---
    def _get_client(self) -> PostgresClient:
        return PostgresClient(self.connection_string)

    # --- IBenchmarkEngine Implementation (Delegation) ---
    def run_query(self, sql: str, partition_key: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        client = self._get_client() 
        return client.run_query(sql=sql, scenario_params=scenario_params)

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def get_engine_name(self) -> str:
        return "postgres"
    
    # --- EXTERNAL/SYSTEM/CONFIG HELPERS (Remain Here) ---
    def clear_cache(self):
        """External control logic (e.g., Docker commands)."""
        pass 

    def _check_port_available(self, port: int, host: str = 'localhost') -> bool:
        """Utility function for checking external system state (the port)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect_ex((host, port))
            return True 
        finally:
            sock.close()