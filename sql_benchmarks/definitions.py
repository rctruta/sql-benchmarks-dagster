from dagster import Definitions, load_assets_from_modules

# Import from the assets folder
from .assets import data_gen 
from .partitions import size_partitions

# Explicitly load the assets
data_gen_assets = load_assets_from_modules([data_gen])

defs = Definitions(
    assets=[*data_gen_assets],
    resources={
        # This key 'database' is how we will ask for it in our assets later
        "database": DuckDBResource(database_path="data/benchmark.duckdb") 
    },
)