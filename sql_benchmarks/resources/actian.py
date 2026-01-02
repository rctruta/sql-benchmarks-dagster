import os
import time
import docker
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
from pydantic import ConfigDict, PrivateAttr
from .base_engine import IBenchmarkEngine
from .actian_client import ActianClient

class ActianEngine(ConfigurableResource):
    """
    Dagster Resource for Actian Vector / X.
    Handles the Docker container lifecycle and provides cold-cache enforcement.
    """
    
    # --- CONFIGURATION ---
    host: str = "localhost"
    port: int = 27832
    user: str = "actian"
    password: str = "password"
    database: str = "db"
    container_name: str = "benchmark_actian"
    docker_image: str = "actian/vector-ce:latest"
    model_config = ConfigDict(extra='forbid')

    # --- FACTORY METHOD ---
    def _get_client(self) -> ActianClient:
        connection_params = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database
        }
        return ActianClient(connection_params)

    # --- IBenchmarkEngine Implementation ---
    
    def get_engine_name(self) -> str:
        return "actian"

    def clear_cache(self, settings: dict = None):
        """
        Enforces a multi-layer Cold Cache:
        1. Host Layer: Floods host RAM to evict OS Page Cache.
        2. Database Layer: Recreates the container to wipe DBMS buffer pools.
        """
        from ..utils.system import thrash_os_cache
        thrash_os_cache()
        self.setup_docker(settings)
        self._wait_for_ready()

    def run_query(self, sql: str, partition_key: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        self.clear_cache(scenario_params.get("actian_settings"))
        client = self._get_client()
        return client.run_query(sql, scenario_params)

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        self.setup_docker()
        self._wait_for_ready()
        client = self._get_client()
        client.bulk_load(filepath, table_name, partition_key)

    def _wait_for_ready(self, timeout=60):
        import socket
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection((self.host, self.port), timeout=1):
                    return
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(2)
        raise TimeoutError(f"Actian container '{self.container_name}' failed to come online at {self.host}:{self.port}")

    def _kill_zombie_container(self):
        client = docker.from_env()
        try:
            container = client.containers.get(self.container_name)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass

    def setup_docker(self, settings: dict = None):
        """
        Robust Provisioning: Recreates the container to ensure a Cold Cache.
        """
        # 1. CLEANUP
        self._kill_zombie_container()

        # 2. RUN CONTAINER
        client = docker.from_env()
        from ..constants import DATA_DIR
        
        # Construct environment from config
        env = {
            "AV_PASSWORD": self.password,
        }

        try:
            client.containers.run(
                image=self.docker_image,
                name=self.container_name,
                detach=True,
                ports={
                    '27832/tcp': self.port,
                    '27839/tcp': 27839 # JDBC
                },
                volumes={
                    'actian_bench_data': {'bind': '/home/actian/data', 'mode': 'rw'},
                    DATA_DIR: {'bind': '/mnt/data', 'mode': 'rw'}
                },
                environment=env,
                shm_size="2gb"
            )
        except Exception as e:
            raise RuntimeError(f"Actian failed to start via Docker: {e}")
