import importlib
import os
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import DATA_DIR
from ..utils.common import load_context, get_data_dependencies

# 1. LOAD CONTEXT
CTX = load_context()

OUTPUT_DIR = os.path.join(DATA_DIR, "staging")

def make_data_asset(table_name):
    # Ask Utils for dependencies
    raw_deps = get_data_dependencies(table_name, CTX['table_defs'])
    asset_deps = [f"{d}_parquet" for d in raw_deps]

    @asset(
        name=f"{table_name}_parquet",
        partitions_def=partitions_def,
        group_name="data_generation",
        deps=asset_deps,
        description=f"Generates {table_name}"
    )
    def _generator(context: AssetExecutionContext):
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        # Load Plugin from Config
        plugin_name = CTX['dataset_config']['source']
        module = importlib.import_module(plugin_name)
        
        # Pass Config to Plugin
        return module.generate(context, params, table_name, OUTPUT_DIR, CTX['dataset_config'])

    return _generator

# Loop over the list provided by Common
data_assets = [make_data_asset(t) for t in CTX['tables']]