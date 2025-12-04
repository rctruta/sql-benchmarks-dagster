import time
import subprocess
import io
import polars as pl
import pyarrow.parquet as pq
from dagster import ConfigurableResource
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

class PostgresResource(ConfigurableResource):
    connection_string: str
    container_name: str = "benchmark_postgres"

    def get_engine(self):
        return create_engine(self.connection_string)

    def execute_query(self, sql: str):
        engine = self.get_engine()
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()

    def clear_cache(self):
        # (Keep existing clear_cache logic...)
        print(f"❄️ Restarting {self.container_name}...")
        subprocess.run(["docker", "restart", self.container_name], check=True)
        retries = 15
        while retries > 0:
            try:
                engine = self.get_engine()
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return
            except OperationalError:
                time.sleep(1)
                retries -= 1
        raise Exception("Postgres failed to restart.")

    def _calculate_work_mem(self, row_count: int) -> str:
        """
        Dynamically determines work_mem based on dataset size.
        Heuristic: We want enough RAM to hash/sort the dataset in memory.
        """
        if row_count is None or row_count == 0:
            return "64MB"  # Safe default
        
        # 1. Tiny/Small (< 100k) -> 16MB is plenty
        if row_count < 100_000:
            return "16MB"
        
        # 2. Medium (100k - 1M) -> 64MB
        if row_count < 1_000_000:
            return "64MB"
            
        # 3. Large (1M - 10M) -> 256MB
        if row_count < 10_000_000:
            return "256MB"
            
        # 4. Huge (10M+) -> 1GB (Assuming host has RAM)
        return "1GB"

    def benchmark_query(self, sql: str, partition_key: str = None, expected_rows: int = 0):
        """
        Runs the benchmark with adaptive configuration.
        """
        self.clear_cache()
        
        # Calculate optimal settings
        work_mem = self._calculate_work_mem(expected_rows)
        
        engine = self.get_engine()
        with engine.connect() as conn:
            # Apply Adaptive Config
            print(f"   ⚙️ Tuning Postgres: work_mem={work_mem} (for ~{expected_rows} rows)")
            conn.execute(text(f"SET work_mem = '{work_mem}';"))
            
            # Execute
            _ = conn.execute(text(sql)).fetchall()

    def bulk_load(self, parquet_path: str, table_name: str):
        """
        Streams data from disk -> Postgres COPY.
        Uses PyArrow for chunking and Polars for CSV formatting.
        """
        engine = self.get_engine()
        
        # 1. Create Schema
        # We scan just to infer schema, very lightweight
        print(f"   🔨 Creating schema for {table_name}...")
        try:
            pl.scan_parquet(parquet_path).limit(0).collect().write_database(
                table_name=table_name, 
                connection=self.connection_string, 
                if_table_exists="replace", 
                engine="sqlalchemy"
            )
        except Exception as e:
            raise Exception(f"Schema creation failed: {e}")

        # 2. Stream Data
        print(f"   🚀 Streaming from {parquet_path}...")
        t_start = time.time()
        
        parquet_file = pq.ParquetFile(parquet_path)
        conn = engine.raw_connection()
        
        try:
            cursor = conn.cursor()
            
            # Iterate over batches (Standard Arrow API)
            # 500k rows is a safe chunk size for memory stability
            for i, batch in enumerate(parquet_file.iter_batches(batch_size=500_000)):
                
                # Zero-Copy conversion: Arrow Batch -> Polars DataFrame
                df_chunk = pl.from_arrow(batch)
                
                # Write to CSV Buffer using Polars
                csv_buffer = io.BytesIO()
                df_chunk.write_csv(csv_buffer, include_header=False)
                csv_buffer.seek(0)
                
                cursor.copy_expert(
                    f"COPY {table_name} FROM STDIN WITH (FORMAT CSV)", 
                    csv_buffer
                )
                print(f"      ... loaded chunk {i+1}")
            
            conn.commit()
            print(f"   ✅ Done in {time.time() - t_start:.1f}s")
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()