import polars as pl
import numpy as np
import os
import simpleeval
from dagster import MaterializeResult, MetadataValue

def generate(context, params, table_name, output_dir, dataset_config):
    """
    Generates synthetic data based on the YAML schema definition.
    Uses Polars for high-performance generation.
    """
    partition_key = context.partition_key
    
    if 'tables' not in dataset_config:
         raise ValueError("Missing 'tables' definition in dataset config.")
         
    table_def = dataset_config['tables'].get(table_name)
    if not table_def:
        raise ValueError(f"Schema for table '{table_name}' not found in YAML.")

    # 1. CALCULATE ROW COUNT
    base_rows = params['rows']
    
    eval_ctx = {
        'rows': base_rows,
        'ratio': params.get('ratio', 10)
    }
    
    row_expr = str(table_def.get('rows', 'rows'))
    
    try:
        num_rows = int(simpleeval.simple_eval(row_expr, names=eval_ctx))
        num_rows = max(num_rows, 1)
    except Exception as e:
        context.log.warning(f"Math error for {table_name}: {e}. Defaulting to {base_rows}.")
        num_rows = base_rows

    context.log.info(f"Generating {num_rows} rows for {table_name} (Polars)...")

    # 2. GENERATE COLUMNS
    data = {}
    columns = table_def.get('columns', [])
    np.random.seed(42)

    for col in columns:
        col_name = col['name']
        provider = col['provider']
        
        if provider == "sequence":
            data[col_name] = pl.int_range(1, num_rows + 1, eager=True)
            
        elif provider == "choice":
            options = col['options']
            data[col_name] = np.random.choice(options, size=num_rows)
            
        elif provider == "uniform":
            min_v, max_v = col.get('min', 0), col.get('max', 100)
            data[col_name] = np.random.uniform(min_v, max_v, size=num_rows)
            
        elif provider == "foreign_key":
            target_table = col['target_table']
            
            target_def = dataset_config['tables'].get(target_table)
            if not target_def:
                raise ValueError(f"Foreign key target '{target_table}' not defined.")
                
            target_expr = str(target_def.get('rows', 'rows'))
            target_rows = int(simpleeval.simple_eval(target_expr, names=eval_ctx))
            
            apply_orphan = col.get('apply_orphan_rate', False)
            orphan_pct = params.get('orphan_rate', 0.0) if apply_orphan else 0.0
            
            num_orphans = int(num_rows * orphan_pct)
            num_valid = num_rows - num_orphans
            
            max_valid_id = max(target_rows, 1)
            valid_ids = np.random.randint(1, max_valid_id + 1, size=num_valid)
            orphan_ids = np.random.randint(max_valid_id + 1, max_valid_id + 10000, size=num_orphans)
            
            combined = np.concatenate([valid_ids, orphan_ids])
            np.random.shuffle(combined)
            data[col_name] = combined

    # 3. SAVE
    df = pl.DataFrame(data)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{table_name}_{partition_key}.parquet")
    df.write_parquet(output_path)
    
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(len(df)),
            "schema_source": "yaml_definition",
            "generation_backend": "polars" 
        }
    )