from dagster import Definitions, load_assets_from_modules

# 1. IMPORT ARCHITECTURE (The V5 Factories)
from .assets import (
    data_factory,       # Generates Parquet (Data Gen)
    ingestion_factory,  # Loads Tables (DuckDB + Postgres)
    benchmark_factory,  # Runs Queries (DuckDB + Postgres)
    reporting           # The Dashboard
)

# 2. IMPORT RESOURCES
from .resources.duckdb import DuckDBResource
from .resources.postgres import PostgresResource

# 3. IMPORT CONSTANTS (No more path math here)
from .constants import DATA_DIR

# 4. CONFIGURATION
# We point DuckDB to the folder (Shared Nothing Architecture)
duckdb_data_folder = DATA_DIR

# We define Postgres connection (Standard Docker defaults)
# In V6, you could wrap this in os.getenv("PG_URL", ...)
postgres_url = "postgresql://postgres:password@localhost:5432/postgres"

# 5. AGGREGATE ASSETS
# We pull the generated lists from the factories
assets_list = [
    *data_factory.data_assets,
    *ingestion_factory.ingestion_assets,
    *benchmark_factory.benchmark_assets,
    reporting.performance_dashboard
]

# 6. SYSTEM DEFINITION
defs = Definitions(
    assets=assets_list,
    resources={
        # Key names MUST match the 'engines' list in experiments.yaml
        "duckdb": DuckDBResource(data_folder=duckdb_data_folder),
        "postgres": PostgresResource(connection_string=postgres_url)
    },
)