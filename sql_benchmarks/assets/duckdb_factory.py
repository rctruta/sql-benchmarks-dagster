import os
import glob
import time
import jinja2
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG, EXPERIMENT_META
from ..resources.database import DuckDBResource 

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql", "duckdb")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

def make_benchmark_asset(name, sql_path, dependent_asset_name=None):
    with open(sql_path, "r") as f:
        raw_template = f.read()

    # 1. BASE DEPENDENCIES (The Tables)
    current_deps = ["duckdb_orders_table", "duckdb_customers_table"]
    
    # 2. SEQUENCE DEPENDENCY (The Lock Fix)
    # If a previous benchmark exists, we add it to deps.
    # This forces Dagster to wait, preventing parallel file access.
    if dependent_asset_name:
        current_deps.append(dependent_asset_name)

    @asset(
        name=name,
        partitions_def=partitions_def,
        group_name="dynamic_duckdb_benchmarks",
        deps=current_deps, # <--- Applied here
        tags={
            "source": "sql_factory", 
            "engine": "duckdb",
            "experiment": EXPERIMENT_META.get("experiment_id", "default")
        }
    )
    def _dynamic_asset(context: AssetExecutionContext, database: DuckDBResource):
        partition_key = context.partition_key
        params = SCENARIO_CONFIG[partition_key]
        
        render_context = {
            "orders_table": f"orders_{partition_key}",
            "customers_table": f"customers_{partition_key}"
        }
        
        template = jinja2.Template(raw_template)
        final_query = template.render(render_context)
        
        start_time = time.time()
        
        # Pass key to hit the specific partition file
        database.benchmark_query(final_query, partition_key=partition_key) 
        
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "experiment_id": EXPERIMENT_META.get("experiment_id", "unknown"),
                "config_engine": "duckdb",
                "sql_preview": MetadataValue.md(f"```sql\n{final_query}\n```"),
                "duration_seconds": MetadataValue.float(duration),
                "config_rows": MetadataValue.int(params['rows']),
                "config_orphans": MetadataValue.float(params['orphan_rate']),
            }
        )
    
    _dynamic_asset.__name__ = f"duckdb_fn_{name}"
    return _dynamic_asset

# --- SEQUENTIAL CHAINING LOOP ---
benchmark_assets = []
previous_asset_name = None

for sql_file in sql_files:
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"duckdb_benchmark_{base_name}"
    
    # We pass 'previous_asset_name' to link them
    new_asset = make_benchmark_asset(asset_name, sql_file, dependent_asset_name=previous_asset_name)
    benchmark_assets.append(new_asset)
    
    # Update the pointer for the next iteration
    previous_asset_name = asset_name