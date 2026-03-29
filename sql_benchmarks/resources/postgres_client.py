import io
import time
import polars as pl
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from typing import Dict, Any, Optional

class PostgresClient:
    """
    STATEFUL CLIENT: Restored original logic using Polars + PyArrow for robust ingestion.
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine = create_engine(connection_string) 

    # Allowlist of Postgres settings the benchmark harness is permitted to set.
    # Prevents arbitrary SQL injection via pg_settings YAML keys.
    _ALLOWED_PG_SETTINGS = frozenset({
        "work_mem",
        "random_page_cost",
        "enable_hashjoin",
        "enable_nestloop",
        "enable_seqscan",
        "enable_sort",
        "enable_mergejoin",
        "effective_cache_size",
        "max_parallel_workers_per_gather",
    })

    def run_query(self, sql: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        pg_settings = scenario_params.get("pg_settings", {})

        with self.engine.connect() as conn:
            if pg_settings:
                for key, val in pg_settings.items():
                    if key not in self._ALLOWED_PG_SETTINGS:
                        raise ValueError(f"pg_setting '{key}' is not in the allowlist.")
                    # Values are safe_cast to string and quoted; key is allowlisted above.
                    conn.execute(text(f"SET {key} = :val"), {"val": str(val)})
            
            start = time.time()
            conn.execute(text(sql))
            conn.commit() 
            return time.time() - start

    # Updated signature to accept partition_key (passed from factory), even if unused logic-wise
    def bulk_load(self, file_path: str, table_name: str, partition_key: str = None):
        print(f"Streaming {file_path} to {table_name}...")

        if file_path.endswith(".parquet"):
            # 1. Infer Schema using Polars (Fixes UndefinedTable error)
            df_schema = pl.scan_parquet(file_path).limit(1).collect()
            self._create_schema(table_name, df_schema)
            # 2. Stream Data
            self._stream_parquet(file_path, table_name)
            
        elif file_path.endswith(".json"):
             self._stream_json(file_path, table_name)
        elif file_path.endswith(".csv"):
             self._stream_csv(file_path, table_name)

        self._execute_internal(f"ANALYZE {table_name};")

    def _create_schema(self, table_name: str, sample_df: pl.DataFrame):
        """
        Creates the table schema dynamically using a robust Type Map.
        """
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