import importlib
import os
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import DATA_DIR
# Import the new helper
from ..utils.common import load_active_config, get_data_dependencies

# 1. LOAD CONTEXT
try:
    CTX = load_active_config()
    PLUGIN_MODULE = CTX['dataset_config']['source']
    TABLE_CONFIGS = CTX['tables']
    TARGET_TABLES = CTX['table_names']
    DATASET_CONFIG = CTX['dataset_config']
except Exception as e:
    print(f"⚠️ Data Factory Init Error: {e}")
    TARGET_TABLES = []
    TABLE_CONFIGS = {}

OUTPUT_DIR = os.path.join(DATA_DIR, "staging")

def make_data_asset(table_name):
    
    # 2. CALCULATE DEPENDENCIES (Delegated to Util)
    # We ask the helper: "What does this table need?"
    t_conf = TABLE_CONFIGS.get(table_name, {})
    raw_deps = get_data_dependencies(t_conf)
    
    # Format as asset names
    asset_deps = [f"{d}_parquet" for d in raw_deps]

    @asset(
        name=f"{table_name}_parquet",
        partitions_def=partitions_def,
        group_name="data_generation",
        deps=asset_deps, # <--- Injected
        description=f"Generates {table_name} using plugin: {PLUGIN_MODULE}"
    )
    def _generator(context: AssetExecutionContext):
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        try:
            module = importlib.import_module(PLUGIN_MODULE)
        except ImportError as e:
            raise ImportError(f"Could not load data plugin '{PLUGIN_MODULE}'") from e
        
        result = module.generate(context, params, table_name, OUTPUT_DIR, DATASET_CONFIG)
        return result

    return _generator

data_assets = [make_data_asset(table) for table in TARGET_TABLES]