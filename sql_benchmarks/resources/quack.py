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
    # attach mode (False): client-side planning via USE remote.
    # pushdown (True): SQL text shipped via remote.query() — server-side execution.
    pushdown: bool = False
    model_config = ConfigDict(extra='forbid')

    def _get_client(self) -> QuackClient:
        return QuackClient(data_folder=self.data_folder, port=self.port,
                           token=self.token, pushdown=self.pushdown)

    # --- IBenchmarkEngine Implementation (Delegation) ---

    def get_engine_name(self) -> str:
        return "quack"

    def bulk_load(self, filepath: str, table_name: str, partition_key: str, table_def: dict = None) -> None:
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key, table_def)

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


class QuackAdbcEngine(QuackEngine):
    """Same Quack server + cold-start lifecycle as QuackEngine, but the query is
    measured through GizmoData's ADBC Quack driver (adbc-driver-quack, Arrow)
    instead of the native client. Comparing 'quack_pushdown' vs 'quack_adbc' on
    identical data/SQL/server isolates the result-transport CLIENT — the
    native-vs-standardized question. Own data_folder + port so it never contends
    with the native quack engines."""

    def get_engine_name(self) -> str:
        return "quack_adbc"

    def run_query(self, sql: str, partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        self.clear_cache()
        return self._get_client().run_query_adbc(
            sql=sql, partition_key=partition_key, engine_params=engine_params)
