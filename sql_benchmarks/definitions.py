import os
from dagster import Definitions

# 1. FACTORIES (Dynamic Lists)
# We import the lists we explicitly built.
from .assets.data_factory import data_assets
from .assets.ingestion_factory import ingestion_assets
from .assets.benchmark_factory import benchmark_assets

# 2. STATIC ASSETS (Explicit Import)
# STOP using load_assets_from_modules here.
# It creates duplicate keys because it scans imported variables.
from .assets.reporting import performance_dashboard
from .assets.maintenance import cleanup_staging_data

# 3. RESOURCES & INFRA
from .resources.postgres import PostgresEngine
from .resources.duckdb import DuckDBEngine
from .constants import DATA_DIR
from .jobs import benchmark_job
from .sensors import experiment_queue_sensor

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
    cleanup_staging_data
]

defs = Definitions(
    assets=all_assets,
    resources={
        "postgres": PostgresEngine(connection_string=postgres_url),
        "duckdb": DuckDBEngine(data_folder=os.path.join(DATA_DIR, "duckdb"))
    },
    jobs=[benchmark_job],
    sensors=[experiment_queue_sensor]
)
