import duckdb
import os
import re
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional
from ..utils.system import thrash_os_cache
from .base_engine import IBenchmarkEngine

_SAFE_IDENTIFIER = re.compile(r"^\w+$")  # letters, digits, underscores only


def _assert_safe_identifier(value: str, label: str) -> None:
    if not _SAFE_IDENTIFIER.match(value):
        raise ValueError(f"Unsafe {label}: '{value}'. Only word characters allowed.")


# The 'duckdb' engine_params namespace vocabulary: session settings applied
# via SET before the measured query. Strict allowlist — an unknown key is a
# config error and must fail loudly, never be silently ignored.
DUCKDB_SETTING_KEYS = frozenset({
    "threads",
    "memory_limit",
})

# SET cannot use parameter binding; values are interpolated as quoted
# literals, so restrict the alphabet (covers ints and sizes like '1GB').
_SAFE_SETTING_VALUE = re.compile(r"^[A-Za-z0-9._]+$")


def _apply_engine_params(con, engine_params: Dict[str, Any]) -> None:
    for key, value in (engine_params or {}).items():
        if key not in DUCKDB_SETTING_KEYS:
            raise ValueError(
                f"Unknown duckdb engine_params key '{key}'. "
                f"Allowed: {sorted(DUCKDB_SETTING_KEYS)}"
            )
        if not _SAFE_SETTING_VALUE.match(str(value)):
            raise ValueError(f"Unsafe value for duckdb setting '{key}': {value!r}")
        con.execute(f"SET {key} = '{value}'")

# Note: DuckDBClient does NOT inherit ConfigurableResource

# ---------------------------------------------------------------------------
# Module-level db-file tracker (mirrors the TypeDBEngine pattern).
# The first bulk_load call for a given db file deletes any stale copy
# (clean slate).  Subsequent tables are added to the same file via
# CREATE OR REPLACE TABLE, so multi-table experiments (e.g. hypergraph
# supply chain) work correctly.  Keyed by db_path — not partition_key —
# because multiple engines (duckdb, quack) load the same partitions into
# different data folders.  Cleared naturally between runs because each
# execute_run.py invocation starts a fresh Python process.
# ---------------------------------------------------------------------------
_INITIALIZED_DB_FILES: set = set()

class DuckDBClient: 
    """
    STATEFUL CLIENT: Holds the execution logic and performs all I/O operations,
    ensuring the Engine resource remains immutable.
    """
    
    def __init__(self, data_folder: str):
        # Configuration required for execution, held on the stateful object
        self.data_folder = data_folder
    
    # --- IBenchmarkEngine Implementation (Execution Logic) ---
    
    def bulk_load(self, filepath: str, target_table_name: str, partition_key: str) -> None:
        db_path = self._get_db_path(partition_key)

        # Validate inputs before constructing SQL.
        # Table name: DuckDB doesn't support parameterized identifiers, so we validate
        # with a strict allowlist regex (word chars only) before interpolation.
        # Filepath: use read_parquet(?) parameterized binding for the value.
        _assert_safe_identifier(target_table_name, "table name")
        filepath = os.path.realpath(filepath)  # resolve symlinks / traversal

        # First table for this db file: wipe any stale copy for a clean
        # slate.  Subsequent tables are added to the same file via
        # CREATE OR REPLACE TABLE so all tables coexist.
        if db_path not in _INITIALIZED_DB_FILES:
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except OSError as e:
                    print(f"[WARN] Could not remove existing DB file {db_path}: {e}")
            _INITIALIZED_DB_FILES.add(db_path)

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with duckdb.connect(db_path, read_only=False) as con:
            con.execute(
                f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet(?)",
                [filepath],
            )
             
    def run_query(self,
                  sql: str,
                  partition_key: str,
                  engine_params: Dict[str, Any] = None) -> Optional[float]:
        """Execute a benchmark query against the partition's DuckDB file.

        engine_params is the 'duckdb' namespace (threads, memory_limit),
        applied via SET before timing starts so the measurement reflects the
        configured execution, not the configuration itself.
        """
        db_path = self._get_db_path(partition_key)

        # Enable RW for Sentinel experiments (CREATE TABLE)
        with duckdb.connect(db_path, read_only=False) as con:
            _apply_engine_params(con, engine_params)
            start = time.time()
            # In DuckDB, multiple statements in one string are executed if separated by semicolon
            # .sql() executes them. 
            con.sql(sql).fetchall()
            end = time.time()
            
            return end - start
            
    # --- Internal/Utility Methods (Moved here) ---
    
    def _get_db_path(self, partition_key: str):
        """Calculates the database file path using the partition_key."""
        if partition_key is None:
            return os.path.join(self.data_folder, "benchmark.duckdb") 
        
        db_filename = f"benchmark_{partition_key}.duckdb" 
        return os.path.join(self.data_folder, db_filename)

    # --- Utility Methods ---
    # execute_query, get_connection, and execute_on_file are moved here
    # as they all involve I/O and state.

    def execute_query(self, sql: str, partition_key: str = None, read_only: bool = False, is_benchmark: bool = False):
        db_path = self._get_db_path(partition_key)
        
        if not read_only:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        with duckdb.connect(db_path, read_only=read_only) as con:
            result = con.execute(sql)
            if is_benchmark:
                result.fetchall()
    
    @contextmanager
    def get_connection(self, db_path: str, read_only: bool = False):
        con = duckdb.connect(db_path, read_only=read_only)
        try:
            yield con
        finally:
            con.close()

    def execute_on_file(self, sql: str, target_path: str):
        with self.get_connection(target_path) as con:
            con.execute(sql)