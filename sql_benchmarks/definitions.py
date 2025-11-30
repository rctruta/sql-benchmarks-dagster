import os
from dagster import Definitions, load_assets_from_modules

# 1. IMPORT THE FACTORIES
from .assets import (
    data_factory,       # Generates Parquet (Data Gen)
    ingestion_factory,   # Load the factory ingestion (Ingestion)
    benchmark_factory,  # Runs Queries (The Universal Benchmark Runner)
    reporting           # The Dashboard
)

# 2. IMPORT RESOURCES
from .resources.database import DuckDBResource
from .resources.postgres import PostgresResource

# 3. CONFIGURATION (Single Source of Truth)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))

# Paths
data_folder = os.path.join(project_root, "data")
duckdb_path = os.path.join(data_folder, "benchmark.duckdb") # Fallback path
postgres_url = "postgresql://postgres:password@localhost:5432/postgres"

# 4. LOAD ASSET LISTS
# The factories already produced lists of assets. We just grab them.
data_assets = data_factory.data_assets
ingest_assets = ingestion_factory.ingestion_assets # Single list!
bench_assets = benchmark_factory.benchmark_assets

# 5. DEFINE THE SYSTEM
defs = Definitions(
    assets=[
        *data_assets, 
        *ingest_assets, 
        *bench_assets, 
        reporting.performance_dashboard
    ],
    resources={
        "duckdb": DuckDBResource(data_folder=data_folder),
        "postgres": PostgresResource(connection_string=postgres_url) 
    },
)