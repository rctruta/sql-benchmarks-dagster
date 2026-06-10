import time
import socket
import docker
from docker.errors import NotFound, APIError
from dagster import ConfigurableResource
from typing import Dict, Any, Optional
from pydantic import ConfigDict
from .typedb_client import TypeDBClient
from ..utils.system import thrash_os_cache

# ---------------------------------------------------------------------------
# Module-level partition tracker
#
# Records which TypeDB database names have already been initialised (drop +
# create) in the current process.  This lets bulk_load be called once per
# table while only wiping the database on the very first call for a given
# partition, so multiple entity types can coexist in the same database.
#
# The set is naturally cleared between benchmark runs because execute_run.py
# starts a fresh Python process each time.
# ---------------------------------------------------------------------------
_INITIALIZED_PARTITIONS: set = set()


class TypeDBEngine(ConfigurableResource):
    """
    Dagster Resource for TypeDB (local Docker).

    Manages the Docker container lifecycle and provides cold-cache enforcement
    by killing and recreating the container (data is preserved in a named
    Docker volume, identical to the PostgresEngine approach).

    Multi-table support
    -------------------
    When an experiment loads several tables into the same partition (e.g. a
    supply-chain hypergraph with supplier, buyer, product, supply_contract),
    this engine initialises the TypeDB database *once* on the first
    ``bulk_load`` call and then adds each subsequent table additively.

    Relation tables are declared via ``relation_configs``::

        relation_configs = {
            "supply_contract": {          # base table name (without partition key)
                "roles": {
                    "supplier_id": ["supplier", "supplier_role"],
                    "buyer_id":    ["buyer",    "buyer_role"],
                    "product_id":  ["product",  "product_role"],
                },
                "attributes": ["volume", "price_per_unit"],
            }
        }

    Entity tables (not in ``relation_configs``) are loaded via
    ``TypeDBClient.load_entity()``.  Relation tables are loaded via
    ``TypeDBClient.bulk_load_relation()`` using a ``match … insert`` pattern.
    """

    # --- CONFIGURATION ---
    address: str = "127.0.0.1:1729"
    container_name: str = "bench_typedb"
    docker_image: str = "typedb/typedb:latest"
    relation_configs: Dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")

    # ------------------------------------------------------------------
    # IBenchmarkEngine interface
    # ------------------------------------------------------------------

    def get_engine_name(self) -> str:
        return "typedb"

    def clear_cache(self, settings: dict = None):
        """
        Enforces a cold-cache run:
        1. Flood host RAM to evict the OS page cache.
        2. Kill and recreate the TypeDB container (clears DBMS buffer pool).
           Data survives because it lives in a named Docker volume.
        """
        thrash_os_cache()
        self._restart_container()
        self._wait_for_ready()

    def run_query(self, sql: str, partition_key: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        self.clear_cache()
        client = self._get_client(partition_key)
        return client.run_query(sql, scenario_params)

    def bulk_load(self, filepath: str, table_name: str, partition_key: str) -> None:
        """
        Load one table into TypeDB for the given partition.

        On the *first* call for a partition the database is dropped and
        recreated (clean slate).  Subsequent calls for the same partition add
        to the existing database so that multiple entity types and relations
        can coexist.

        Entity tables use ``TypeDBClient.load_entity()``.
        Relation tables (declared in ``relation_configs``) use
        ``TypeDBClient.bulk_load_relation()`` with a match-insert pattern.
        """
        self._ensure_container()
        self._wait_for_ready()
        client = self._get_client(partition_key)
        db_key = self._db_name(partition_key)

        # Initialise DB once per partition per process
        if db_key not in _INITIALIZED_PARTITIONS:
            client.initialize_db()
            _INITIALIZED_PARTITIONS.add(db_key)

        # Dispatch: relation vs entity
        base_name = self._base_table_name(table_name, partition_key)
        if base_name in self.relation_configs:
            config = self.relation_configs[base_name]
            role_map = self._resolve_role_map(config["roles"], partition_key)
            client.bulk_load_relation(
                filepath,
                table_name,
                role_map,
                config.get("attributes", []),
            )
            # After loading the relation, optionally define an inference rule
            # so that subsequent read queries can traverse the graph transitively.
            if config.get("inference") == "transitive":
                role_values = list(role_map.values())
                entity_type = role_values[0][0]  # same for both roles (self-referential)
                from_role   = role_values[0][1]
                to_role     = role_values[1][1]
                tql = self._build_transitive_inference_schema(
                    table_name, entity_type, from_role, to_role
                )
                client.apply_inference_schema(tql)
        else:
            client.load_entity(filepath, table_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self, partition_key: str) -> TypeDBClient:
        db_name = self._db_name(partition_key)
        return TypeDBClient(address=self.address, db_name=db_name)

    @staticmethod
    def _db_name(partition_key: str) -> str:
        """Convert a partition key into a valid TypeDB database name."""
        return f"bench_{partition_key}".replace("-", "_").replace("~", "_")

    @staticmethod
    def _base_table_name(table_name: str, partition_key: str) -> str:
        """
        Strip the partition-key suffix to obtain the base table name.

        Example: ``supply_contract_small`` with ``small`` → ``supply_contract``.
        """
        suffix = f"_{partition_key}"
        return table_name[: -len(suffix)] if table_name.endswith(suffix) else table_name

    @staticmethod
    def _build_transitive_inference_schema(
        relation_type: str,
        entity_type: str,
        from_role: str,
        to_role: str,
    ) -> str:
        """
        Generate a TypeQL ``define`` block containing a recursive stream function
        that computes the transitive closure over ``relation_type``.

        TypeDB 3.x does not support inference rules (``rule`` keyword) — functions
        are the supported mechanism.  The generated ``fun reachable`` uses the
        ``{ base } or { recursive }`` pattern inside its ``match`` body; TypeDB
        evaluates it lazily with tabling so cycles terminate automatically.

        Args:
            relation_type: Fully qualified relation name, e.g.
                           ``supplies_small_small``.
            entity_type:   Entity type that plays both roles (self-referential),
                           e.g. ``company_small_small``.
            from_role:     Name of the "source" role, e.g. ``seller_role``.
            to_role:       Name of the "destination" role, e.g. ``buyer_role``.

        Returns:
            TypeQL define block as a string ready to pass to
            ``TypeDBClient.apply_inference_schema()``.

        Example output::

            define
              fun reachable($from: company_small_small) -> { company_small_small }:
              match
                { (seller_role: $from, buyer_role: $to) isa supplies_small_small; } or
                { (seller_role: $from, buyer_role: $via) isa supplies_small_small;
                  let $to in reachable($via); };
              return { $to };
        """
        return (
            "define\n"
            f"  fun reachable($from: {entity_type}) -> {{ {entity_type} }}:\n"
            "  match\n"
            f"    {{ ({from_role}: $from, {to_role}: $to) isa {relation_type}; }} or\n"
            f"    {{ ({from_role}: $from, {to_role}: $via) isa {relation_type};\n"
            "      let $to in reachable($via); };\n"
            "  return { $to };"
        )

    @staticmethod
    def _resolve_role_map(role_configs: dict, partition_key: str) -> dict:
        """
        Expand base entity type names in role configs to full runtime names
        by appending the partition key.

        Input:  ``{"supplier_id": ["supplier", "supplier_role"]}``
        Output: ``{"supplier_id": ["supplier_small", "supplier_role"]}``
        """
        return {
            col: [f"{entry[0]}_{partition_key}", entry[1]]
            for col, entry in role_configs.items()
        }

    # ------------------------------------------------------------------
    # Docker lifecycle
    # ------------------------------------------------------------------

    def _ensure_container(self):
        """Start the container if it is not already running."""
        client = docker.from_env()
        try:
            container = client.containers.get(self.container_name)
            if container.status != "running":
                container.start()
        except NotFound:
            self._start_container(client)

    def _restart_container(self):
        """Kill any existing container and start a fresh one."""
        client = docker.from_env()
        self._kill_container(client)
        self._start_container(client)

    def _kill_container(self, client=None):
        client = client or docker.from_env()
        try:
            container = client.containers.get(self.container_name)
            container.remove(force=True)
        except NotFound:
            pass
        except APIError as e:
            raise RuntimeError(f"Failed to remove TypeDB container '{self.container_name}': {e}")

    def _start_container(self, client=None):
        client = client or docker.from_env()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                client.containers.run(
                    image=self.docker_image,
                    name=self.container_name,
                    detach=True,
                    ports={"1729/tcp": 1729},
                    volumes={
                        "typedb_bench_data": {
                            "bind": "/var/lib/typedb/data",
                            "mode": "rw",
                        }
                    },
                )
                return
            except APIError as e:
                if ("port is already allocated" in str(e) or "Conflict" in str(e)) and attempt < max_retries - 1:
                    time.sleep(2)
                    self._kill_container(client)
                    continue
                raise RuntimeError(f"TypeDB container failed to start: {e}")

    def _wait_for_ready(self, timeout: int = 60):
        """
        Poll port 1729 until TypeDB accepts TCP connections, then attempt
        a lightweight driver ping to confirm the server is fully up.
        """
        start = time.time()
        while time.time() - start < timeout:
            if self._port_open():
                try:
                    from typedb.driver import TypeDB, Credentials, DriverOptions  # noqa: PLC0415
                    creds = Credentials("admin", "password")
                    opts = DriverOptions(is_tls_enabled=False)
                    with TypeDB.driver(self.address, creds, opts) as driver:
                        driver.databases.all()
                    return
                except Exception:
                    pass
            time.sleep(1)

        raise TimeoutError(f"TypeDB at {self.address} did not become ready within {timeout}s")

    def _port_open(self) -> bool:
        host, port = self.address.split(":")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, int(port))) == 0
