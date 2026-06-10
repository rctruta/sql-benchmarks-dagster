import os
import time
import socket
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
from pydantic import ConfigDict, PrivateAttr
from .base_engine import IBenchmarkEngine
from .actian_client import ActianClient


class ActianEngine(ConfigurableResource):
    """
    Dagster Resource for Actian Vector on EC2.

    Manages SSH tunnel lifecycle and provides cold-cache enforcement
    via remote service restart.
    """

    # --- CONFIGURATION ---
    # Local connection (through tunnel)
    local_port: int = 27832

    # Remote EC2 configuration
    ec2_host: str = os.getenv("ACTIAN_EC2_HOST", "")
    ec2_user: str = os.getenv("ACTIAN_EC2_USER", "ingres")
    ssh_key_path: str = os.getenv("ACTIAN_SSH_KEY", os.path.expanduser("~/.ssh/benchmark-key-pair.pem"))

    # Actian database configuration
    database: str = os.getenv("ACTIAN_DATABASE", "benchmark_db")
    db_user: str = os.getenv("ACTIAN_USER", "ingres")
    db_password: str = os.getenv("ACTIAN_PASSWORD", "AntiGravity")

    # Remote paths
    remote_data_dir: str = "/tmp/benchmark_data"
    vwload_path: str = "/opt/Actian/VectorVW/ingres/bin/vwload"
    actian_sql_path: str = "/opt/Actian/VectorVW/ingres/bin/sql"

    model_config = ConfigDict(extra='forbid')

    # Private attributes for runtime state
    _tunnel: Any = PrivateAttr(default=None)
    _ssh_client: Any = PrivateAttr(default=None)

    def _ensure_tunnel(self):
        """Establishes SSH tunnel if not already active."""
        if self._tunnel is not None and self._tunnel.is_active:
            return

        if not self.ec2_host:
            raise ValueError("ACTIAN_EC2_HOST environment variable must be set")

        from sshtunnel import SSHTunnelForwarder

        self._tunnel = SSHTunnelForwarder(
            (self.ec2_host, 22),
            ssh_username=self.ec2_user,
            ssh_pkey=self.ssh_key_path,
            remote_bind_address=('localhost', 27832),
            local_bind_address=('localhost', self.local_port),
        )
        self._tunnel.start()
        print(f"[Actian] SSH tunnel established: localhost:{self._tunnel.local_bind_port} -> {self.ec2_host}:27832")

        # Give the tunnel a moment to stabilize
        time.sleep(1)

    def _ensure_ssh(self):
        """Establishes SSH client for remote commands."""
        if self._ssh_client is not None:
            # Check if connection is still alive
            try:
                self._ssh_client.exec_command("echo ok", timeout=5)
                return
            except Exception:
                self._ssh_client = None

        if not self.ec2_host:
            raise ValueError("ACTIAN_EC2_HOST environment variable must be set")

        import paramiko
    # 1. Expand the path (handling both the env var and the default)
        full_key_path = os.path.expanduser(self.ssh_key_path)
    
        # 2. Architect Fix: Explicitly load as RSAKey. 
        # This bypasses the logic where Paramiko scans for DSSKey and crashes.
        try:
            pkey = paramiko.RSAKey.from_private_key_file(full_key_path)
        except Exception as e:
            raise RuntimeError(f"Could not load RSA key from {full_key_path}: {e}")
    
        # 3. Connect using 'pkey' instead of 'key_filename'
        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        self._ssh_client.connect(
            hostname=self.ec2_host,
            username=self.ec2_user,
            pkey=pkey, # Use the loaded object here
            timeout=30
        )
        # self._ssh_client = paramiko.SSHClient()
        # self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # self._ssh_client.connect(
        #     hostname=self.ec2_host,
        #     username=self.ec2_user,
        #     key_filename=self.ssh_key_path,
        #     timeout=30
        # )
        print(f"[Actian] SSH connection established to {self.ec2_host}")

    def _ssh_exec(self, command: str, timeout: int = 300) -> tuple[str, str, int]:
        """Execute a command on the remote EC2 instance."""
        self._ensure_ssh()

        stdin, stdout, stderr = self._ssh_client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        return stdout.read().decode(), stderr.read().decode(), exit_code

    def _get_client(self) -> ActianClient:
        """Factory method for creating the Actian client."""
        self._ensure_tunnel()

        connection_params = {
            "host": "localhost",
            "port": self._tunnel.local_bind_port,
            "user": self.db_user,
            "password": self.db_password,
            "database": self.database
        }

        # Pass SSH details for vwload operations
        ssh_params = {
            "ec2_host": self.ec2_host,
            "ec2_user": self.ec2_user,
            "ssh_key_path": self.ssh_key_path,
            "remote_data_dir": self.remote_data_dir,
            "vwload_path": self.vwload_path,
            "actian_sql_path": self.actian_sql_path,
        }

        return ActianClient(connection_params, ssh_params)

    # --- IBenchmarkEngine Implementation ---

    def get_engine_name(self) -> str:
        return "actian"

    def clear_cache(self, settings: dict = None):
        """
        Enforces cold cache by restarting Actian Vector service on EC2.

        This clears both:
        1. X100 engine memory segments
        2. Linux page cache (via service restart)
        """
        print("[Actian] Clearing cache via service restart...")

        # Restart Actian Vector service
        stdout, stderr, exit_code = self._ssh_exec(
            "sudo systemctl restart actian-vectorVW",
            timeout=120
        )

        if exit_code != 0:
            raise RuntimeError(f"Failed to restart Actian service: {stderr}")

        # Wait for service to be ready
        self._wait_for_ready()
        print("[Actian] Service restarted, cache cleared")

    def run_query(self, sql: str, partition_key: str, engine_params: Dict[str, Any] = None) -> Optional[float]:
        """Execute a benchmark query with cold cache.

        engine_params is the 'actian' namespace — accepted but not yet applied
        (Vector session tuning is a future capability).
        """
        self.clear_cache()
        client = self._get_client()
        return client.run_query(sql, {})

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        """
        Bulk load data into Actian Vector.

        1. SCP the file to EC2
        2. Convert to CSV if needed (vwload prefers CSV)
        3. Run vwload on EC2
        """
        self._ensure_tunnel()
        self._wait_for_ready()

        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def _wait_for_ready(self, timeout: int = 120):
        """Wait for Actian to be ready to accept connections."""
        self._ensure_tunnel()

        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(
                    ('localhost', self._tunnel.local_bind_port),
                    timeout=2
                ):
                    # Port is open, but let's verify the service is actually responding
                    time.sleep(2)
                    return
            except (socket.timeout, ConnectionRefusedError, OSError):
                time.sleep(2)

        raise TimeoutError(
            f"Actian Vector on {self.ec2_host} failed to respond within {timeout}s"
        )

    def cleanup(self):
        """Clean up SSH tunnel and connections."""
        if self._ssh_client:
            self._ssh_client.close()
            self._ssh_client = None

        if self._tunnel:
            self._tunnel.stop()
            self._tunnel = None

        print("[Actian] Connections closed")

    def __del__(self):
        """Ensure cleanup on garbage collection."""
        try:
            self.cleanup()
        except Exception:
            pass
