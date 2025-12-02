import os
import polars as pl
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def
from ..constants import ROOT_DIR
from ..utils.common import load_active_config

try:
    CTX = load_active_config()
    ACTIVE_ENGINES = CTX['engines']
    TARGET_TABLES = CTX['table_names']
except Exception:
    ACTIVE_ENGINES = []
    TARGET_TABLES = []

def get_parquet_path(partition_key, table_name):
    return os.path.join(ROOT_DIR, "data", "staging", f"{table_name}_{partition_key}.parquet")

def make_ingestion_asset(table_name, engine, dependent_asset_name=None):
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    asset_name = f"{prefix}{table_name}_table"
    group_name = f"{engine}_ingestion"

    current_deps = [f"{table_name}_parquet"]
    
    # --- THE FIX: Restore Daisy Chain ---
    if dependent_asset_name:
        current_deps.append(dependent_asset_name)

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
            context.log.info(f"Loading into Postgres...")
            df = pl.read_parquet(file_path)
            df.write_database(target_table, db_resource.connection_string, if_table_exists="replace", engine="sqlalchemy")
            
        elif engine == "duckdb":
            context.log.info(f"Loading into DuckDB...")
            query = f"CREATE OR REPLACE TABLE {target_table} AS SELECT * FROM read_parquet('{file_path}');"
            db_resource.execute_query(query, partition_key=partition_key)

    _ingest_asset.__name__ = f"ingest_{engine}_{table_name}"
    return _ingest_asset

ingestion_assets = []
for engine in ACTIVE_ENGINES:
    previous_asset_name = None
    for table in TARGET_TABLES:
        # Only Chain DuckDB
        dep = previous_asset_name if engine == "duckdb" else None
        
        new_asset = make_ingestion_asset(table, engine, dep)
        ingestion_assets.append(new_asset)
        
        previous_asset_name = f"{engine}_table" if engine == "duckdb" else f"pg_{table}_table"
        # Note: We construct the name manually to match the asset name logic
        prefix = "pg_" if engine == "postgres" else f"{engine}_"
        previous_asset_name = f"{prefix}{table}_table"