import os
import pandas as pd
from dagster import asset, AssetExecutionContext
from ..resources.postgres import PostgresResource
from ..partitions import size_partitions

TARGET_TABLES = ["customers", "orders"]

def get_parquet_path(partition_key, table_name):
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(PROJECT_ROOT, "data", "staging", f"{table_name}_{partition_key}.parquet")

def build_postgres_ingest(table_name):
    @asset(
        name=f"pg_{table_name}_table", 
        partitions_def=size_partitions,
        group_name="postgres_ingestion",
        deps=[f"{table_name}_parquet"], 
        tags={"layer": "ingestion", "engine": "postgres"},        
        description=f"Loads `{table_name}.parquet` into a native Postgres table for querying."
    )    
    def _ingest_asset(context: AssetExecutionContext, pg: PostgresResource):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        target_table = f"{table_name}_{partition_key}"

        context.log.info(f"Reading {file_path} for upload to Postgres...")
        
        # Read Parquet into RAM
        df = pd.read_parquet(file_path)
        
        # Write to Postgres
        # if_exists='replace' handles the DROP/CREATE logic automatically
        engine = pg.get_engine()
        df.to_sql(target_table, engine, if_exists='replace', index=False)
        
        context.log.info(f"Loaded {len(df)} rows into Postgres table '{target_table}'")

    _ingest_asset.__name__ = f"pg_ingest_{table_name}"
    return _ingest_asset

postgres_ingest_assets = [build_postgres_ingest(table) for table in TARGET_TABLES]