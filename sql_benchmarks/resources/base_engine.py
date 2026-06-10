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
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """
        Executes the query for benchmarking and forces result collection.

        Args:
            sql (str): The SQL or Cypher query to run.
            partition_key (str): The unique key for the scenario/database instance.
            engine_params (Dict): THIS engine's own tuning namespace, already
                                  sliced by the benchmark factory from the
                                  config's namespaced engine_params block
                                  (e.g. the postgres engine receives
                                  {'work_mem': '64MB'}). Each engine owns its
                                  vocabulary; engines without tunables accept
                                  the kwarg and ignore it.

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