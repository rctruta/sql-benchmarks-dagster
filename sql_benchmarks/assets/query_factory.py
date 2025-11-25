import os
import glob
import time
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..resources.database import DuckDBResource
from ..partitions import size_partitions

# 1. FIND THE SQL FILES
# We look for any .sql file in the scripts/sql folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQL_FOLDER = os.path.join(PROJECT_ROOT, "sql_benchmarks", "scripts", "sql")
sql_files = glob.glob(os.path.join(SQL_FOLDER, "*.sql"))

# 2. DEFINE THE FACTORY FUNCTION
def make_benchmark_asset(name, sql_path):
    """
    Creates a Dagster asset definition dynamically for a specific SQL file.
    """
    
    # Read the SQL content once at startup
    with open(sql_path, "r") as f:
        query_sql = f.read()

    @asset(
        name=name,  # Unique name (e.g., 'benchmark_join_anti_pattern')
        partitions_def=size_partitions,
        group_name="dynamic_benchmarks",
        deps=["orders_table"] # Assumes tables are loaded
    )
    def _dynamic_asset(context: AssetExecutionContext, database: DuckDBResource):
        
        # A. Cold Start / Isolation
        database.force_cold_start()
        
        # B. Execute
        start_time = time.time()
        database.execute_query(query_sql)
        duration = time.time() - start_time
        
        context.log.info(f"Query {name} finished in {duration:.4f}s")

        # C. Return Metrics
        return MaterializeResult(
            metadata={
                "duration_seconds": MetadataValue.float(duration),
                "sql_preview": MetadataValue.md(f"```sql\n{query_sql}\n```")
            }
        )

    return _dynamic_asset

# 3. GENERATE THE ASSETS LIST
# We loop through every file found and create an asset for it.
benchmark_assets = []
for sql_file in sql_files:
    # filename: /path/to/join_anti_pattern.sql -> asset_name: benchmark_join_anti_pattern
    base_name = os.path.basename(sql_file).replace(".sql", "")
    asset_name = f"benchmark_{base_name}"
    
    # Create the asset and add to list
    new_asset = make_benchmark_asset(asset_name, sql_file)
    benchmark_assets.append(new_asset)