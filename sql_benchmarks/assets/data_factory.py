import importlib
import os
import yaml
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def, SCENARIO_CONFIG

# FIX: Use relative import for consistency
from ..constants import ACTIVE_CONFIG_PATH, DATA_DIR 

# 1. READ CONFIG (Strict Mode)
if not os.path.exists(ACTIVE_CONFIG_PATH):
    # Fallback to defaults to prevent import-time crashes if file is missing
    # (This allows you to load Dagster even if active.yaml is broken)
    PLUGIN_MODULE = 'sql_benchmarks.plugins.data_sources.synthetic_ecommerce'
    TARGET_TABLES = ['customers', 'orders']
else:
    with open(ACTIVE_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)

    # Validate Contract
    if 'dataset' not in config or 'source' not in config['dataset']:
        raise ValueError("active.yaml is missing 'dataset.source'.")

    PLUGIN_MODULE = config['dataset']['source']
    TARGET_TABLES = config['dataset'].get('tables', ['customers', 'orders'])

# Define staging area using the constant we verified
OUTPUT_DIR = os.path.join(DATA_DIR, "staging")

def make_data_asset(table_name):
    # Dependency Logic (Hardcoded for V4 MVP)
    # In V5, the plugin class would define this relationship dynamically.
    deps = []
    if table_name == "orders":
        # Note: We must refer to the generated name, e.g., 'customers_parquet'
        deps = ["customers_parquet"]

    @asset(
        name=f"{table_name}_parquet",
        partitions_def=partitions_def,
        group_name="data_generation",
        deps=deps,
        description=f"Generates {table_name} using plugin: {PLUGIN_MODULE}"
    )
    def _generator(context: AssetExecutionContext):
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        try:
            module = importlib.import_module(PLUGIN_MODULE)
        except ImportError as e:
            raise ImportError(f"Could not load data plugin '{PLUGIN_MODULE}'") from e
        
        # Pass the verified OUTPUT_DIR constant
        result = module.generate(context, params, table_name, OUTPUT_DIR)
        return result

    return _generator

data_assets = [make_data_asset(table) for table in TARGET_TABLES]