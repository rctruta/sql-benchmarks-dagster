import os
from dagster import asset, AssetExecutionContext
from ..resources.database import DuckDBResource
from ..partitions import size_partitions

TARGET_TABLES = ["customers", "orders"]

def get_parquet_path(partition_key, table_name):
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(PROJECT_ROOT, "data", "staging", f"{table_name}_{partition_key}.parquet")

def build_ingestion_asset(table_name):
    @asset(
        name=f"{table_name}_table",
        partitions_def=size_partitions,
        group_name="ingestion",
        deps=[f"{table_name}_parquet"]
    )
    def _ingest_asset(context: AssetExecutionContext, database: DuckDBResource):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        # DYNAMIC NAMING: orders_small, orders_medium
        target_table_name = f"{table_name}_{partition_key}"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing: {file_path}")

        # Create specific table for this partition
        query = f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet('{file_path}');"
        database.execute_query(query)
        
        context.log.info(f"Created table '{target_table_name}'")

    _ingest_asset.__name__ = f"ingest_{table_name}"
    return _ingest_asset

ingestion_assets = [build_ingestion_asset(table) for table in TARGET_TABLES]