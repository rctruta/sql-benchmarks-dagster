import os
import glob
import time
import jinja2
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG
from ..resources.database import DuckDBResource 

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point to DuckDB SQL folder
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql", "duckdb")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

def make_benchmark_asset(name, sql_path, dependent_asset_name=None):
    with open(sql_path, "r") as f:
        raw_template = f.read()
    
    # 1. DEFINE DEPENDENCIES
    # Start with the tables
    current_deps = ["duckdb_orders_table", "duckdb_customers_table"]
    
    # If there is a previous benchmark, add it to the list.
    # This forces this benchmark to WAIT until the previous one finishes.
    if dependent_asset_name:
        current_deps.append(dependent_asset_name)
        
    # Calculate the relative path for display (e.g. scripts/sql/duckdb/join.sql)
    # This shows the user exactly where to edit the SQL.
    rel_path = os.path.relpath(sql_path, start=PROJECT_ROOT)

    @asset(
        name=name,
        partitions_def=partitions_def,
        group_name="dynamic_duckdb_benchmarks", # This groups them visually
        deps=["duckdb_orders_table", "duckdb_customers_table"],
        tags={"source": "sql_factory", "engine": "duckdb"},
        description=f"""
        **Auto-Generated Benchmark**
        
        * **Source File**: `{rel_path}`
        * **Engine**: DuckDB (Sequential Mode)
        * **Logic**: Runs the raw SQL file inside the timer.
        """
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
        database.benchmark_query(final_query, partition_key=context.partition_key)        
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "config_engine": "duckdb",
                "config_rows": MetadataValue.int(params['rows']),
                "config_orphans": MetadataValue.float(params['orphan_rate']),
                "sql_preview": MetadataValue.md(f"```sql\n{final_query}\n```")
            }
        )
    
    _dynamic_asset.__name__ = f"fn_{name}"
    return _dynamic_asset

# --- SEQUENTIAL CHAINING LOGIC ---
benchmark_assets = []
previous_asset_name = None

for sql_file in sql_files:
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"duckdb_benchmark_{base_name}"
    
    # Pass the previous name to link them together
    new_asset = make_benchmark_asset(asset_name, sql_file, dependent_asset_name=previous_asset_name)
    benchmark_assets.append(new_asset)
    
    # Update the pointer
    previous_asset_name = asset_name    