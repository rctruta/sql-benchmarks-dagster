"""Stateful client that executes operations in an isolated subprocess under a
specified DuckDB version via uv."""
import json
import os
import subprocess
from typing import Dict, Any, Optional

_INITIALIZED_DB_FILES: set = set()


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
            "uv",
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
    ) -> Optional[float]:
        db_path = self._get_db_path(partition_key)

        cmd = [
            "uv",
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
            err_msg = result.stderr.strip() or result.stdout.strip()
            print(f"[ERROR] DuckDB {self.version} query execution failed: {err_msg}")
            return None

        try:
            lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
            payload = json.loads(lines[-1])
            return float(payload["duration_seconds"])
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse DuckDB worker output: {result.stdout!r}. Error: {e}"
            )
