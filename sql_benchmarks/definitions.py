import os
from dagster import Definitions, load_assets_from_modules

# 1. Import Asset Modules
from .assets import (
    data_gen, 
    duckdb_ingestion, 
    duckdb_factory,
    postgres_ingestion,
    postgres_factory
)

# 2. Import Resources
from .resources.database import DuckDBResource
from .resources.postgres import PostgresResource

# 3. Path & Config Logic
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))

# DuckDB Config (Calculated Path)
duckdb_path = os.path.join(project_root, "data", "benchmark.duckdb")

# Postgres Config (Connection String)
postgres_url = "postgresql://postgres:password@localhost:5432/postgres"

# 4. Load Assets
data_assets = load_assets_from_modules([data_gen])

duck_assets = [
    *duckdb_ingestion.ingestion_assets, 
    *duckdb_factory.benchmark_assets
]

pg_assets = [
    *postgres_ingestion.postgres_ingest_assets, 
    *postgres_factory.postgres_bench_assets
]

# 5. Definitions
defs = Definitions(
    assets=[*data_assets, *duck_assets, *pg_assets],
    resources={
        # Now both look identical: Resource(config=variable)
        "database": DuckDBResource(database_path=duckdb_path),
        "pg": PostgresResource(connection_string=postgres_url) 
    },
)