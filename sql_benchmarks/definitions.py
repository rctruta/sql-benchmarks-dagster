import os
from dagster import Definitions, load_assets_from_modules

from .assets import data_gen, ingestion, query_factory 
from .resources.database import DuckDBResource
from .resources.docker_duckdb import DockerDuckDBResource

# 1. CALCULATE PATHS DYNAMICALLY
# This finds the file's current location, then goes up 2 levels to the project root.
# Example result: /Users/ramona/Projects/sql-benchmark-dagster/
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))

# 2. DEFINE THE DATABASE PATH
# The Folder (For Docker to mount)
data_path = os.path.join(project_root, "data")
# The File (For the local Resource to connect to)
db_path = os.path.join(project_root, "data", "benchmark.duckdb")

# 3. LOAD ASSETS
ingest_assets = ingestion.ingestion_assets 
benchmark_assets = query_factory.benchmark_assets
data_gen_assets = load_assets_from_modules([data_gen])

defs = Definitions(
    assets=[*data_gen_assets, *ingest_assets, *benchmark_assets],
    resources={
        # We pass the absolute path to the resource
        "database": DuckDBResource(database_path=db_path),
        "runner": DockerDuckDBResource(host_data_path=data_path)
    },
)
