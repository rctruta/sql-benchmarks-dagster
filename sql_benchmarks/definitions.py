import os
from dagster import Definitions

# 1. FACTORIES (Dynamic Lists)
# We import the lists we explicitly built.
from .assets.data_factory import data_assets
from .assets.ingestion_factory import ingestion_assets
from .assets.benchmark_factory import benchmark_assets
from .assets.semantic_gate import get_semantic_gate_assets

# 2. STATIC ASSETS (Explicit Import)
# STOP using load_assets_from_modules here.
# It creates duplicate keys because it scans imported variables.
from .assets.reporting import performance_dashboard
from .assets.maintenance import cleanup_staging_data
from .assets.data_quality import quality_assets

semantic_gate_assets = get_semantic_gate_assets(benchmark_assets)

# 3. RESOURCES & INFRA
from .resources.postgres import PostgresEngine
from .resources.duckdb import DuckDBEngine
from .resources.actian import ActianEngine
from .resources.typedb_engine import TypeDBEngine
from .resources.quack import QuackEngine
from .constants import DATA_DIR
from .jobs import benchmark_job
# from .sensors import experiment_queue_sensor

# 4. CONFIG
pg_user = os.getenv("POSTGRES_USER", "postgres")
pg_password = os.getenv("POSTGRES_PASSWORD", "password")
pg_host = os.getenv("POSTGRES_HOST", "localhost")
pg_port = os.getenv("POSTGRES_PORT", "5432")
pg_db = os.getenv("POSTGRES_DB", "postgres")

postgres_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"

# 5. Definitions
all_assets = [
    *data_assets,
    *ingestion_assets,
    *benchmark_assets,
    performance_dashboard,
    cleanup_staging_data,
    *quality_assets,
    *semantic_gate_assets
]

typedb_address = os.getenv("TYPEDB_ADDRESS", "127.0.0.1:1729")

# ---------------------------------------------------------------------------
# Relation configs — keyed by base table name (no partition-key suffix).
# Used by TypeDBEngine.bulk_load to dispatch to bulk_load_relation.
# ---------------------------------------------------------------------------

# Supply-chain hypergraph (3-way: supplier × buyer × product)
SUPPLY_CHAIN_RELATION_CONFIGS = {
    "supply_contract": {
        "roles": {
            "supplier_id": ["supplier", "supplier_role"],
            "buyer_id":    ["buyer",    "buyer_role"],
            "product_id":  ["product",  "product_role"],
        },
        "attributes": ["volume", "price_per_unit"],
    }
}

# Recursive supply-graph (self-referential: company × company)
# Both roles are played by the same entity type — TypeDB handles this natively.
# "inference": "transitive" triggers _build_transitive_inference_schema after
# the relation is loaded, adding a 'reachable' relation + recursive rule so that
# q_transitive_closure.sql can query full reachability without explicit recursion.
RECURSIVE_GRAPH_RELATION_CONFIGS = {
    "supplies": {
        "roles": {
            "from_id": ["company", "seller_role"],
            "to_id":   ["company", "buyer_role"],
        },
        "attributes": [],
        "inference": "transitive",
    }
}

# Active relation config — switch this to match the current experiment.
# The TypeDBEngine is instantiated once at Dagster load time, so only one
# experiment's relation config can be active per process.
ACTIVE_RELATION_CONFIGS = RECURSIVE_GRAPH_RELATION_CONFIGS

defs = Definitions(
    assets=all_assets,
    resources={
        "postgres": PostgresEngine(connection_string=postgres_url),
        "duckdb": DuckDBEngine(data_folder=os.path.join(DATA_DIR, "duckdb")),
        "quack": QuackEngine(
            data_folder=os.path.join(DATA_DIR, "quack"),
            port=int(os.getenv("SB_QUACK_PORT", "9494")),
            token=os.getenv("SB_QUACK_TOKEN", "sb-local-quack-token"),
        ),
        "actian": ActianEngine(),
        "typedb": TypeDBEngine(
            address=typedb_address,
            relation_configs=ACTIVE_RELATION_CONFIGS,
        ),
    },
    jobs=[benchmark_job],
)
