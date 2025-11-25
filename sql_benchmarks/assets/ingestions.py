import os
from dagster import asset, AssetExecutionContext
from ..resources.database import DuckDBResource
from ..partitions import size_partitions

# 1. DEFINE THE CONFIGURATION
# In a full tool, this could come from a YAML file or a Class.
# For now, a simple list of table names is sufficient.
TARGET_TABLES = ["customers", "orders"]

def get_parquet_path(partition_key, table_name):
    # Dynamic path calculation
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(PROJECT_ROOT, "data", "staging", f"{table_name}_{partition_key}.parquet")

# 2. THE FACTORY FUNCTION
def build_ingestion_asset(table_name):
    """
    Returns a Dagster asset definition that loads a specific parquet file into a DuckDB table.
    """
    
    @asset(
        name=f"{table_name}_table",         # e.g., customers_table
        partitions_def=size_partitions,
        group_name="ingestion",
        # We dynamically define the dependency based on the table name.
        # This assumes the upstream assets are named '{table_name}_parquet'
        deps=[f"{table_name}_parquet"]      
    )
    def _ingest_asset(context: AssetExecutionContext, database: DuckDBResource):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        context.log.info(f"Ingesting {table_name} from {file_path}")
        
        # Check if file exists to give a better error message
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Could not find parquet file: {file_path}")

        # DuckDB Magic
        query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{file_path}');"
        database.execute_query(query)
        
        context.log.info(f"Successfully created table '{table_name}' in DuckDB.")
        
    return _ingest_asset

# 3. GENERATE THE ASSET LIST
# This is what we will import in definitions.py
ingestion_assets = [build_ingestion_asset(table) for table in TARGET_TABLES]