import json
import datetime
import os
import glob
import time
import jinja2
import statistics
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import RESULTS_DIR
from ..utils.common import load_context, get_tables_used_in_sql, get_target_sql_dir, infer_metadata_from_sql, get_engine_asset_prefix

CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
EXPERIMENT_META = CTX['meta'] 
VALID_TABLES = set(CTX['tables'])
FULL_CONFIG = CTX['full_config']
REPLICATION_FACTOR = FULL_CONFIG.get("execution", {}).get("replication", 1)

def _smart_cast(val):
    if isinstance(val, (int, float, bool)): return val
    return str(val)

def write_benchmark_fragment(experiment_id, run_id, engine, asset_name, pk, durations, params):
    """
    Writes the atomic result fragment to disk. 
    Isolates the 'Scientific Proof' logic from the Dagster asset.
    """
    # Use global RESULTS_DIR and f-string as requested
    fragment_path = os.path.join(
        RESULTS_DIR, 
        f"{experiment_id}/fragments/{asset_name}__{pk}.json"
    )
    
    os.makedirs(os.path.dirname(fragment_path), exist_ok=True)
    
    payload = {
        "meta": {
            "timestamp": datetime.datetime.now().isoformat(),
            "experiment_id": experiment_id,
            "dagster_run_id": run_id,
            "engine": engine,
            "asset": asset_name,
            "partition": pk
        },
        "metrics": {
            "duration_seconds": statistics.mean(durations),
            "replication_factor": REPLICATION_FACTOR  
        },
        "parameters": params # The "Jagged" Context
    }
    
    with open(fragment_path, "w") as f:
        json.dump(payload, f, default=str, indent=2)
        
    return fragment_path

def make_benchmark_asset(name, engine, used_tables, raw_template, static_meta, extra_context=None):
    prefix = get_engine_asset_prefix(engine)
    deps = [f"{prefix}{t}_table" for t in used_tables]
    asset_name = f"{prefix}benchmark_{name}"
    tags = {}
    
    # Condition: If this is Postgres, enforce the Single-Lane Limit
    if engine == "postgres":
        tags["dagster/concurrency_key"] = "postgres_exclusive"
    tags["experiment_scope"] = "partitioned"    

    @asset(
        name=asset_name,
        partitions_def=partitions_def,
        deps=deps,
        group_name=f"dynamic_bench_{engine}",
        required_resource_keys={engine},
        op_tags=tags
    )
    def _benchmark(context: AssetExecutionContext):
        # 1. Dynamic Resource Retrieval

        db = getattr(context.resources, engine)
        
        pk = context.partition_key
        params = SCENARIO_CONFIG.get(pk, {})
        
        # 2. SQL Render
        render_ctx = {f"{t}_table": f"{t}_{pk}" for t in used_tables}
        render_ctx.update(params)
        if extra_context:
            render_ctx.update(extra_context)
            
        sql = jinja2.Template(raw_template).render(render_ctx)
        
        # 3. Execution Loop
        durations = []
        for _ in range(REPLICATION_FACTOR):
            duration = db.run_query(
                sql=sql, 
                partition_key=pk, 
                scenario_params=params
            )
            
            # Fail hard if the engine does not return a duration (violating the contract)
            if duration is None:
                raise ValueError(f"Engine '{engine}' execution returned None. ensure run_query returns a float duration.")
            
            durations.append(duration)

        # 4. Write Fragment (The Isolated Call)
        experiment_id = EXPERIMENT_META.get("experiment_id", "unknown")
        
        saved_path = write_benchmark_fragment(
            experiment_id=experiment_id,
            run_id=context.run.run_id,
            engine=engine,
            asset_name=asset_name,
            pk=pk,
            durations=durations,
            params=params
        )

        # 4. Return Dagster Metadata
        meta = {
            "duration": MetadataValue.float(statistics.mean(durations)),
            "sql": MetadataValue.md(f"```sql\n{sql}\n```"),
            
            "experiment_id": EXPERIMENT_META.get("experiment_id", "unknown"),
            "config_engine": engine, 
            
            # Static & Dimension Meta
            **{k: _smart_cast(v) for k,v in static_meta.items()},
            **{f"dim_{k}": _smart_cast(v) for k,v in params.items() if k != "pg_settings"}
        }
        return MaterializeResult(metadata=meta)

    return _benchmark

def get_benchmark_assets():
    assets = []
    
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
            if os.path.getsize(f) == 0:
                print(f"[WARN] Skipping empty benchmark file: {f}")
                continue
                
            base = os.path.basename(f).replace(".sql", "")
            tables, raw = get_tables_used_in_sql(f, VALID_TABLES)
            static_meta = infer_metadata_from_sql(raw, dataset_cfg)
            
            # Context Injection: Enable {{ column_name }} in SQL
            col_ctx = {}
            if dataset_cfg and 'tables' in dataset_cfg:
                for t in tables:
                     t_def = dataset_cfg['tables'].get(t, {})
                     for c in t_def.get('columns', []):
                         col_ctx[c['name']] = c['name']
            
            asset_wrapper = make_benchmark_asset(base, engine, tables, raw, static_meta, extra_context=col_ctx)
            
            try:
                asset_obj = asset_wrapper.to_asset_def()
            except AttributeError:
                asset_obj = asset_wrapper
                
            assets.append(asset_obj)
            
    return assets

benchmark_assets = get_benchmark_assets()
