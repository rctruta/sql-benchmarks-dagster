import os
import glob
import time
import jinja2
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..constants import SQL_DIR
from ..utils.common import load_active_config, get_tables_used_in_sql

# 1. LOAD CONFIG
try:
    CTX = load_active_config()
    ACTIVE_ENGINES = CTX['engines']
    EXPERIMENT_META = CTX['meta']
    VALID_TABLES_SET = set(CTX['table_names'])
    
    # Get Replication (Default 1)
    REPLICATION_FACTOR = CTX['full_config'].get("execution", {}).get("replication", 1)

except Exception as e:
    print(f"⚠️ Benchmark Factory Init Error: {e}")
    ACTIVE_ENGINES = []
    VALID_TABLES_SET = set()
    EXPERIMENT_META = {}
    REPLICATION_FACTOR = 1

def make_benchmark_asset(name, sql_path, engine_name, replica_id=0):
    # NO 'dependent_asset_name' ARGUMENT NEEDED
    
    # 2. PARSE SQL
    used_tables, raw_template = get_tables_used_in_sql(sql_path, VALID_TABLES_SET)

    prefix = "pg_" if engine_name == "postgres" else f"{engine_name}_"
    
    # 3. BUILD DEPENDENCIES
    deps = [f"{prefix}{t}_table" for t in used_tables]

    # Unique Name for Replicas
    suffix = f"_rep{replica_id}" if REPLICATION_FACTOR > 1 else ""
    asset_name = f"{prefix}benchmark_{name}{suffix}"

    @asset(
        name=asset_name, 
        partitions_def=partitions_def,
        group_name=f"dynamic_{engine_name}_benchmarks",
        deps=deps,
        tags={
            "source": "sql_factory", 
            "engine": engine_name,
            "experiment": EXPERIMENT_META.get("experiment_id", "default"),
            "replica": str(replica_id)
        },
        required_resource_keys={engine_name}
    )
    def _benchmark_asset(context: AssetExecutionContext):
        if not hasattr(context.resources, engine_name):
            raise ValueError(f"Resource '{engine_name}' not found")
            
        db_resource = getattr(context.resources, engine_name)
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        render_context = {}
        for table in used_tables:
            render_context[f"{table}_table"] = f"{table}_{partition_key}"

        template = jinja2.Template(raw_template)
        final_query = template.render(render_context)
        
        start_time = time.time()
        
        # Execute (Both support partition_key argument)
        db_resource.benchmark_query(final_query, partition_key=partition_key)
            
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "experiment_id": EXPERIMENT_META.get("experiment_id", "unknown"),
                "replica_id": MetadataValue.int(replica_id),
                "trace_orphans": MetadataValue.float(params.get('orphan_rate', 0)),
                "config_engine": engine_name,
                "sql_preview": MetadataValue.md(f"```sql\n{final_query}\n```")
            }
        )
    
    _benchmark_asset.__name__ = f"{engine_name}_{name}_rep{replica_id}"
    return _benchmark_asset

# 4. MASTER LOOP
benchmark_assets = []

for engine in ACTIVE_ENGINES:
    engine_sql_dir = os.path.join(SQL_DIR, engine)
    if not os.path.exists(engine_sql_dir): continue
        
    sql_files = glob.glob(os.path.join(engine_sql_dir, "*.sql"))
    
    for sql_file in sql_files:
        base_name = os.path.basename(sql_file).replace(".sql", "")
        
        # Replication Loop
        for i in range(1, REPLICATION_FACTOR + 1):
            # NO DAISY CHAIN PASSED HERE
            new_asset = make_benchmark_asset(base_name, sql_file, engine, replica_id=i)
            benchmark_assets.append(new_asset)