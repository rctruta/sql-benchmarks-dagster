"""
QuackClient: benchmark client for DuckDB's Quack client-server protocol
(beta since DuckDB 1.5.3).

Topology per measurement (mirrors the Postgres cold-cache methodology):
  1. Any previous server on this port is stopped (cold start guarantee).
  2. A fresh server subprocess opens the partition's .duckdb file and serves
     it via CALL quack_serve over HTTP, bound to localhost only.
  3. The measurement connection ATTACHes with 'quack:localhost:<port>',
     switches default catalog with USE, and executes the SAME SQL files as
     the in-process duckdb engine — measured time therefore includes Quack
     protocol serialization and HTTP transport, which is the point.
  4. The server is stopped after the measurement.

Server startup and ATTACH handshake happen BEFORE the timer starts; only
query execution + result materialisation are measured.
"""
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

import duckdb

from .duckdb_client import DuckDBClient

# Token is interpolated into SQL on both server and client side; restrict the
# alphabet so a misconfigured env var fails loudly instead of injecting SQL.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,}$")

# Module-level server registry keyed by port (facades create a fresh client
# per call — instance state would orphan server processes).
_SERVERS: Dict[int, subprocess.Popen] = {}

# Runs in a subprocess: open the partition db, serve it, block forever.
# db_path and port arrive via argv; the token via env (kept out of `ps`).
_SERVER_SCRIPT = """
import os, sys, time
import duckdb
db_path, port = sys.argv[1], sys.argv[2]
token = os.environ["SB_QUACK_TOKEN"]
con = duckdb.connect(db_path)
con.execute("LOAD quack;")
con.execute("CALL quack_serve('quack:localhost:%s', token := '%s')" % (port, token))
print("READY", flush=True)
while True:
    time.sleep(3600)
"""


class QuackClient:
    """STATEFUL CLIENT: owns server lifecycle + measurement I/O for Quack."""

    def __init__(self, data_folder: str, port: int = 9494, token: str = "",
                 pushdown: bool = False):
        if not _SAFE_TOKEN.match(token):
            raise ValueError(
                "Quack token must be >=8 chars of [A-Za-z0-9_-] "
                "(it is interpolated into quack_serve/ATTACH statements)."
            )
        self.data_folder = data_folder
        self.port = port
        self.token = token
        # Execution mode. attach (default): the CLIENT plans the query against
        # the remote catalog (USE remote) — table data may stream over HTTP.
        # pushdown: the SQL text is shipped via remote.query('...') and
        # executes fully SERVER-side; only the result set crosses the wire.
        # Comparing the two isolates where Quack spends its time.
        self.pushdown = pushdown
        # File-level operations (db path layout, parquet bulk load) are
        # identical to the in-process duckdb engine — compose, don't copy.
        self._duck = DuckDBClient(data_folder=data_folder)

    # --- IBenchmarkEngine-facing operations -------------------------------

    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str, table_def: dict = None) -> None:
        # The server holds the db file open; loading requires exclusive access.
        self.stop_server()
        self._duck.bulk_load(filepath, target_table_name, partition_key, table_def)

    def run_query(self,
                  sql: str,
                  partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """Cold-start a server for the partition, measure the query over Quack.

        engine_params is the 'quack' namespace — reserved for server-side
        settings; not yet applied.
        """
        db_path = self._duck._get_db_path(partition_key)
        self.stop_server()
        proc = self._start_server(db_path)
        con = duckdb.connect()
        try:
            con.execute("LOAD quack;")
            self._attach_with_retry(con, proc)

            if self.pushdown:
                # Ship the SQL text; execution happens entirely server-side.
                # Single-quote doubling is the only escaping SQL strings need.
                wrapped = "FROM remote.query('{}')".format(sql.replace("'", "''"))
                start = time.time()
                con.sql(wrapped).fetchall()
                end = time.time()
            else:
                con.execute("USE remote")
                start = time.time()
                con.sql(sql).fetchall()
                end = time.time()
            return end - start
        except duckdb.NotImplementedException as e:
            # A protocol capability gap, not a config error: e.g. attach mode
            # cannot run multi-table joins in the Quack beta ("Multiple
            # streaming scans ... not currently supported"). Record as DNF —
            # the limitation IS the measurement. Anything else still raises.
            print(f"[Quack] DNF — protocol limitation: {e}")
            return None
        finally:
            con.close()
            self.stop_server()

    # --- Server lifecycle --------------------------------------------------

    def stop_server(self) -> None:
        proc = _SERVERS.pop(self.port, None)
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _start_server(self, db_path: str) -> subprocess.Popen:
        env = {**os.environ, "SB_QUACK_TOKEN": self.token}
        proc = subprocess.Popen(
            [sys.executable, "-c", _SERVER_SCRIPT, db_path, str(self.port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _SERVERS[self.port] = proc
        return proc

    def _attach_with_retry(self, con, proc: subprocess.Popen, timeout_s: float = 15.0) -> None:
        """ATTACH doubles as the readiness probe. Fails loudly with server stderr."""
        uri = f"quack:localhost:{self.port}"
        deadline = time.time() + timeout_s
        last_err = None
        while time.time() < deadline:
            if proc.poll() is not None:
                _, stderr = proc.communicate()
                raise RuntimeError(
                    f"Quack server exited (code {proc.returncode}) before serving "
                    f"{uri}. Stderr:\n{stderr}"
                )
            try:
                con.execute(
                    f"ATTACH '{uri}' AS remote (TOKEN '{self.token}', DISABLE_SSL true)"
                )
                return
            except duckdb.Error as e:
                last_err = e
                time.sleep(0.2)
        raise RuntimeError(f"Quack server at {uri} not ready after {timeout_s}s: {last_err}")
