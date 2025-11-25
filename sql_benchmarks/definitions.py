import os
from dagster import Definitions, load_assets_from_modules

from .assets import data_gen, benchmarks
from .resources.database import DuckDBResource

# 1. CALCULATE PATHS DYNAMICALLY
# This finds the file's current location, then goes up 2 levels to the project root.
# Example result: /Users/ramona/Projects/sql-benchmark-dagster/
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))

# 2. DEFINE THE DATABASE PATH
# We force the DB to live in the 'data' folder at the root.
db_path = os.path.join(project_root, "data", "benchmark.duckdb")

# 3. LOAD ASSETS
all_assets = load_assets_from_modules([data_gen, benchmarks])

defs = Definitions(
    assets=[*all_assets],
    resources={
        # We pass the absolute path to the resource
        "database": DuckDBResource(database_path=db_path)
    },
)