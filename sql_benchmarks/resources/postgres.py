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
from pydantic import ConfigDict, PrivateAttr
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
    docker_image: str = "postgres:15" 
    model_config = ConfigDict(extra='forbid')
    
    _runtime_connection_string: Optional[str] = PrivateAttr(default=None)

    # --- FACTORY METHOD ---
    def _get_client(self) -> PostgresClient:
        # Use runtime string if set (dynamic port), else config default
        target_conn = self._runtime_connection_string or self.connection_string
        return PostgresClient(target_conn)

    # --- IBenchmarkEngine Implementation (Delegation) ---
    def clear_cache(self, settings: dict = None):
        """
        Enforces a multi-layer Cold Cache:
        1. Host Layer: Floods host RAM to evict OS Page Cache.
        2. Database Layer: Recreates the container to wipe DBMS buffer pools.
        """
        thrash_os_cache()
        self.setup_docker(settings)
        self._wait_for_ready()

    def run_query(self, sql: str, partition_key: str, engine_params: Dict[str, Any] = None) -> Optional[float]:
        # engine_params is the 'postgres' namespace: session settings (work_mem, ...)
        self.clear_cache(engine_params)
        client = self._get_client()
        return client.run_query(sql=sql, pg_settings=engine_params)

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        self.setup_docker()      
        self._wait_for_ready()
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def get_engine_name(self) -> str:
        return "postgres"
    
    def get_engine(self):
        target_conn = self._runtime_connection_string or self.connection_string
        return create_engine(target_conn)

    # --- EXTERNAL/SYSTEM/CONFIG HELPERS ---
    def _get_port_from_url(self) -> int:
        try:
            target_conn = self._runtime_connection_string or self.connection_string
            url = make_url(target_conn)
            return url.port or 5432
        except Exception:
            return 5432

    def _check_port_available(self, port: int) -> bool:
        """Returns True if port is free (connect returns non-zero)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) != 0

    def _find_free_port(self, start_port: int = 5432) -> int:
        port = start_port
        while True:
            if self._check_port_available(port):
                return port
            port += 1

    def _wait_for_ready(self, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            try:
                # Use dynamic engine creation
                engine = self.get_engine()
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
        Robust Provisioning using Docker SDK
        """
        # 1. CLEANUP
        self._kill_zombie_container()

        target_port = self._get_port_from_url()

        # 2. DYNAMIC PORT ALLOCATION (Auto-Resolve Conflict)
        # Check if the desired port is free. If not, find a new one.
        is_free = False
        for _ in range(5):
             if self._check_port_available(target_port):
                 is_free = True
                 break
             time.sleep(1)

        if not is_free:
            print(f"[WARN] Port {target_port} is busy. searching for free port...")
            new_port = self._find_free_port(start_port=target_port + 1)
            print(f"[INFO] Switched to available port: {new_port}")
            target_port = new_port
            
            # CRITICAL: Update connection_string so clients connect to the new port
            url = make_url(self.connection_string)
            new_url = url.set(port=new_port)
            self._runtime_connection_string = str(new_url)
            
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
        
        # Retry logic for "Port is already allocated" race condition
        max_retries = 5
        for attempt in range(max_retries):
            try:
                client.containers.run(
                    image=self.docker_image,
                    name=self.container_name,
                    detach=True,
                    ports={f'5432/tcp': target_port},
                    volumes={
                        'pg_bench_data': {'bind': '/var/lib/postgresql/data', 'mode': 'rw'},
                        DATA_DIR: {'bind': '/mnt/data', 'mode': 'rw'}
                    },
                    environment={
                        "POSTGRES_PASSWORD": make_url(self.connection_string).password or "password",
                        "POSTGRES_HOST_AUTH_METHOD": "trust",
                        "POSTGRES_DB": make_url(self.connection_string).database
                    },
                    shm_size="2gb",
                    command=command_args
                )
                break # Success
            except APIError as e:
                # If port is busy or conflict, wait and retry
                if "port is already allocated" in str(e) or "Conflict" in str(e):
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        # Try cleanup again just in case
                        self._kill_zombie_container()
                        continue
                raise RuntimeError(f"Postgres failed to start via Docker SDK: {e}")

        # No wait here. Orchestration layer handles the wait.