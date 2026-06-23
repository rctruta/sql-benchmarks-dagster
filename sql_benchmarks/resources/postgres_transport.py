# Postgres transport engine: measures the CLIENT/TRANSPORT cost of pulling a
# query result out of Postgres into an in-memory analytical structure — the
# question ADBC exists to answer, asked under the lab's cold-cache discipline.
#
# Same Postgres backend, same query; only the CLIENT varies (psycopg row-fetch,
# ADBC Arrow, connectorx Arrow). The client is chosen per-partition via the
# namespaced matrix dim `postgres_transport.client` (arrives in engine_params).
# This is the Quack "transport-as-variant" intent adapted to a SHARED server:
# each (rows x client) partition loads its own cold table, so there's no
# shared-backend race — unlike registering three engines over one Postgres.
#
# run_query's contract is "execute AND force result collection"; for this engine
# the collection IS the measurement, so it times execute -> fully materialized.
import time
from typing import Any, Dict, Optional

import polars as pl
from sqlalchemy.engine.url import make_url

from .postgres import PostgresEngine


class PostgresTransportEngine(PostgresEngine):
    """Postgres accessed via a pluggable result-transport client. Inherits
    cold-cache (`clear_cache`) and `bulk_load` from PostgresEngine; overrides
    `run_query` to fetch+materialize through the chosen client and time it."""

    def get_engine_name(self) -> str:
        return "postgres_transport"

    def run_query(self, sql: str, partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        params = dict(engine_params or {})
        client = params.pop("client", "psycopg")        # the transport under test
        self.clear_cache()                              # cold: OS + DBMS buffers
        uri = self._runtime_connection_string or self.connection_string
        return self._timed_fetch(client, sql, uri)

    @staticmethod
    def _timed_fetch(client: str, sql: str, uri: str) -> float:
        """Time execute -> result fully materialized in memory (the transport cost)."""
        start = time.time()
        if client == "psycopg":
            import psycopg2
            u = make_url(uri)
            conn = psycopg2.connect(host=u.host, port=u.port or 5432, user=u.username,
                                    password=u.password, dbname=u.database)
            cur = conn.cursor()
            cur.execute(sql)
            cur.fetchall()                              # materialize row tuples
            conn.close()
        elif client == "adbc":
            pl.read_database_uri(sql, uri, engine="adbc")        # Arrow -> polars
        elif client == "connectorx":
            pl.read_database_uri(sql, uri, engine="connectorx")  # Arrow -> polars
        else:
            raise ValueError(f"postgres_transport: unknown client '{client}' "
                             f"(expected psycopg | adbc | connectorx)")
        return time.time() - start
