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
from ..utils.common import load_context, get_tables_used_in_sql, get_target_sql_dir, infer_metadata_from_sql, get_engine_asset_prefix, get_engine_sql_dialect, get_engine_benchmark_group, get_scoped_asset_name

CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
EXPERIMENT_META = CTX['meta']
EXP_ID = EXPERIMENT_META.get("experiment_id", "unknown")
VALID_TABLES = set(CTX['tables'])
FULL_CONFIG = CTX['full_config']
REPLICATION_FACTOR = FULL_CONFIG.get("execution", {}).get("replication", 1)

# Every dataset column name, bound to itself, so SQL templates can reference
# columns as {{ col }} uniformly — not just {{ tbl_table }}. A column that is
# *parameterized* (a matrix dimension) still wins, because `dims` updates the
# render context last. This is what makes {{ join_key_a }} resolve.
ALL_COLUMNS = {
    col["name"]
    for tdef in CTX['table_defs'].values() if isinstance(tdef, dict)
    for col in tdef.get("columns", []) if isinstance(col, dict) and "name" in col
}

def _smart_cast(val):
    if isinstance(val, (int, float, bool)): return val
    return str(val)

def write_benchmark_fragment(experiment_id, run_id, engine, asset_name, pk, durations, params):
    """
    Writes the atomic result fragment to disk. 
    Isolates the 'Scientific Proof' logic from the Dagster asset.
    """
    # Results are isolated by experiment_id in RESULTS_DIR
    fragment_path = os.path.join(
        RESULTS_DIR, 
        experiment_id,
        "fragments",
        f"{asset_name}__{pk}.json"
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
            # Raw per-replication measurements: the spread under identical
            # conditions is itself evidence (thermal drift, scheduler noise,
            # cold-cache approximation). Mean alone hides it.
            "durations_raw": durations,
            "replication_factor": REPLICATION_FACTOR
        },
        "parameters": params # The "Jagged" Context
    }
    
    with open(fragment_path, "w") as f:
        json.dump(payload, f, default=str, indent=2)
        
    return fragment_path

def make_benchmark_asset(name, engine, used_tables, raw_template, static_meta, extra_context=None):
    prefix = get_engine_asset_prefix(engine)
    deps = [get_scoped_asset_name(f"{prefix}{t}_table", EXP_ID) for t in used_tables]
    asset_base_name = f"{prefix}benchmark_{name}"
    asset_scoped_name = get_scoped_asset_name(asset_base_name, EXP_ID)
    tags = {}

    # Single-Lane Limit for engines with exclusive infrastructure:
    # postgres restarts a shared Docker container; quack variants bind fixed ports.
    if engine in ("postgres", "quack", "quack_pushdown"):
        tags["dagster/concurrency_key"] = f"{engine}_exclusive"
    tags["experiment_scope"] = "partitioned"

    @asset(
        name=asset_scoped_name,
        partitions_def=partitions_def,
        deps=deps,
        group_name=get_engine_benchmark_group(engine),
        required_resource_keys={engine},
        op_tags=tags
    )
    def _benchmark(context: AssetExecutionContext):
        db = getattr(context.resources, engine)
        pk = context.partition_key
        params = SCENARIO_CONFIG.get(pk, {})
        # Each engine receives ONLY its own namespace of engine_params
        # (assembled by config_loader from execution.engine_params + namespaced
        # matrix dimensions like 'postgres.work_mem').
        engine_params = params.get("engine_params", {}).get(engine, {})
        dims = {k: v for k, v in params.items() if k != "engine_params"}

        # SQL render — precedence: matrix dims > table names > column names.
        # columns bind to themselves; {{ tbl_table }} → physical partition table;
        # a parameterized column/table (a matrix dim) overrides. engine_params
        # stays out of the SQL (applied as session settings, not text).
        render_ctx = {c: c for c in ALL_COLUMNS}
        render_ctx.update({f"{t}_table": f"{t}_{pk}" for t in used_tables})
        render_ctx.update(dims)
        sql = jinja2.Template(raw_template).render(render_ctx)

        # 3. Execution (Replicated)
        # None return means the engine signalled a non-fatal failure (e.g. TypeDB
        # stack overflow on recursive queries).  We stop after the first None and
        # record the run as DNF rather than crashing the entire Dagster step.
        durations = []
        dnf = False
        for _ in range(REPLICATION_FACTOR):
            duration = db.run_query(sql=sql, partition_key=pk, engine_params=engine_params)
            if duration is None:
                dnf = True
                break
            durations.append(duration)

        if dnf:
            context.log.warning(
                f"Engine '{engine}' returned None for partition '{pk}' — "
                f"recording as DNF (did-not-finish). "
                f"Likely cause: server crash / stack overflow / OOM during query evaluation."
            )
            # Write a sentinel fragment directly (bypass write_benchmark_fragment
            # which requires at least one duration measurement)
            experiment_id = EXPERIMENT_META.get("experiment_id", "unknown")
            fragment_path = os.path.join(
                RESULTS_DIR, experiment_id, "fragments",
                f"{asset_scoped_name}__{pk}.json"
            )
            os.makedirs(os.path.dirname(fragment_path), exist_ok=True)
            import json as _json, datetime as _dt
            _json.dump({
                "meta": {
                    "timestamp": _dt.datetime.now().isoformat(),
                    "experiment_id": experiment_id,
                    "dagster_run_id": context.run.run_id,
                    "engine": engine,
                    "asset": asset_scoped_name,
                    "partition": pk,
                },
                "metrics": {"duration_seconds": None, "durations_raw": [], "replication_factor": 0, "dnf": True},
                # dnf lives in metrics; duplicating it into parameters leaked a
                # redundant lowercase 'dnf' column into the flattened CSV.
                "parameters": params,
            }, open(fragment_path, "w"), default=str, indent=2)
            return MaterializeResult(metadata={
                "dnf": MetadataValue.bool(True),
                "engine": MetadataValue.text(engine),
                "partition": MetadataValue.text(pk),
            })

        # 4. Write Fragment (The Isolated Call)
        experiment_id = EXPERIMENT_META.get("experiment_id", "unknown")

        write_benchmark_fragment(
            experiment_id=experiment_id,
            run_id=context.run.run_id,
            engine=engine,
            asset_name=asset_scoped_name,
            pk=pk,
            durations=durations,
            params=dims,
        )

        meta = {
            "duration": MetadataValue.float(statistics.mean(durations)),
            "sql": MetadataValue.md(f"```sql\n{sql}\n```"),
            "experiment_id": experiment_id,
            "config_engine": engine,
            **{k: _smart_cast(v) for k, v in static_meta.items()},
            **{f"dim_{k}": _smart_cast(v) for k, v in dims.items()},
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
        path = os.path.join(target_dir, get_engine_sql_dialect(engine))
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
