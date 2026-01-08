import time
import os
import polars as pl
from typing import Dict, Any, Optional

class ActianClient:
    """
    Stateful Client for Actian X / Vector.
    Uses the native 'actian-python-connector' for high-performance vectorized access.
    """
    
    def __init__(self, connection_params: Dict[str, Any], container_name: str = "sql_bench_actian"):
        self.connection_params = connection_params
        self.container_name = container_name
        # Performance Note: In a production scenario, we'd use a connection pool.
        # For benchmarking, we use discrete connections to ensure 'Cold Cache' isolation.
        self.connection = None

    def _connect(self):
        try:
            import pyodbc
            # Standard Actian/Ingres ODBC Connection String
            # Requires Actian Client (Ingres Net) installed on the host or in the container.
            # Since we are running on Host but DB is in Container, we need the ODBC Driver.
            # However, for this POC, we can try using the `ingresdbi` logic if available, 
            # BUT standard ODBC is safer.
            
            # NOTE: We are assuming `pyodbc` is available.
            # Connection String format: "DRIVER={Ingres};SERVER=@localhost,27832;DATABASE=bench_db;UID=actian;PWD=actian"
            
            # Construct standard ODBC string
            conn_str = (
                f"DRIVER={{Ingres}};SERVER=@{self.connection_params.get('host', 'localhost')},II7;"
                f"DATABASE={self.connection_params.get('database')};"
                f"UID={self.connection_params.get('user')};PWD={self.connection_params.get('password')}"
            )
            self.connection = pyodbc.connect(conn_str, autocommit=True)
            
        except ImportError:
            raise RuntimeError("pyodbc not installed. Please run 'pip install pyodbc'")
        except Exception as e:
            # Fallback/Debug: Print error clearly
            print(f"Actian Connection Failed: {e}")
            raise

    def _run_query_exec(self, sql: str) -> float:
        """
        Executes query via 'docker exec' and 'iiquery' native utility.
        This bypasses the need for a host-side ODBC driver.
        """
        import subprocess
        import time

        # We use a temporary file inside the container to avoid shell escaping issues with complex SQL
        # But for this POC, we'll pipe simple SQL.
        cmd = [
            "sudo", "docker", "exec", "-i", self.container_name,
            "/opt/Actian/Vector/ingres/bin/iiquery", 
            "-uactian", "-p", self.connection_params["database"], "-s"
        ]
        
        start = time.time()
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=sql)
        duration = time.time() - start

        if process.returncode != 0:
            raise RuntimeError(f"Actian Exec Error: {stderr}")
        
        return duration

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
        print(f"Vectorizing {file_path} into Actian table '{table_name}'...")
        
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
