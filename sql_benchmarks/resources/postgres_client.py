import io
import time
import polars as pl
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from typing import Dict, Any, Optional

# Module-level constant so callers can identify pg-setting dimension keys
# without importing the class or reaching into its internals.
PG_SETTING_KEYS = frozenset({
    "work_mem",
    "random_page_cost",
    "enable_hashjoin",
    "enable_nestloop",
    "enable_seqscan",
    "enable_sort",
    "enable_mergejoin",
    "effective_cache_size",
    "max_parallel_workers_per_gather",
    "statement_timeout",   # budget per query; on breach the query is recorded DNF
})


class PostgresClient:
    """
    STATEFUL CLIENT: Restored original logic using Polars + PyArrow for robust ingestion.
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine = create_engine(connection_string) 

    # Allowlist of Postgres settings the benchmark harness is permitted to set.
    # Prevents arbitrary SQL injection via pg_settings YAML keys.
    # Also exported as a module-level constant for callers that need to
    # identify which dimension keys are pg settings (without coupling to this class).
    _ALLOWED_PG_SETTINGS = PG_SETTING_KEYS

    def run_query(self, sql: str, partition_key: str = None, pg_settings: Dict[str, Any] = None) -> Optional[float]:
        """Execute a benchmark query, optionally applying Postgres session settings first.

        partition_key is accepted but unused — present for interface symmetry with DuckDBClient.
        pg_settings must only contain keys from PG_SETTING_KEYS (enforced below).
        """
        pg_settings = pg_settings or {}

        with self.engine.connect() as conn:
            for key, val in pg_settings.items():
                if key not in PG_SETTING_KEYS:
                    raise ValueError(f"pg_setting '{key}' is not in the allowlist.")
                # Key is allowlisted (safe to interpolate); value is parameterized.
                conn.execute(text(f"SET {key} = :val"), {"val": str(val)})

            start = time.time()
            try:
                conn.execute(text(sql))
                conn.commit()
            except OperationalError as e:
                # statement_timeout fired (SQLSTATE 57014, query_canceled): the
                # query genuinely did not finish in its budget. Record as DNF
                # (None) — a finding, not a crash — instead of masking other errors.
                if getattr(e.orig, "pgcode", None) == "57014":
                    conn.rollback()
                    print(f"[Postgres] DNF — statement_timeout "
                          f"({pg_settings.get('statement_timeout')}) exceeded.")
                    return None
                raise
            return time.time() - start

    # Updated signature to accept partition_key (passed from factory), even if unused logic-wise
    def bulk_load(self, file_path: str, table_name: str, partition_key: str = None, table_def: dict = None):
        print(f"Streaming {file_path} to {table_name}...")

        if file_path.endswith(".parquet"):
            # 1. Infer Schema using Polars (Fixes UndefinedTable error)
            df_schema = pl.scan_parquet(file_path).limit(1).collect()
            # Honor explicit per-column DDL type overrides (e.g. type: jsonb) so a
            # column can land as a real DB type instead of inferred TEXT.
            overrides = {c["name"]: c["type"] for c in (table_def or {}).get("columns", [])
                         if isinstance(c, dict) and c.get("type")}
            self._create_schema(table_name, df_schema, type_overrides=overrides)
            # 2. Stream Data
            self._stream_parquet(file_path, table_name)

        elif file_path.endswith(".json"):
             self._stream_json(file_path, table_name)
        elif file_path.endswith(".csv"):
             self._stream_csv(file_path, table_name)

        self._execute_internal(f"ANALYZE {table_name};")

        # Apply declared schema constraints (PK, indexes, FKs) AFTER the bulk
        # load — building them post-load is correct and faster than per-row.
        # This is one-time setup cost, outside the timed query loop.
        if table_def:
            self._apply_constraints(table_def, table_name, partition_key)

    def _apply_constraints(self, table_def: dict, table_name: str, partition_key: str):
        from ..utils.ddl import PostgresDDLGenerator
        gen = PostgresDDLGenerator(table_def, table_name, partition_key)
        statements = []
        pk_sql = gen.generate_pk_sql()
        if pk_sql:
            statements.append(pk_sql)
        statements.extend(gen.generate_index_sqls())
        statements.extend(gen.generate_fk_sqls())
        for sql in statements:
            self._execute_internal(sql)
        if statements:
            # Refresh stats so the planner can choose an index scan.
            self._execute_internal(f"ANALYZE {table_name};")

    def _create_schema(self, table_name: str, sample_df: pl.DataFrame, type_overrides: dict = None):
        """
        Creates the table schema dynamically using a robust Type Map.
        An explicit per-column `type_overrides` (from the config's `type:` field)
        wins over the inferred polars->pg mapping — e.g. type: jsonb.
        """
        type_overrides = type_overrides or {}
        # Improved Type Map as requested
        type_map = {
            pl.Int8: "SMALLINT",
            pl.Int16: "SMALLINT",
            pl.Int32: "INTEGER",
            pl.Int64: "BIGINT",
            pl.Float32: "REAL",
            pl.Float64: "DOUBLE PRECISION",
            pl.String: "TEXT",
            pl.Utf8: "TEXT",
            pl.Boolean: "BOOLEAN",
            pl.Date: "DATE",
            pl.Datetime: "TIMESTAMP",
            pl.Object: "TEXT"
        }

        cols = []
        for name, dtype in sample_df.schema.items():
            if name in type_overrides:
                pg_type = type_overrides[name]            # explicit wins (e.g. jsonb)
            else:
                # Default to TEXT if not found, or use the mapped type
                pg_type = type_map.get(dtype, "TEXT")
                # Handle datetime subclasses if necessary
                if isinstance(dtype, pl.Datetime):
                    pg_type = "TIMESTAMP"

            cols.append(f'"{name}" {pg_type}')

        # Clean slate: Drop and Create
        ddl = f"DROP TABLE IF EXISTS {table_name}; CREATE TABLE {table_name} ({', '.join(cols)});"
        self._execute_internal(ddl)

    def _stream_parquet(self, path: str, table_name: str, batch_size: int = 500_000):
        # Use the engine's raw connection (Restored your try/finally logic)
        raw_conn = self.engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                parquet_file = pq.ParquetFile(path)

                for batch in parquet_file.iter_batches(batch_size=batch_size):
                    df = pl.from_arrow(batch)
                    self._copy_buffer(cur, df, table_name)

            raw_conn.commit()
        finally:
            raw_conn.close()

    def _stream_json(self, path: str, table_name: str):
        raw_conn = self.engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                df = pl.read_ndjson(path)
                self._create_schema(table_name, df)
                self._copy_buffer(cur, df, table_name)
            raw_conn.commit()
        finally:
            raw_conn.close()

    def _stream_csv(self, path: str, table_name: str):
        raw_conn = self.engine.raw_connection()
        try:
            with open(path, 'r') as f:
                with raw_conn.cursor() as cur:
                     cur.copy_expert(f"COPY {table_name} FROM STDIN WITH (FORMAT CSV, HEADER)", f)
            raw_conn.commit()
        finally:
            raw_conn.close()

    def _copy_buffer(self, cursor, df: pl.DataFrame, table_name: str):
        """
        High-performance buffer write using Polars CSV serializer.
        """
        csv_buffer = io.StringIO()
        # write_csv is extremely fast in Polars
        df.write_csv(csv_buffer, include_header=False)
        csv_buffer.seek(0)
        cursor.copy_expert(
            f"COPY {table_name} FROM STDIN WITH (FORMAT CSV)",
            csv_buffer
        )

    def _execute_internal(self, sql: str):
        """Helper to execute DDL/Utility queries"""
        with self.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()