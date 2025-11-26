import os
import glob
import time
import jinja2
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import size_partitions
from ..resources.database import DuckDBResource 

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql", "duckdb")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

def make_benchmark_asset(name, sql_path):
    # Read template once
    with open(sql_path, "r") as f:
        raw_template = f.read()

    @asset(
        name=name,
        partitions_def=size_partitions,
        group_name="dynamic_benchmarks",
        deps=["orders_table", "customers_table"] 
    )
    def _dynamic_asset(context: AssetExecutionContext, database: DuckDBResource):
        partition_key = context.partition_key
        
        # 1. Define Context Variables
        # Map generic names to partition-specific names
        render_context = {
            "orders_table": f"orders_{partition_key}",
            "customers_table": f"customers_{partition_key}"
        }
        
        # 2. Render Template
        template = jinja2.Template(raw_template)
        final_query = template.render(render_context)
        
        start_time = time.time()
        
        # 3. Run the Rendered SQL
        database.benchmark_query(final_query) 
        
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "rendered_sql": MetadataValue.md(f"```sql\n{final_query}\n```")
            }
        )
    
    _dynamic_asset.__name__ = f"fn_{name}"
    return _dynamic_asset

benchmark_assets = []
for sql_file in sql_files:
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"benchmark_{base_name}"
    benchmark_assets.append(make_benchmark_asset(asset_name, sql_file))