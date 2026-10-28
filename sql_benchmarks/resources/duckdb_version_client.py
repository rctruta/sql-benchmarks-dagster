"""Stateful client that executes operations in an isolated subprocess under a
specified DuckDB version via uv."""
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, Any, Optional

from .duckdb_client import refuse_cold

logger = logging.getLogger("dagster")

_INITIALIZED_DB_FILES: set = set()


def _find_uv_bin() -> str:
    """Locate the uv binary on PATH or within the active Python environment."""
    bin_path = shutil.which("uv")
    if bin_path:
        return bin_path
    venv_bin = os.path.join(os.path.dirname(sys.executable), "uv")
    if os.path.isfile(venv_bin) and os.access(venv_bin, os.X_OK):
        return venv_bin
    return "uv"


def _parse_worker_error(stderr: str) -> Optional[dict]:
    """The worker's structured error, or None if the worker never reported one.

    The worker prints {"status": "error", ...} as its last stderr line when
    DuckDB itself rejects the query. Anything else (uv unable to install the
    version, an import failure, a crash) means the worker did not run.
    """
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("status") == "error":
        return payload
    return None


class DuckDBVersionClient:
    """Stateful client executing DuckDB operations in a version-isolated process."""

    def __init__(self, data_folder: str, version: str):
        self.data_folder = data_folder
        self.version = version

    def _get_db_path(self, partition_key: str) -> str:
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb")
        db_filename = f"benchmark_{partition_key}.duckdb"
        return os.path.join(self.data_folder, db_filename)

    def bulk_load(
        self,
        filepath: str,
        target_table_name: str,
        partition_key: str,
        table_def: dict = None,
    ) -> None:
        db_path = self._get_db_path(partition_key)
        filepath = os.path.realpath(filepath)

        if db_path not in _INITIALIZED_DB_FILES:
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except OSError as e:
                    print(f"[WARN] Could not remove existing DB file {db_path}: {e}")
            _INITIALIZED_DB_FILES.add(db_path)

        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        cmd = [
            _find_uv_bin(),
            "run",
            "--quiet",
            "--no-project",
            f"--with=duckdb=={self.version}",
            "python",
            "-m",
            "sql_benchmarks.resources.duckdb_worker",
            "bulk_load",
            "--db-path",
            db_path,
            "--table-name",
            target_table_name,
            "--filepath",
            filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"DuckDB {self.version} bulk_load failed (code {result.returncode}): "
                f"{result.stderr or result.stdout}"
            )

    def run_query(
        self,
        sql: str,
        partition_key: str,
        engine_params: Dict[str, Any] = None,
        *,
        cold: bool,
    ) -> Optional[float]:
        """Run one query in a fresh worker process, so DuckDB's buffer pool is
        always empty. cold has no default; until OS page-cache eviction is
        implemented, cold=True raises.

        Returns None (recorded as DNF) only when DuckDB rejected the query;
        a worker that never ran raises.
        """
        refuse_cold(cold)
        db_path = self._get_db_path(partition_key)

        cmd = [
            _find_uv_bin(),
            "run",
            "--quiet",
            "--no-project",
            f"--with=duckdb=={self.version}",
            "python",
            "-m",
            "sql_benchmarks.resources.duckdb_worker",
            "query",
            "--db-path",
            db_path,
        ]
        if engine_params:
            cmd.extend(["--engine-params", json.dumps(engine_params)])

        # Pass SQL via stdin to support arbitrarily large queries without shell escaping issues
        result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
        if result.returncode != 0:
            worker_error = _parse_worker_error(result.stderr)
            if worker_error is None:
                raise RuntimeError(
                    f"DuckDB {self.version} worker did not run (code {result.returncode}): "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            logger.warning(
                f"DuckDB {self.version} rejected the query "
                f"({worker_error.get('error_type')}): {worker_error.get('error')}"
            )
            return None

        try:
            lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
            payload = json.loads(lines[-1])
            return float(payload["duration_seconds"])
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse DuckDB worker output: {result.stdout!r}. Error: {e}"
            )
