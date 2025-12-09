import os
import glob
import time
import jinja2
import statistics
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG

# UNIFIED IMPORTS
from ..utils.common import load_context, get_tables_used_in_sql, get_target_sql_dir, infer_metadata_from_sql
from ..utils.system import thrash_os_cache

CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
EXPERIMENT_META = CTX['meta']
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
        group_name=f"bench_{engine}",
        required_resource_keys={engine}
    )
    def _benchmark(context: AssetExecutionContext):
        db = getattr(context.resources, engine)
        pk = context.partition_key
        params = SCENARIO_CONFIG.get(pk, {})
        
        # SQL Render
        render_ctx = {f"{t}_table": f"{t}_{pk}" for t in used_tables}
        sql = jinja2.Template(raw_template).render(render_ctx)

        # Run
        durations = []
        for _ in range(REPLICATION_FACTOR):
            t0 = time.time()
            if engine == "duckdb":
                thrash_os_cache(override_gb=params.get("flood_size_gb"))
                db.benchmark_query(sql, partition_key=pk)
            else:
                db.benchmark_query(sql, partition_key=pk, db_config=params.get("pg_settings", {}))
            durations.append(time.time() - t0)

        # Metadata
        meta = {
            "duration": MetadataValue.float(statistics.mean(durations)),
            "sql": MetadataValue.md(f"```sql\n{sql}\n```"),
            **{k: _smart_cast(v) for k,v in static_meta.items()},
            **{f"dim_{k}": _smart_cast(v) for k,v in params.items() if k != "pg_settings"}
        }
        return MaterializeResult(metadata=meta)

    return _benchmark

benchmark_assets = []
if ACTIVE_ENGINES:
    target_dir = get_target_sql_dir(FULL_CONFIG)
    dataset_cfg = CTX['dataset_config']
    for engine in ACTIVE_ENGINES:
        path = os.path.join(target_dir, engine)
        if not os.path.exists(path): continue
        for f in glob.glob(os.path.join(path, "*.sql")):
            base = os.path.basename(f).replace(".sql", "")
            tables, raw = get_tables_used_in_sql(f, VALID_TABLES)
            static_meta = infer_metadata_from_sql(raw, dataset_cfg)
            benchmark_assets.append(make_benchmark_asset(base, engine, tables, raw, static_meta))