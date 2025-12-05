import os
import glob
import time
import jinja2
import statistics
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG

# STRICT IMPORTS
from ..utils.common import load_context, get_tables_used_in_sql, get_target_sql_dir

# 1. LOAD CONTEXT (Fail Fast)
CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
EXPERIMENT_META = CTX['meta']
VALID_TABLES = set(CTX['tables'])
FULL_CONFIG = CTX['full_config']

# Execution Settings
_EXEC = FULL_CONFIG.get("execution", {})
REPLICATION_FACTOR = _EXEC.get("replication", 1) 
TEST_SUITE = _EXEC.get("test_suite")

def thrash_os_cache():
    """
    Allocates 1GB of random data to pressure OS Page Cache.
    This helps simulate a 'Cold' read for DuckDB on the host.
    """
    try:
        # Allocate 1GB array
        _ = bytearray(1024 * 1024 * 1024) 
    except Exception:
        pass

def make_benchmark_asset(name, engine, used_tables, raw_template):
    """
    Creates a SINGLE benchmark asset that runs the query N times sequentially.
    Solves concurrency/locking by strict serial execution inside the function.
    """
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    
    # Dependencies: Only wait for the data tables.
    deps = [f"{prefix}{t}_table" for t in used_tables]
    asset_name = f"{prefix}benchmark_{name}"

    @asset(
        name=asset_name, 
        partitions_def=partitions_def,
        group_name=f"dynamic_{engine}_benchmarks",
        deps=deps,
        tags={
            "engine": engine, 
            "experiment": EXPERIMENT_META.get("experiment_id"),
            "suite": TEST_SUITE or "root"
        },
        required_resource_keys={engine}
    )
    def _benchmark_asset(context: AssetExecutionContext):
        db_resource = getattr(context.resources, engine)
        partition_key = context.partition_key
        
        # 1. Render SQL
        render_ctx = {f"{t}_table": f"{t}_{partition_key}" for t in used_tables}
        final_query = jinja2.Template(raw_template).render(render_ctx)
                
        # Extract row count for tuning
        # params comes from SCENARIO_CONFIG[partition_key]
        params = SCENARIO_CONFIG.get(partition_key, {})
        current_rows = int(params.get('rows', 0))        

        pg_config = params.get("pg_settings", {})

        # 2. Internal Sequential Loop (Lock-Safe)
        durations = []
        context.log.info(f"Starting {REPLICATION_FACTOR} iterations for {asset_name}...")

        # 1. CAPTURE EXECUTION PLAN (The X-Ray)
        # We run EXPLAIN to see what the DB *intends* to do.
        # This is fast and tells us "Index Scan" vs "Seq Scan".
        plan_summary = "Not Available"
        try:
            if engine == "postgres":
                # Postgres JSON format is easy to parse, but TEXT is readable
                explain_sql = f"EXPLAIN {final_query}"
                # We need a raw connection to run this safely without affecting the benchmark txn
                # But for simplicity, we just run it via the resource helper if available
                # Or we skip the helper and use the resource engine directly here:
                with db_resource.get_engine().connect() as conn:
                    result = conn.execute(jinja2.Template(explain_sql).render(render_ctx)).fetchall()
                    # Join lines to make it readable in Dagster UI
                    plan_summary = "\n".join([row[0] for row in result])
                    
            elif engine == "duckdb":
                explain_sql = f"EXPLAIN {final_query}"
                # DuckDB execute_query might not return rows easily via the resource
                # We can do a quick connect here or add explain capability to resource
                # For now, let's skip DuckDB explain or use a raw connection:
                import duckdb
                # Connect read-only to the specific partition file
                db_path = db_resource._get_db_path(partition_key) 
                with duckdb.connect(db_path, read_only=True) as con:
                    result = con.execute(explain_sql).fetchall()
                    plan_summary = "\n".join([str(r) for r in result])

        except Exception as e:
            context.log.warning(f"Could not capture execution plan: {e}")

        for i in range(REPLICATION_FACTOR):
            iteration_start = time.time()
            
            # The resource handles connection/disconnection per query
            if engine == "duckdb":
                thrash_os_cache()
                db_resource.benchmark_query(final_query, partition_key=partition_key)
            else:
                db_resource.benchmark_query(
                    final_query, 
                    partition_key=partition_key, 
                    db_config=pg_config,
                    expected_rows=current_rows  
                )
            
            duration = time.time() - iteration_start
            durations.append(duration)
        
        # 3. Calculate Statistics
        avg_duration = statistics.mean(durations)
        median_duration = statistics.median(durations)
        stdev = statistics.stdev(durations) if len(durations) > 1 else 0.0

        return MaterializeResult(
            metadata={
                # --- CONTEXT ---
                "experiment_id": EXPERIMENT_META.get("experiment_id"),
                "config_engine": engine,
                "suite": TEST_SUITE,
                # Explicit Casting fixes the "params error"
                "trace_orphans": MetadataValue.float(float(params.get('orphan_rate', 0.0))),
                "trace_rows": MetadataValue.int(int(params.get('rows', 0))),
                
                # --- METRICS ---
                "duration_seconds": MetadataValue.float(avg_duration), 
                "duration_median": MetadataValue.float(median_duration),
                "duration_stdev": MetadataValue.float(stdev),
                "iterations": MetadataValue.int(REPLICATION_FACTOR),
                "raw_durations": MetadataValue.json(durations),

                "execution_plan": MetadataValue.md(f"```\n{plan_summary}\n```"),
                "executed_sql": MetadataValue.md(f"```sql\n{final_query}\n```"),
            }
        )
    
    _benchmark_asset.__name__ = f"{engine}_{name}"
    return _benchmark_asset


# --- MAIN FACTORY LOOP ---
benchmark_assets = []

if ACTIVE_ENGINES:
    # 1. Resolve Path
    target_dir = get_target_sql_dir(FULL_CONFIG)
    
    for engine in ACTIVE_ENGINES:
        engine_path = os.path.join(target_dir, engine)
        
        if not os.path.exists(engine_path):
            continue
            
        sql_files = glob.glob(os.path.join(engine_path, "*.sql"))
        
        for sql_file in sql_files:
            base_name = os.path.basename(sql_file).replace(".sql", "")
            
            # Parse Dependencies
            used_tables, raw_template = get_tables_used_in_sql(sql_file, VALID_TABLES)
            
            # Create ONE asset per SQL file (Internal Loop)
            new_asset = make_benchmark_asset(
                name=base_name,
                engine=engine,
                used_tables=used_tables,
                raw_template=raw_template
            )
            
            benchmark_assets.append(new_asset)