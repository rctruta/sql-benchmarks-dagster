import os
from dagster import asset, AssetExecutionContext
from ..resources.database import DuckDBResource
from ..partitions import size_partitions

TARGET_TABLES = ["customers", "orders"]

def get_parquet_path(partition_key, table_name):
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(PROJECT_ROOT, "data", "staging", f"{table_name}_{partition_key}.parquet")

def build_ingestion_asset(table_name, dependent_asset_name=None):
    
    # 1. Define Dependencies using STRINGS
    # This was the fix. We use the name "customers_table", not the object.
    current_deps = [f"{table_name}_parquet"]
    
    if dependent_asset_name:
        current_deps.append(dependent_asset_name)

    @asset(
        name=f"{table_name}_table",
        partitions_def=size_partitions,
        group_name="ingestion",
        deps=current_deps
    )
    def _ingest_asset(context: AssetExecutionContext, database: DuckDBResource):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Could not find parquet file: {file_path}")

        # Execute
        query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{file_path}');"
        database.execute_query(query)
        context.log.info(f"Created table '{table_name}'")

    # We update the internal name just to be safe (good practice for factories)
    _ingest_asset.__name__ = f"ingest_{table_name}"
    
    return _ingest_asset

# --- CHAINING LOGIC (Using Strings) ---
ingestion_assets = []
previous_asset_name = None

for table in TARGET_TABLES:
    # Pass the NAME of the previous table (e.g., "customers_table")
    new_asset = build_ingestion_asset(table, dependent_asset_name=previous_asset_name)
    
    ingestion_assets.append(new_asset)
    
    # Set the pointer for the next loop to be THIS table's name
    previous_asset_name = f"{table}_table"