import os
import glob
import time
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import size_partitions
from ..resources.database import DuckDBResource

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

def make_benchmark_asset(name, sql_path, dependent_asset_name=None):
    with open(sql_path, "r") as f:
        query_sql = f.read()

    current_deps = ["orders_table"]
    if dependent_asset_name:
        current_deps.append(dependent_asset_name)

    @asset(
        name=name,
        partitions_def=size_partitions,
        group_name="dynamic_benchmarks",
        deps=current_deps 
    )
    def _dynamic_asset(context: AssetExecutionContext, database: DuckDBResource):
        start_time = time.time()
        
        # This accurately measures the 20s+ query time
        database.benchmark_query(query_sql) 
        
        duration = time.time() - start_time
        context.log.info(f"Query {name} finished in {duration:.4f}s")

        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "sql_preview": MetadataValue.md(f"```sql\n{query_sql}\n```")
            }
        )
    
    _dynamic_asset.__name__ = f"fn_{name}"
    
    return _dynamic_asset

# --- SEQUENTIAL CHAINING LOGIC ---
benchmark_assets = []
previous_asset_name = None

for sql_file in sql_files:
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"benchmark_{base_name}"
    
    new_asset = make_benchmark_asset(asset_name, sql_file, dependent_asset_name=previous_asset_name)
    benchmark_assets.append(new_asset)
    
    previous_asset_name = asset_name