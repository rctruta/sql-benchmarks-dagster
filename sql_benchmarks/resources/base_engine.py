# sql_benchmarks_dagster/resources/base_engine.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class IBenchmarkEngine(Protocol):
    """
    ABSTRACT BASE CLASS: Defines the mandatory interface for all 
    pluggable benchmark engines (SQL, Graph, etc.).
    
    The benchmark and ingestion factories rely ONLY on this contract.
    """

    @abstractmethod
    def get_engine_name(self) -> str:
        """Returns the canonical name of the engine (e.g., 'duckdb', 'postgres', 'neo4j')."""
        raise NotImplementedError

    @abstractmethod
    def clear_cache(self):
        """
        Resets the database state to ensure a 'Cold Cache' benchmark.
        """
        pass   
     
    @abstractmethod
    def run_query(self,
                  sql: str,
                  partition_key: str,
                  pg_settings: Dict[str, Any] = None) -> Optional[float]:
        """
        Executes the query for benchmarking and forces result collection.

        Args:
            sql (str): The SQL or Cypher query to run.
            partition_key (str): The unique key for the scenario/database instance.
            pg_settings (Dict): Engine session settings prepared by config_loader
                                (currently Postgres session parameters). Engines
                                that do not use them MUST still accept the kwarg
                                and ignore it — the benchmark factory passes it
                                to every engine.

        Returns:
            Optional[float]: The execution duration in seconds, if measured internally.
        """
        raise NotImplementedError

    @abstractmethod
    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str) -> None:
        """
        Handles the engine-specific logic for efficiently loading a file (e.g., Parquet).
        
        Note: The partition_key is required to map the ingestion to the correct physical 
              database file (e.g., benchmark_tiny_ssd.duckdb).
        """
        raise NotImplementedError