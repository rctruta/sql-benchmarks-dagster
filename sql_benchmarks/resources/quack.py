import os
from typing import Dict, Any, Optional

from dagster import ConfigurableResource
from pydantic import ConfigDict

from ..utils.system import thrash_os_cache
from .quack_client import QuackClient


class QuackEngine(ConfigurableResource):
    """
    DuckDB-over-Quack: the same storage and SQL dialect as the duckdb engine,
    measured through the Quack client-server protocol (HTTP) instead of
    in-process calls. Comparing 'duckdb' vs 'quack' on identical scenarios
    isolates the protocol cost.

    Uses its OWN data_folder so its database files never contend with the
    in-process duckdb engine's files within the same experiment.
    """
    data_folder: str
    port: int = 9494
    token: str = "sb-local-quack-token"
    model_config = ConfigDict(extra='forbid')

    def _get_client(self) -> QuackClient:
        return QuackClient(data_folder=self.data_folder, port=self.port, token=self.token)

    # --- IBenchmarkEngine Implementation (Delegation) ---

    def get_engine_name(self) -> str:
        return "quack"

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def run_query(self,
                  sql: str,
                  partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """engine_params is the 'quack' namespace — reserved, not yet applied."""
        self.clear_cache()
        client = self._get_client()
        return client.run_query(sql=sql,
                                partition_key=partition_key,
                                engine_params=engine_params)

    def clear_cache(self):
        # OS page cache flush; the per-query server restart in QuackClient
        # provides the engine-level cold start.
        thrash_os_cache()
