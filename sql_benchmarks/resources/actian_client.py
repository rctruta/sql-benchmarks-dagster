import os
import time
import tempfile
import polars as pl
from typing import Dict, Any, Optional


class ActianClient:
    """
    Stateful Client for Actian Vector on EC2.

    Executes queries via SSH and handles bulk loading via SCP + vwload.
    """

    def __init__(self, connection_params: Dict[str, Any], ssh_params: Dict[str, Any]):
        self.connection_params = connection_params
        self.ssh_params = ssh_params
        self._ssh_client = None

    def _ensure_ssh(self):
        """Establishes SSH client for remote commands."""
        if self._ssh_client is not None:
            try:
                transport = self._ssh_client.get_transport()
                if transport and transport.is_active():
                    return
            except Exception:
                pass
            self._ssh_client = None

        import paramiko

        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh_client.connect(
            hostname=self.ssh_params["ec2_host"],
            username=self.ssh_params["ec2_user"],
            key_filename=self.ssh_params["ssh_key_path"],
            timeout=30
        )

    def _ssh_exec(self, command: str, timeout: int = 300) -> tuple[str, str, int]:
        """Execute a command on the remote EC2 instance."""
        self._ensure_ssh()

        stdin, stdout, stderr = self._ssh_client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        return stdout.read().decode(), stderr.read().decode(), exit_code

    def _scp_to_remote(self, local_path: str, remote_path: str):
        """Copy a file to the remote EC2 instance."""
        self._ensure_ssh()

        from scp import SCPClient

        # Ensure remote directory exists
        remote_dir = os.path.dirname(remote_path)
        self._ssh_exec(f"mkdir -p {remote_dir}")

        with SCPClient(self._ssh_client.get_transport()) as scp:
            scp.put(local_path, remote_path)

        print(f"[Actian] Uploaded {local_path} -> {remote_path}")

    def run_query(self, sql: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        """
        Execute a SQL query on Actian Vector via SSH.

        Uses the native `sql` command on EC2 for reliable execution
        without requiring local ODBC drivers.
        """
        database = self.connection_params["database"]
        sql_path = self.ssh_params["actian_sql_path"]

        # Escape single quotes in SQL for shell
        escaped_sql = sql.replace("'", "'\\''")

        # Build command: echo SQL | sql database
        # The -s flag suppresses headers for cleaner output
        command = f"echo '{escaped_sql}' | {sql_path} {database}"

        start = time.time()
        stdout, stderr, exit_code = self._ssh_exec(command, timeout=600)
        duration = time.time() - start

        if exit_code != 0:
            raise RuntimeError(f"Actian query failed: {stderr}\nSQL: {sql[:200]}...")

        return duration

    def bulk_load(self, file_path: str, table_name: str, partition_key: str = None):
        """
        High-performance bulk load into Actian Vector using vwload.

        Steps:
        1. Convert Parquet to CSV locally (vwload prefers CSV)
        2. SCP the CSV to EC2
        3. Create table schema on Actian
        4. Run vwload on EC2
        5. Cleanup remote files
        """
        print(f"[Actian] Bulk loading {file_path} into table '{table_name}'...")

        remote_data_dir = self.ssh_params["remote_data_dir"]
        vwload_path = self.ssh_params["vwload_path"]
        database = self.connection_params["database"]

        # 1. Read schema and convert to CSV
        df = pl.read_parquet(file_path)

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            local_csv_path = tmp.name
            df.write_csv(local_csv_path, include_header=True)

        try:
            # 2. SCP to EC2
            remote_csv_path = f"{remote_data_dir}/{table_name}.csv"
            self._scp_to_remote(local_csv_path, remote_csv_path)

            # 3. Create table schema
            self._create_table_schema(table_name, df)

            # 4. Run vwload
            # vwload syntax: vwload [options] dbname tablename filename
            vwload_cmd = (
                f"{vwload_path} "
                f"--fdelim ',' "
                f"--header "
                f"--log /tmp/vwload_{table_name}.log "
                f"{database} {table_name} {remote_csv_path}"
            )

            print(f"[Actian] Running vwload: {vwload_cmd}")
            stdout, stderr, exit_code = self._ssh_exec(vwload_cmd, timeout=600)

            if exit_code != 0:
                # Try to get the log file for more details
                log_stdout, _, _ = self._ssh_exec(f"cat /tmp/vwload_{table_name}.log 2>/dev/null || echo 'No log'")
                raise RuntimeError(
                    f"vwload failed (exit {exit_code}):\n"
                    f"stderr: {stderr}\n"
                    f"log: {log_stdout}"
                )

            print(f"[Actian] Loaded {df.height} rows into {table_name}")

            # 5. Optimize table for analytics
            self._optimize_table(table_name)

            # 6. Cleanup remote CSV
            self._ssh_exec(f"rm -f {remote_csv_path}")

        finally:
            # Cleanup local temp file
            if os.path.exists(local_csv_path):
                os.remove(local_csv_path)

    def _create_table_schema(self, table_name: str, df: pl.DataFrame):
        """Create table schema in Actian based on Polars DataFrame."""

        # Map Polars types to Actian Vector types
        type_map = {
            pl.Int8: "TINYINT",
            pl.Int16: "SMALLINT",
            pl.Int32: "INTEGER",
            pl.Int64: "BIGINT",
            pl.UInt8: "SMALLINT",
            pl.UInt16: "INTEGER",
            pl.UInt32: "BIGINT",
            pl.UInt64: "BIGINT",
            pl.Float32: "FLOAT4",
            pl.Float64: "FLOAT8",
            pl.String: "VARCHAR(1000)",
            pl.Utf8: "VARCHAR(1000)",
            pl.Boolean: "BOOLEAN",
            pl.Date: "DATE",
            pl.Datetime: "TIMESTAMP",
        }

        columns = []
        for col_name, dtype in df.schema.items():
            # Get base type, handle parameterized types like Datetime
            actian_type = type_map.get(type(dtype), None)
            if actian_type is None:
                actian_type = type_map.get(dtype, "VARCHAR(1000)")

            # Handle datetime subtypes
            if isinstance(dtype, pl.Datetime):
                actian_type = "TIMESTAMP"

            columns.append(f'"{col_name}" {actian_type}')

        columns_sql = ", ".join(columns)

        # Drop and recreate for clean state
        drop_sql = f"DROP TABLE IF EXISTS {table_name}"
        create_sql = f"CREATE TABLE {table_name} ({columns_sql})"

        self._execute_sql(drop_sql)
        self._execute_sql(create_sql)

        print(f"[Actian] Created table {table_name} with {len(columns)} columns")

    def _optimize_table(self, table_name: str):
        """Optimize table for analytical queries."""
        # MODIFY TO COMBINE reorganizes data for better scan performance
        try:
            self._execute_sql(f"MODIFY {table_name} TO COMBINE")
            print(f"[Actian] Optimized table {table_name}")
        except Exception as e:
            print(f"[Actian] Warning: MODIFY TO COMBINE failed (non-fatal): {e}")

    def _execute_sql(self, sql: str):
        """Execute a SQL statement (DDL/utility) without timing."""
        database = self.connection_params["database"]
        sql_path = self.ssh_params["actian_sql_path"]

        escaped_sql = sql.replace("'", "'\\''")
        command = f"echo '{escaped_sql}' | {sql_path} {database}"

        stdout, stderr, exit_code = self._ssh_exec(command, timeout=120)

        if exit_code != 0:
            raise RuntimeError(f"SQL execution failed: {stderr}\nSQL: {sql}")

    def close(self):
        """Close SSH connection."""
        if self._ssh_client:
            self._ssh_client.close()
            self._ssh_client = None
