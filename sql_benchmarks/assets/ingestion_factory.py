import os
import yaml
from dagster import asset, AssetExecutionContext
from typing import List
from ..constants import DATA_DIR, EXPERIMENTS_DIR, ACTIVE_CONFIG_PATH
from ..partitions import partitions_def
from ..utils.common import load_context, get_engine_asset_prefix, get_scoped_asset_name

CTX = load_context()
ACTIVE_ENGINES = CTX.get('engines', []) 
EXP_ID = CTX['meta'].get("experiment_id", "unknown")

def load_dataset_config():
    """Reads the active experiment YAML to find the tables configured for the dataset."""
    config_path = ACTIVE_CONFIG_PATH
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r") as f:
        conf = yaml.safe_load(f) or {}
    return conf.get("dataset", {}).get("tables", {})

TABLES_CONFIG = load_dataset_config()

ingestion_assets: List[object] = []

def make_ingestion_asset(engine: str, table_name: str):
    """
    Creates a single ingestion asset for a given engine and table, 
    delegating execution to the engine's bulk_load method.
    """
    prefix = get_engine_asset_prefix(engine)
    base_asset_name = f"{prefix}{table_name}_table"
    scoped_name = get_scoped_asset_name(base_asset_name, EXP_ID)

    tags = {}
    tags["experiment_scope"] = "partitioned"  
    
    deps = [
        get_scoped_asset_name(f"{table_name}_parquet", EXP_ID),
        get_scoped_asset_name(f"{table_name}_quality", EXP_ID)
    ]

    @asset(
        name=scoped_name,
        group_name="ingestion",
        partitions_def=partitions_def,
        deps=deps, 
        required_resource_keys={engine},
        op_tags=tags
    )
    def _ingest(context: AssetExecutionContext):
        partition_key = context.partition_key
        
        # 1. Dynamic Resource Retrieval (Polymorphic)
        db = getattr(context.resources, engine)
        
        # 2. FIND THE EXACT FILE
        filename = f"{table_name}_{partition_key}.parquet"
        parquet_path = os.path.join(DATA_DIR, "staging", filename)
        
        if not os.path.exists(parquet_path):
             raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
        
        # 3. DEFINE TARGET TABLE NAME
        target_table_name = f"{table_name}_{partition_key}"
        
        context.log.info(f"Ingesting {parquet_path} into {engine} table '{target_table_name}'...")

        # 4. Use the polymorphic bulk_load method
        db.bulk_load(
            filepath=parquet_path, 
            table_name=target_table_name, 
            partition_key=partition_key
        )
        
        return None 

    return _ingest


# --- Dynamic Asset Creation ---
# Loop 1: Iterate over the configured engines (e.g., duckdb, postgres)
for engine in ACTIVE_ENGINES:
    # Loop 2: Iterate over the correct list of table names from your verified config logic
    for table_name in TABLES_CONFIG.keys():
        asset_obj = make_ingestion_asset(engine, table_name)
        ingestion_assets.append(asset_obj)