import os
import glob
import time
import jinja2
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import size_partitions
from ..resources.postgres import PostgresResource

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Point to the POSTGRES folder
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql", "postgres")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

def make_postgres_benchmark(name, sql_path):
    with open(sql_path, "r") as f:
        raw_template = f.read()

    @asset(
        name=name,
        partitions_def=size_partitions,
        group_name="postgres_benchmarks",
        # Depend on the PG tables, not the DuckDB tables
        deps=["pg_orders_table", "pg_customers_table"] 
    )
    def _pg_asset(context: AssetExecutionContext, pg: PostgresResource):
        partition_key = context.partition_key
        
        render_context = {
            "orders_table": f"orders_{partition_key}",
            "customers_table": f"customers_{partition_key}"
        }
        
        template = jinja2.Template(raw_template)
        final_query = template.render(render_context)
        
        start_time = time.time()
        pg.benchmark_query(final_query)
        duration = time.time() - start_time
        
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "engine": "postgres",
                "sql_preview": MetadataValue.md(f"```sql\n{final_query}\n```")
            }
        )
    
    _pg_asset.__name__ = f"pg_fn_{name}"
    return _pg_asset

postgres_bench_assets = []
for sql_file in sql_files:
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"pg_benchmark_{base_name}"
    postgres_bench_assets.append(make_postgres_benchmark(asset_name, sql_file))