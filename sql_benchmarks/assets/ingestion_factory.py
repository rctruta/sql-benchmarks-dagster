import os
import yaml
import pandas as pd
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def
from ..constants import ACTIVE_CONFIG_PATH, ROOT_DIR

# 1. LOAD CONFIG
if os.path.exists(ACTIVE_CONFIG_PATH):
    with open(ACTIVE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    ACTIVE_ENGINES = config.get("engines", ["duckdb"])
    
    if 'dataset' not in config or 'tables' not in config['dataset']:
        raise ValueError(f"CRITICAL: '{ACTIVE_CONFIG_PATH}' is missing 'dataset.tables'.")
    TARGET_TABLES = config['dataset']['tables']
else:
    ACTIVE_ENGINES = []
    TARGET_TABLES = []

def get_parquet_path(partition_key, table_name):
    return os.path.join(ROOT_DIR, "data", "staging", f"{table_name}_{partition_key}.parquet")

def make_ingestion_asset(table_name, engine):
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    asset_name = f"{prefix}{table_name}_table"
    group_name = f"{engine}_ingestion"

    # CLEAN DEPENDENCIES: Only depend on the file source.
    # No daisy chaining. No cross-table links.
    current_deps = [f"{table_name}_parquet"]

    @asset(
        name=asset_name,
        partitions_def=partitions_def,
        group_name=group_name,
        deps=current_deps,
        tags={"layer": "storage", "engine": engine},
        required_resource_keys={engine}
    )
    def _ingest_asset(context: AssetExecutionContext):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing: {file_path}")

        db_resource = getattr(context.resources, engine)
        target_table = f"{table_name}_{partition_key}"

        if engine == "postgres":
            context.log.info(f"Loading {file_path} into Postgres table {target_table}...")
            df = pd.read_parquet(file_path)
            engine_obj = db_resource.get_engine()
            df.to_sql(target_table, engine_obj, if_exists='replace', index=False)
            
        elif engine == "duckdb":
            context.log.info(f"Loading {file_path} into DuckDB file...")
            query = f"CREATE OR REPLACE TABLE {target_table} AS SELECT * FROM read_parquet('{file_path}');"
            db_resource.execute_query(query, partition_key=partition_key)

    _ingest_asset.__name__ = f"ingest_{engine}_{table_name}"
    return _ingest_asset

# 2. GENERATION LOOP (Clean)
ingestion_assets = []

for engine in ACTIVE_ENGINES:
    for table in TARGET_TABLES:
        # Create asset without passing any dependent_asset_name
        new_asset = make_ingestion_asset(table, engine)
        ingestion_assets.append(new_asset)