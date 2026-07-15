import os
from typing import Dict, Any, Optional

from dagster import ConfigurableResource
from pydantic import ConfigDict

from .malloy_client import MalloyClient
from .storage import MountedVolumeStore


class MalloyEngine(ConfigurableResource):
    """
    DuckDB-over-Malloy-Publisher: the same storage (parquet via DuckDB) as the
    duckdb engine, measured through the Malloy semantic layer (compile + REST)
    instead of in-process SQL. Comparing 'duckdb' vs 'malloy' on identical
    scenarios isolates the semantic-layer cost — the same experimental shape
    as 'duckdb' vs 'quack' for the protocol cost.

    Queries are Malloy text (sql/<suite>/malloy/), not SQL. The measured
    duration includes Malloy compilation and the HTTP round trip by design.
    Cold start = docker restart of the Publisher container per query.
    """
    # The mount contract, declared explicitly: host_dir is where this process
    # writes; container_dir is where the Publisher reads. MountedVolumeStore
    # verifies (via a probe file + docker exec) that the two are the same
    # place before any data is delivered. host_dir must be ROOT-anchored —
    # the per-experiment DATA_DIR sandbox is invisible to the container.
    host_dir: str
    container_dir: str = "/publisher/publisher_data/bench/bench"
    port: int = 4001
    environment: str = "bench"
    package: str = "bench"
    container: str = "sbd-malloy-publisher"
    model_config = ConfigDict(extra='forbid')

    def _get_client(self) -> MalloyClient:
        store = MountedVolumeStore(host_dir=self.host_dir,
                                   container_dir=self.container_dir,
                                   container=self.container)
        return MalloyClient(store=store, port=self.port,
                            environment=self.environment, package=self.package,
                            container=self.container)

    # --- IBenchmarkEngine implementation ---

    def get_engine_name(self) -> str:
        return "malloy"

    def bulk_load(self, filepath: str, table_name: str, partition_key: str,
                  table_def: dict = None) -> None:
        self._get_client().bulk_load(filepath, table_name, partition_key, table_def)

    def run_query(self, sql: str, partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """`sql` carries Malloy query text (the harness renders the malloy
        dialect directory for this engine). engine_params is the 'malloy'
        namespace — reserved, not yet applied."""
        return self._get_client().run_query(
            malloy_query=sql, partition_key=partition_key)

    def clear_cache(self):
        # OS page cache flush; engine-level cold start (container restart)
        # happens inside MalloyClient.run_query.
        from ..utils.system import thrash_os_cache
        thrash_os_cache()
