import importlib
import os
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import DATA_DIR
from ..utils.common import load_context, get_data_dependencies, get_scoped_asset_name

from ..plugins.data_sources import declarative_gen

# 1. LOAD CONTEXT
CTX = load_context()
EXP_ID = CTX['meta'].get("experiment_id", "unknown")

OUTPUT_DIR = os.path.join(DATA_DIR, "staging")

def make_data_asset(table_name):

    raw_deps = get_data_dependencies(table_name, CTX['table_defs'])
    asset_deps = [get_scoped_asset_name(f"{d}_parquet", EXP_ID) for d in raw_deps]
    scoped_name = get_scoped_asset_name(f"{table_name}_parquet", EXP_ID)

    @asset(
        name=scoped_name,
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
        
        # 1. Construct the path
        file_name = f"{table_name}_{partition_key}.parquet"
        target_path = os.path.join(OUTPUT_DIR, file_name)
        
        # 2. Ensure folder exists
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # 3. Call Plugin
        return module.generate(
            context=context, 
            params=params, 
            table_name=table_name, 
            target_path=target_path, 
            dataset_config=CTX['dataset_config']
        )
    return _generator

data_assets = [make_data_asset(t) for t in CTX['tables']]