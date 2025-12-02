import os
import polars as pl
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def

# STRICT IMPORTS: Consistency with the rest of the system
from ..constants import DATA_DIR
from ..utils.common import load_context

# 1. LOAD CONTEXT
# Fail fast if config is bad.
CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
TARGET_TABLES = CTX['tables'] # List of table names

def get_parquet_path(partition_key, table_name):
    # Use the canonical DATA_DIR from constants
    return os.path.join(DATA_DIR, "staging", f"{table_name}_{partition_key}.parquet")

def make_ingestion_asset(table_name, engine, upstream_asset_key):
    """
    Creates an ingestion asset.
    If 'upstream_asset_key' is provided, this asset waits for it to finish.
    """
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    asset_name = f"{prefix}{table_name}_table"
    group_name = f"{engine}_ingestion"

    # Dependency: The Parquet file must exist first
    deps = [f"{table_name}_parquet"]
    
    # Daisy Chain Dependency (For DuckDB Locking)
    if upstream_asset_key:
        deps.append(upstream_asset_key)

    @asset(
        name=asset_name,
        partitions_def=partitions_def,
        group_name=group_name,
        deps=deps,
        tags={"layer": "storage", "engine": engine},
        required_resource_keys={engine}
    )
    def _ingest_asset(context: AssetExecutionContext):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing Source Data: {file_path}")

        db_resource = getattr(context.resources, engine)
        target_table = f"{table_name}_{partition_key}"

        if engine == "postgres":
            context.log.info(f"Loading {table_name} into Postgres...")
            # Postgres handles concurrency well, so standard Polars write is fine.
            df = pl.read_parquet(file_path)
            df.write_database(
                table_name=target_table, 
                connection=db_resource.connection_string, 
                if_table_exists="replace", 
                engine="sqlalchemy"
            )
            
        elif engine == "duckdb":
            context.log.info(f"Loading {table_name} into DuckDB (Sequential)...")
            # We use a query to keep the connection logic inside the Resource
            query = f"CREATE OR REPLACE TABLE {target_table} AS SELECT * FROM read_parquet('{file_path}');"
            db_resource.execute_query(query, partition_key=partition_key)

    _ingest_asset.__name__ = f"ingest_{engine}_{table_name}"
    return _ingest_asset


# --- MAIN FACTORY LOOP ---
ingestion_assets = []

if ACTIVE_ENGINES:
    for engine in ACTIVE_ENGINES:
        
        # CHAIN TRACKER
        # We only need to chain DuckDB. Postgres can run parallel.
        previous_asset_key = None
        
        for table in TARGET_TABLES:
            
            # Logic: If DuckDB, link to previous. If Postgres, no link.
            upstream_key = previous_asset_key if engine == "duckdb" else None
            
            new_asset = make_ingestion_asset(
                table_name=table, 
                engine=engine, 
                upstream_asset_key=upstream_key
            )
            
            ingestion_assets.append(new_asset)
            
            # Update pointer
            # (We track it regardless, but only use it if engine==duckdb)
            previous_asset_key = new_asset.key.path[-1]