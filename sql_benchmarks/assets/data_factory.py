import importlib
import os
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import DATA_DIR
# FIX: Import the centralized loader
from ..utils.common import load_active_config

# 1. LOAD FROM CENTRAL UTILS
try:
    CTX = load_active_config()
    PLUGIN_MODULE = CTX['dataset_config']['source']
    TABLE_CONFIGS = CTX['tables']
    TARGET_TABLES = CTX['table_names']
    DATASET_CONFIG = CTX['dataset_config']
except Exception as e:
    # Fail gracefully at import time if config is broken
    print(f"⚠️ Data Factory Init Error: {e}")
    TARGET_TABLES = []

OUTPUT_DIR = os.path.join(DATA_DIR, "staging")

def make_data_asset(table_name):
    # Dynamic Dependencies from YAML
    t_conf = TABLE_CONFIGS.get(table_name, {})
    raw_deps = t_conf.get('deps', [])
    asset_deps = [f"{d}_parquet" for d in raw_deps]

    @asset(
        name=f"{table_name}_parquet",
        partitions_def=partitions_def,
        group_name="data_generation",
        deps=asset_deps,
        description=f"Generates {table_name} using plugin: {PLUGIN_MODULE}"
    )
    def _generator(context: AssetExecutionContext):
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        module = importlib.import_module(PLUGIN_MODULE)
        
        # Pass full context to plugin
        result = module.generate(context, params, table_name, OUTPUT_DIR, DATASET_CONFIG)
        return result

    return _generator

data_assets = [make_data_asset(table) for table in TARGET_TABLES]