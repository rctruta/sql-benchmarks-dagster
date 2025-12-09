import time
import io
import os
import subprocess
import polars as pl
import pyarrow.parquet as pq
from dagster import ConfigurableResource
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

class PostgresResource(ConfigurableResource):
    connection_string: str
    container_name: str = "benchmark_postgres"

    # ==========================================================
    # PUBLIC INTERFACE
    # ==========================================================
    def get_engine(self):
        return create_engine(self.connection_string)

    def execute_query(self, sql: str):
        with self.get_engine().connect() as conn:
            conn.execute(text(sql))
            conn.commit()

    def clear_cache(self):
        """Restarts the container to ensure cold cache."""
        subprocess.run(["docker", "restart", self.container_name], check=True)
        
        # Retry loop to wait for DB to come up
        retries = 15
        while retries > 0:
            try:
                with self.get_engine().connect() as conn: conn.execute(text("SELECT 1"))
                return
            except OperationalError:
                time.sleep(1); retries -= 1
        raise Exception("Postgres failed to restart.")

    def benchmark_query(self, sql: str, partition_key: str = None, db_config: dict = None, expected_rows: int = 0):
        self.clear_cache()
        with self.get_engine().connect() as conn:
             if db_config:
                 for k, v in db_config.items(): conn.execute(text(f"SET {k} = '{v}';"))
             conn.execute(text(sql)).fetchall()

    def bulk_load(self, file_path: str, table_name: str):
        """
        Public entry point for data loading.
        Dispatches to internal private handlers based on extension.
        """
        engine = self.get_engine()
        file_ext = os.path.splitext(file_path)[1].lower()
        
        print(f"   🔨 Inferring schema for {table_name}...")
        self._create_schema(file_path, table_name, file_ext)

        print(f"   🚀 Streaming {file_ext}...")
        t_start = time.time()
        
        conn = engine.raw_connection()
        try:
            cursor = conn.cursor()
            if file_ext == ".parquet":
                self._stream_parquet(file_path, table_name, cursor)
            elif file_ext == ".csv":
                self._stream_csv(file_path, table_name, cursor)
            elif file_ext in [".json", ".ndjson"]:
                self._stream_json(file_path, table_name, cursor)
            else:
                raise ValueError(f"Unsupported format: {file_ext}")
                
            conn.commit()
            print(f"   ✅ Done ({time.time() - t_start:.1f}s)")
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    # ==========================================================
    # INTERNAL LOADING LOGIC (Encapsulated)
    # ==========================================================
    def _create_schema(self, path: str, table: str, ext: str):
        try:
            if ext == ".parquet": lf = pl.scan_parquet(path)
            elif ext in [".json", ".ndjson"]: lf = pl.scan_ndjson(path)
            elif ext == ".csv": lf = pl.scan_csv(path, infer_schema_length=10000)
            else: raise ValueError(f"Unsupported: {ext}")
            
            lf.limit(0).collect().write_database(
                table_name=table, connection=self.connection_string, 
                if_table_exists="replace", engine="sqlalchemy"
            )
        except Exception as e: raise Exception(f"Schema generation failed: {e}")

    def _copy_buffer(self, df: pl.DataFrame, table: str, cursor):
        """Helper to write DF to CSV buffer and COPY to Postgres."""
        buf = io.BytesIO()
        df.write_csv(buf, include_header=False)
        buf.seek(0)
        cursor.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT CSV)", buf)

    def _stream_parquet(self, path: str, table: str, cursor):
        pq_file = pq.ParquetFile(path)
        for batch in pq_file.iter_batches(batch_size=500_000):
            self._copy_buffer(pl.from_arrow(batch), table, cursor)

    def _stream_csv(self, path: str, table: str, cursor):
        reader = pl.read_csv_batched(path, batch_size=500_000)
        while (batches := reader.next_batches(1)):
            for df in batches: self._copy_buffer(df, table, cursor)

    def _stream_json(self, path: str, table: str, cursor):
        self._copy_buffer(pl.read_ndjson(path), table, cursor)