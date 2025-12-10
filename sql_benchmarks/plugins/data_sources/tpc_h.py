import duckdb
import os
from dagster import MaterializeResult, MetadataValue

# CHANGED: 'output_dir' -> 'target_path'
def generate(context, params, table_name, target_path, dataset_config):
    partition_key = context.partition_key
    
    if 'tables' not in dataset_config:
        raise ValueError("Critical: 'dataset.tables' missing in active.yaml")
        
    if not dataset_config['tables'].get(table_name):
        raise ValueError(f"Table '{table_name}' requested but not defined in YAML.")

    scale_factor = params.get('scale_factor', 0.01)
    
    context.log.info(f"Generating TPC-H table '{table_name}' with SF={scale_factor}...")

    # 1. Setup DuckDB
    con = duckdb.connect(database=':memory:')
    con.install_extension("tpch")
    con.load_extension("tpch")
    
    # 2. Generate Data
    con.execute(f"CALL dbgen(sf={scale_factor})")
    
    # 3. Export with Type Casting
    # Ensure directory exists (Defensive)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Get columns for the table
    cols_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    
    # Build a SELECT statement that casts Decimals to Doubles
    select_parts = []
    for col_name, col_type, _, _, _, _ in cols_info:
        if "DECIMAL" in col_type:
            select_parts.append(f"CAST({col_name} AS DOUBLE) AS {col_name}")
        else:
            select_parts.append(col_name)
            
    select_query = ", ".join(select_parts)
    
    # USE THE PASSED TARGET_PATH
    con.execute(f"""
        COPY (SELECT {select_query} FROM {table_name}) 
        TO '{target_path}' 
        (FORMAT PARQUET, COMPRESSION 'SNAPPY')
    """)
    
    # 4. Metadata
    row_count = con.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
    
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(target_path),
            "row_count": MetadataValue.int(row_count),
            "scale_factor": MetadataValue.float(scale_factor),
            "source": "duckdb_tpch_extension"
        }
    )