import os
# Removed 'glob' as we no longer guess file paths
from dagster import asset, AssetExecutionContext
from ..constants import DATA_DIR
from ..partitions import partitions_def

def load_dataset_config():
    import yaml
    from ..constants import EXPERIMENTS_DIR
    config_path = os.path.join(EXPERIMENTS_DIR, "active.yaml")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r") as f:
        conf = yaml.safe_load(f) or {}
    return conf.get("dataset", {}).get("tables", {})

tables = load_dataset_config()
ingestion_assets = []

for table_name in tables.keys():
    
    # 1. POSTGRES INGESTION
    @asset(
        name=f"pg_{table_name}_table",
        group_name="ingestion",
        partitions_def=partitions_def,
        deps=[f"{table_name}_parquet"],
        required_resource_keys={"postgres"}
    )
    def _pg_ingest(context: AssetExecutionContext):
        partition_key = context.partition_key
        db = context.resources.postgres
        
        # 1. FIND THE EXACT FILE (New Architecture)
        # Matches: assets/data_factory.py
        filename = f"{table_name}_{partition_key}.parquet"
        parquet_path = os.path.join(DATA_DIR, "staging", filename)
        
        if not os.path.exists(parquet_path):
             raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
        
        # 2. DEFINE TARGET TABLE NAME
        # Matches: benchmark_factory.py (expects {table}_{pk})
        target_table_name = f"{table_name}_{partition_key}"
        
        context.log.info(f"Ingesting {parquet_path} into Postgres table '{target_table_name}'...")
        db.bulk_load(parquet_path, target_table_name)

    _pg_ingest.__name__ = f"pg_ingest_{table_name}"
    ingestion_assets.append(_pg_ingest)

    # 2. DUCKDB INGESTION
    @asset(
        name=f"duckdb_{table_name}_table",
        group_name="ingestion",
        partitions_def=partitions_def,
        deps=[f"{table_name}_parquet"],
        required_resource_keys={"duckdb"}
    )
    def _duck_ingest(context: AssetExecutionContext):
        partition_key = context.partition_key
        db = context.resources.duckdb
        
        # 1. FIND THE EXACT FILE
        filename = f"{table_name}_{partition_key}.parquet"
        parquet_path = os.path.join(DATA_DIR, "staging", filename)
        
        if not os.path.exists(parquet_path):
             raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
        
        # 2. DEFINE TARGET TABLE NAME
        # Matches: benchmark_factory.py (expects {table}_{pk})
        target_table_name = f"{table_name}_{partition_key}"
        
        context.log.info(f"Ingesting {parquet_path} into DuckDB table '{target_table_name}'...")

        # We use the LEGACY execute_query (which writes to benchmark_{pk}.duckdb)
        # This keeps the rest of your pipeline working.
        db.execute_query(
            f"CREATE OR REPLACE TABLE {target_table_name} AS SELECT * FROM read_parquet('{parquet_path}')",
            partition_key=partition_key 
        )

    _duck_ingest.__name__ = f"duck_ingest_{table_name}"
    ingestion_assets.append(_duck_ingest)