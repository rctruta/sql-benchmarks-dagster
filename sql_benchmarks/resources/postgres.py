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

    def _calculate_default_work_mem(self, row_count: int) -> str:
        """Heuristic: More rows = More RAM needed to avoid disk spill."""
        if not row_count: return "64MB"
        if row_count < 1_000_000: return "64MB"
        if row_count < 10_000_000: return "256MB"
        return "1GB"

    def benchmark_query(self, sql: str, partition_key: str = None, db_config: dict = None, expected_rows: int = 0):
        self.clear_cache()
        
        # 1. Start with Smart Defaults
        config = {
            "work_mem": self._calculate_default_work_mem(expected_rows),
            "random_page_cost": "4.0" # Default Postgres (HDD assumption)
        }
        
        # 2. Apply Explicit Overrides from YAML (The "Contract")
        if db_config:
            config.update(db_config)

        engine = self.get_engine()
        with engine.connect() as conn:
            
            # 3. Apply Settings
            settings_log = []
            for key, value in config.items():
                # Basic injection check
                if key.replace("_", "").isalnum(): 
                    conn.execute(text(f"SET {key} = '{value}';"))
                    settings_log.append(f"{key}={value}")
            
            print(f"   ⚙️ Tuning Postgres: {', '.join(settings_log)}")
            
            # 4. Execute
            _ = conn.execute(text(sql)).fetchall()

    # --- GENERIC BULK LOADER ---
    def bulk_load(self, parquet_path: str, table_name: str):
        engine = self.get_engine()
        
        print(f"   🔨 Creating schema for {table_name}...")
        
        # 1. Generic Schema Creation
        # We rely on Polars' standard mapping. It works for 99% of cases.
        # (We fix the 1% in the data plugin, not here)
        try:
            pl.scan_parquet(parquet_path).limit(0).collect().write_database(
                table_name=table_name, 
                connection=self.connection_string, 
                if_table_exists="replace", 
                engine="sqlalchemy"
            )
        except Exception as e:
            raise Exception(f"Schema creation failed: {e}")

        # 2. Stream Data (Standard Copy)
        print(f"   🚀 Streaming from {parquet_path}...")
        t_start = time.time()
        
        parquet_file = pq.ParquetFile(parquet_path)
        conn = engine.raw_connection()
        
        try:
            cursor = conn.cursor()
            for i, batch in enumerate(parquet_file.iter_batches(batch_size=500_000)):
                df_chunk = pl.from_arrow(batch)
                csv_buffer = io.BytesIO()
                df_chunk.write_csv(csv_buffer, include_header=False)
                csv_buffer.seek(0)
                
                cursor.copy_expert(f"COPY {table_name} FROM STDIN WITH (FORMAT CSV)", csv_buffer)
                print(f"      ... loaded chunk {i+1}")
            
            conn.commit()
            print(f"   ✅ Done in {time.time() - t_start:.1f}s")
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()