import os
import glob
import time
import jinja2 # Still needed for Template rendering at runtime
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import SQL_DIR
# THE FIX: Use the shared brain
from ..utils.common import load_active_config, get_tables_used_in_sql

# 1. SHARED CONFIG LOADING
# This handles all the validation, defaults, and error raising.
try:
    ACTIVE_ENGINES, TARGET_TABLES, EXPERIMENT_META = load_active_config()
    # Create set for runtime checks
    VALID_TABLES_SET = set(TARGET_TABLES)
except Exception as e:
    # Safety catch so Dagster doesn't crash entirely if config is broken during dev
    print(f"⚠️ Factory Init Error: {e}")
    ACTIVE_ENGINES = []
    VALID_TABLES_SET = set()
    EXPERIMENT_META = {}

def make_benchmark_asset(name, sql_path, engine_name, dependent_asset_name=None):
    
    # 2. USE SHARED LOGIC TO PARSE SQL
    # This returns ONLY the tables found in the SQL that match our YAML list.
    used_tables, raw_template = get_tables_used_in_sql(sql_path, VALID_TABLES_SET)

    # 3. APPLY NAMING CONVENTION
    # Match ingestion_factory: "pg_" for Postgres, "duckdb_" for DuckDB
    prefix = "pg_" if engine_name == "postgres" else f"{engine_name}_"
    
    # Build dependencies using the correct prefix
    deps = [f"{prefix}{t}_table" for t in used_tables]
    
    if dependent_asset_name:
        deps.append(dependent_asset_name)

    @asset(
        name=f"{prefix}benchmark_{name}", 
        partitions_def=partitions_def,
        group_name=f"dynamic_{engine_name}_benchmarks",
        deps=deps, # <--- Correct, filtered dependencies
        tags={
            "source": "sql_factory", 
            "engine": engine_name,
            "experiment": EXPERIMENT_META.get("experiment_id", "default")
        },
        required_resource_keys={engine_name}
    )
    def _benchmark_asset(context: AssetExecutionContext):
        if not hasattr(context.resources, engine_name):
            raise ValueError(f"Resource '{engine_name}' not found")
            
        db_resource = getattr(context.resources, engine_name)
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        # 4. RENDER CONTEXT (Runtime)
        # We inject the specific table names for the partition
        render_context = {}
        for table in used_tables:
            render_context[f"{table}_table"] = f"{table}_{partition_key}"

        template = jinja2.Template(raw_template)
        final_query = template.render(render_context)
        
        start_time = time.time()
        
        if engine_name == "duckdb":
            db_resource.benchmark_query(final_query, partition_key=partition_key)
        else:
            db_resource.benchmark_query(final_query)
            
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "experiment_id": EXPERIMENT_META.get("experiment_id", "unknown"),
                "trace_orphans": MetadataValue.float(params.get('orphan_rate', 0)),
                "config_engine": engine_name,
                "sql_preview": MetadataValue.md(f"```sql\n{final_query}\n```")
            }
        )
    
    _benchmark_asset.__name__ = f"{engine_name}_{name}"
    return _benchmark_asset

# 5. MASTER LOOP
benchmark_assets = []

for engine in ACTIVE_ENGINES:
    engine_sql_dir = os.path.join(SQL_DIR, engine)
    if not os.path.exists(engine_sql_dir): continue
        
    sql_files = glob.glob(os.path.join(engine_sql_dir, "*.sql"))
    previous_benchmark = None
    
    for sql_file in sql_files:
        base_name = os.path.basename(sql_file).replace(".sql", "")
        
        dep_name = previous_benchmark if engine == "duckdb" else None
        
        new_asset = make_benchmark_asset(base_name, sql_file, engine, dependent_asset_name=dep_name)
        benchmark_assets.append(new_asset)
        
        previous_benchmark = f"{engine}_benchmark_{base_name}"