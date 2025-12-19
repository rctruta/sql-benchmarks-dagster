# sql_benchmarks_dagster/resources/postgres.py (Configuration and Delegation)
import time
import os
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
import socket 
import docker
from docker.errors import NotFound, APIError
from .base_engine import IBenchmarkEngine # We import it for type hinting, but don't inherit
from .postgres_client import PostgresClient 
from pydantic import ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError
from ..utils.system import thrash_os_cache
from ..constants import DATA_DIR

# Inheritance is simplified to prevent MRO conflicts. It satisfies IBenchmarkEngine via Protocol.
class PostgresEngine(ConfigurableResource): 
    
    # --- CONFIGURATION (Immutable) ---
    connection_string: str
    container_name: str = "benchmark_postgres"
    model_config = ConfigDict(extra='forbid')
    
    # --- FACTORY METHOD ---
    def _get_client(self) -> PostgresClient:
        return PostgresClient(self.connection_string)

    # --- IBenchmarkEngine Implementation (Delegation) ---
    def run_query(self, sql: str, partition_key: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        self.setup_docker(scenario_params.get("pg_settings"))
        thrash_os_cache()
        self.clear_cache()
        self._wait_for_ready()
        client = self._get_client() 
        return client.run_query(sql=sql, scenario_params=scenario_params)

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        self.setup_docker()      
        self._wait_for_ready()
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def get_engine_name(self) -> str:
        return "postgres"
    
    def get_engine(self):
        return create_engine(self.connection_string)

    # --- EXTERNAL/SYSTEM/CONFIG HELPERS (Remain Here) ---
    def _get_port_from_url(self) -> int:
        try:
            url = make_url(self.connection_string)
            return url.port or 5432
        except Exception:
            return 5432

    def _check_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) != 0

    def clear_cache(self):
        """Restarts the container using Docker SDK to ensure cold cache."""
        client = docker.from_env()
        try:
            container = client.containers.get(self.container_name)
            container.restart()
        except NotFound:
            # If it doesn't exist, we can't restart it. Setup should have caught this.
            raise RuntimeError(f"Container {self.container_name} not found during cache clear.")
        
        # Retry loop to wait for DB to come up
        retries = 15
        while retries > 0:
            try:
                with self.get_engine().connect() as conn: conn.execute(text("SELECT 1"))
                return
            except OperationalError:
                time.sleep(1); retries -= 1
        raise Exception("Postgres failed to restart.")

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
        raise TimeoutError("Postgres container timed out during restart.")    

    def _kill_zombie_container(self):
        """
        Forcefully removes the container using Docker SDK.
        """
        client = docker.from_env()
        try:
            container = client.containers.get(self.container_name)
            container.remove(force=True)
        except NotFound:
            pass # Already gone
        except APIError as e:
            raise RuntimeError(f"Failed to cleanup container {self.container_name}: {e}")

    def setup_docker(self, settings: dict = None):
        """
        Robust Provisioning using Docker SDK:
        1. Cleanup old containers.
        2. Validate Port Availability.
        3. Use Two-Mount Strategy (Storage vs. Inputs).
        """
        # 1. CLEANUP
        self._kill_zombie_container()

        target_port = self._get_port_from_url()

        # 2. VALIDATE PORT (The logic you requested)
        # We perform a small wait-loop to handle OS socket release time
        port_free = False
        for _ in range(5):
            if self._check_port_available(target_port):
                port_free = True
                break
            time.sleep(1)

        if "localhost" in self.connection_string and not port_free:
             raise RuntimeError(
                f"Port {target_port} is occupied by another service. "
                "Update POSTGRES_PORT env var or stop the local service."
            )

        # 3. PREPARE FILESYSTEM
        # A dedicated home for the DB files prevents "Directory not empty" errors.
        db_storage_path = os.path.join(DATA_DIR, "postgres_db")
        os.makedirs(db_storage_path, exist_ok=True)

        # 4. BUILD & RUN CONTAINER
        client = docker.from_env()
        
        # Construct config commands
        # Postgres entrypoint interprets arguments as config flags if they start with -c
        command_args = []
        if settings:
            for key, val in settings.items():
                command_args.extend(["-c", f"{key}={val}"])
        
        try:
            client.containers.run(
                image="postgres:15",
                name=self.container_name,
                detach=True,
                ports={f'5432/tcp': target_port},
                volumes={
                    'pg_bench_data': {'bind': '/var/lib/postgresql/data', 'mode': 'rw'},
                    DATA_DIR: {'bind': '/mnt/data', 'mode': 'rw'}
                },
                environment={
                    "POSTGRES_PASSWORD": "password",
                    "POSTGRES_HOST_AUTH_METHOD": "trust"
                },
                shm_size="2gb",
                command=command_args
            )
        except APIError as e:
            raise RuntimeError(f"Postgres failed to start via Docker SDK: {e}")

        # No wait here. Orchestration layer handles the wait.