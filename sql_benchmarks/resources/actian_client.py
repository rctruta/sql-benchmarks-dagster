import time
import os
import polars as pl
from typing import Dict, Any, Optional

class ActianClient:
    """
    Stateful Client for Actian X / Vector.
    Uses the native 'actian-python-connector' for high-performance vectorized access.
    """
    
    def __init__(self, connection_params: Dict[str, Any]):
        self.connection_params = connection_params
        # Performance Note: In a production scenario, we'd use a connection pool.
        # For benchmarking, we use discrete connections to ensure 'Cold Cache' isolation.
        self.connection = None

    def _connect(self):
        try:
            import actian.native as actian
            self.connection = actian.connect(**self.connection_params)
        except ImportError:
            raise RuntimeError("actian-python-connector not installed. Please run 'pip install actian-python-connector'")

    def run_query(self, sql: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        self._connect()
        try:
            cursor = self.connection.cursor()
            
            # Apply any engine-specific optimizations (e.g. set result_cache off)
            # cursor.execute("SET NO RESULT_CACHE") 

            start = time.time()
            cursor.execute(sql)
            # Force result fetch to ensure end-to-end timing
            cursor.fetchall()
            duration = time.time() - start
            
            return duration
        finally:
            self.connection.close()

    def bulk_load(self, file_path: str, table_name: str, partition_key: str = None):
        """
        High-performance bulk load into Actian Vector.
        We leverage the 'COPY' command for maximum throughput.
        """
        print(f"🚀 Vectorizing {file_path} into Actian table '{table_name}'...")
        
        self._connect()
        try:
            cursor = self.connection.cursor()
            
            # 1. Create table schema if it doesn't exist
            # (In this POC, we assume the table is created by the ingestion factory)
            
            if file_path.endswith(".parquet"):
                # Actian Vector natively supports Parquet via external tables or direct COPY 
                # depending on the version. We'll use the VWLOAD-style COPY.
                copy_sql = f"COPY {table_name} FROM '{file_path}' WITH FORMAT='PARQUET'"
            else:
                # Fallback to CSV for simpler community editions
                copy_sql = f"COPY {table_name} FROM '{file_path}' WITH FORMAT='CSV', HEADER"
                
            cursor.execute(copy_sql)
            self.connection.commit()
            
            # 2. Optimize for analytics
            cursor.execute(f"MODIFY {table_name} TO COMBINE")
        finally:
            self.connection.close()
