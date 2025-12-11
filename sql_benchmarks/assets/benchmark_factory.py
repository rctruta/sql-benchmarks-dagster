import os
import glob
import time
import jinja2
import statistics
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG

from ..utils.common import load_context, get_tables_used_in_sql, get_target_sql_dir, infer_metadata_from_sql
from ..utils.system import thrash_os_cache

CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
EXPERIMENT_META = CTX['meta'] # <--- We have this, but weren't using it!
VALID_TABLES = set(CTX['tables'])
FULL_CONFIG = CTX['full_config']
REPLICATION_FACTOR = FULL_CONFIG.get("execution", {}).get("replication", 1)

def _smart_cast(val):
    if isinstance(val, (int, float, bool)): return val
    return str(val)

def make_benchmark_asset(name, engine, used_tables, raw_template, static_meta):
    deps = [f"{'pg_' if engine=='postgres' else engine+'_'}{t}_table" for t in used_tables]
    asset_name = f"{'pg_' if engine=='postgres' else engine+'_'}benchmark_{name}"

    @asset(
        name=asset_name,
        partitions_def=partitions_def,
        deps=deps,
        group_name=f"dynamic_bench_{engine}",
        required_resource_keys={engine}
    )
    def _benchmark(context: AssetExecutionContext):
        if engine == "duckdb":
            db = context.resources.duckdb
        elif engine == "postgres":
            db = context.resources.postgres
        else:
        # Fails hard if an unsupported engine is provided
            raise ValueError(f"Unsupported engine: {engine}")
        
        pk = context.partition_key
        params = SCENARIO_CONFIG.get(pk, {})
        
        # SQL Render

        render_ctx = {f"{t}_table": f"{t}_{pk}" for t in used_tables}
        render_ctx.update(params)         
        sql = jinja2.Template(raw_template).render(render_ctx)
        
        # Run
        durations = []
        for _ in range(REPLICATION_FACTOR):
            t0 = time.time()
            if engine == "duckdb":
                thrash_os_cache(override_gb=params.get("flood_size_gb"))
                db.execute_query(sql, partition_key=pk, read_only=True, is_benchmark=True)
            else:
                db.execute_query(sql, partition_key=pk, 
                                 db_config=params.get("pg_settings", {}),
                                 read_only=True, is_benchmark=True)
            durations.append(time.time() - t0)

        # Metadata
        meta = {
            "duration": MetadataValue.float(statistics.mean(durations)),
            "sql": MetadataValue.md(f"```sql\n{sql}\n```"),
            
            "experiment_id": EXPERIMENT_META.get("experiment_id", "unknown"),
            "config_engine": engine, # Reporting also needs this!
            
            # Static & Dimension Meta
            **{k: _smart_cast(v) for k,v in static_meta.items()},
            **{f"dim_{k}": _smart_cast(v) for k,v in params.items() if k != "pg_settings"}
        }
        return MaterializeResult(metadata=meta)

    return _benchmark

def get_benchmark_assets():
    assets = []
    
    # Access global configuration context (CTX)
    # Check if CTX is loaded before attempting to read configuration
    if not CTX: 
        return [] 

    ACTIVE_ENGINES = CTX.get('engines')
    if not ACTIVE_ENGINES:
        return []
        
    FULL_CONFIG = CTX.get('full_config', {})
    dataset_cfg = CTX.get('dataset_config', {})
    VALID_TABLES = CTX.get('tables', set())
    
    target_dir = get_target_sql_dir(FULL_CONFIG)

    for engine in ACTIVE_ENGINES:
        path = os.path.join(target_dir, engine)
        if not os.path.exists(path): continue
        
        for f in glob.glob(os.path.join(path, "*.sql")):
            base = os.path.basename(f).replace(".sql", "")
            tables, raw = get_tables_used_in_sql(f, VALID_TABLES)
            static_meta = infer_metadata_from_sql(raw, dataset_cfg)
            
            # 1. Get the raw decorated function
            asset_wrapper = make_benchmark_asset(base, engine, tables, raw, static_meta)
            
            # 2. Convert to the stable AssetDefinition object
            # We assume the conversion method is available on the wrapper function.
            # If to_asset_def() fails, we rely on the object being directly recognizable.
            try:
                asset_obj = asset_wrapper.to_asset_def()
            except AttributeError:
                # Fallback: Assume the decorated function is the AssetDefinition object itself
                asset_obj = asset_wrapper
                
            assets.append(asset_obj)
            
    return assets

# --- Final Global Definition ---

#benchmark_assets = get_benchmark_assets()
