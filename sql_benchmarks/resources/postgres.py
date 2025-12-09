import os
import time
import socket
import subprocess
import io
import csv
from dagster import ConfigurableResource
from sqlalchemy import create_engine, text
from ..utils.system import thrash_os_cache
import polars as pl

class PostgresResource(ConfigurableResource):
    """
    Dagster resource for Postgres interactions.
    Strict Pydantic validation enabled.
    """
    connection_string: str
    container_name: str = "benchmark_postgres"
    
    def _check_port_available(self, port: int = 5432) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) != 0

    def _kill_zombie_container(self):
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name], 
                check=False, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def setup_docker(self, settings: dict = None):
        """
        Idempotent Docker startup.
        """
        self._kill_zombie_container()
        
        if "localhost" in self.connection_string and not self._check_port_available(5432):
            raise RuntimeError("Port 5432 is occupied. Stop local Postgres.")

        shm_size = "2gb"
        cmd_args = ["postgres"]
        
        if settings:
            for key, val in settings.items():
                cmd_args.extend(["-c", f"{key}={val}"])

        try:
            uid = os.getuid()
            gid = os.getgid()
            user_flag = [f"--user={uid}:{gid}"]
        except AttributeError:
            user_flag = []
        
        data_mount = os.path.join(os.getcwd(), "data")
        os.makedirs(data_mount, exist_ok=True)

        subprocess.run([
            "docker", "run", "-d",
            "--name", self.container_name,
            "-p", "5432:5432",
            "-v", f"{data_mount}:/data",
            "--shm-size", shm_size,
            "-e", "POSTGRES_PASSWORD=password",
            *user_flag,
            "postgres:15",
            *cmd_args
        ], check=True)

        self._wait_for_ready()

    def _wait_for_ready(self, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            try:
                engine = create_engine(self.connection_string)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return
            except Exception:
                time.sleep(1)
        raise TimeoutError("Postgres container started but refused connections.")

    def clear_cache(self):
        print(f"❄️ Clearing Postgres Cache ({self.container_name})...")
        subprocess.run(["docker", "restart", self.container_name], check=True)
        self._wait_for_ready()
        thrash_os_cache()

    def get_engine(self):
        return create_engine(self.connection_string)

    def execute_query(self, sql: str):
        engine = self.get_engine()
        with engine.begin() as conn:
            conn.execute(text(sql))

    def benchmark_query(self, sql: str) -> float:
        engine = self.get_engine()
        with engine.connect() as conn:
            start = time.time()
            conn.execute(text(sql))
            end = time.time()
        return end - start

    def bulk_load(self, file_path: str, table_name: str):
        print(f"🚀 Streaming {file_path} to {table_name}...")
        
        if file_path.endswith(".parquet"):
            # 1. Infer Schema
            df_schema = pl.scan_parquet(file_path).limit(1).collect()
            self._create_schema(table_name, df_schema)
            # 2. Stream
            self._stream_parquet(file_path, table_name)
        elif file_path.endswith(".json"):
             self._stream_json(file_path, table_name)
        elif file_path.endswith(".csv"):
             self._stream_csv(file_path, table_name)
        
        self.execute_query(f"ANALYZE {table_name};")

    def _create_schema(self, table_name: str, sample_df: pl.DataFrame):
        cols = []
        for name, dtype in sample_df.schema.items():
            pg_type = "TEXT"
            if dtype in [pl.Int8, pl.Int16, pl.Int32, pl.Int64]:
                pg_type = "BIGINT"
            elif dtype in [pl.Float32, pl.Float64]:
                pg_type = "DOUBLE PRECISION"
            elif dtype == pl.Boolean:
                pg_type = "BOOLEAN"
            
            cols.append(f'"{name}" {pg_type}')
            
        ddl = f"DROP TABLE IF EXISTS {table_name}; CREATE TABLE {table_name} ({', '.join(cols)});"
        self.execute_query(ddl)

    def _stream_parquet(self, path: str, table_name: str, batch_size: int = 500_000):
        engine = self.get_engine()
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                import pyarrow.parquet as pq
                parquet_file = pq.ParquetFile(path)
                
                for batch in parquet_file.iter_batches(batch_size=batch_size):
                    df = pl.from_arrow(batch)
                    self._copy_buffer(cur, df, table_name)
                    
            raw_conn.commit()
        finally:
            raw_conn.close()

    def _stream_json(self, path: str, table_name: str, batch_size: int = 100_000):
        # Basic JSON implementation - iterates lines for NDJSON
        engine = self.get_engine()
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                # Lazy read JSON
                reader = pl.read_ndjson(path, batch_size=batch_size, return_type="arrow")
                # Assuming simple NDJSON here; if complex, requires custom logic
                # For now, simplistic implementation to satisfy interface
                df = pl.read_ndjson(path) # Warning: Loads all to memory if no iterator
                self._create_schema(table_name, df)
                self._copy_buffer(cur, df, table_name)
            raw_conn.commit()
        finally:
            raw_conn.close()
            
    def _stream_csv(self, path: str, table_name: str):
        # CSV is native to Postgres, we can just use COPY directly from file if mounted,
        # but since we are running remote/docker execution, stream via Python
        engine = self.get_engine()
        raw_conn = engine.raw_connection()
        try:
            with open(path, 'r') as f:
                with raw_conn.cursor() as cur:
                     # Create table first? Assuming exists or inferred.
                     # For CSV, inference is harder without scanning. 
                     # Using simplistic direct copy for now.
                     cur.copy_expert(f"COPY {table_name} FROM STDIN WITH (FORMAT CSV, HEADER)", f)
            raw_conn.commit()
        finally:
            raw_conn.close()

    def _copy_buffer(self, cursor, df: pl.DataFrame, table_name: str):
        csv_buffer = io.StringIO()
        # FIX: 'include_header' is correct for Polars write_csv
        df.write_csv(csv_buffer, include_header=False)
        csv_buffer.seek(0)
        cursor.copy_expert(
            f"COPY {table_name} FROM STDIN WITH (FORMAT CSV)",
            csv_buffer
        )