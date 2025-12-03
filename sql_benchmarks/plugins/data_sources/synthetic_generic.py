import polars as pl
import numpy as np
import os
import simpleeval
from dagster import MaterializeResult, MetadataValue

def generate(context, params, table_name, output_dir, dataset_config):
    partition_key = context.partition_key
    
    if 'tables' not in dataset_config:
         raise ValueError("Missing 'tables' definition in dataset config.")
         
    table_def = dataset_config['tables'].get(table_name)
    if not table_def:
        raise ValueError(f"Schema for table '{table_name}' not found in YAML.")

    # 1. CALCULATE ROW COUNT
    base_rows = params['rows']
    eval_ctx = {'rows': base_rows, 'ratio': params.get('ratio', 10)}
    row_expr = str(table_def.get('rows', 'rows'))
    
    try:
        num_rows = int(simpleeval.simple_eval(row_expr, names=eval_ctx))
        num_rows = max(num_rows, 1)
    except Exception as e:
        context.log.warning(f"Math error for {table_name}: {e}. Defaulting to {base_rows}.")
        num_rows = base_rows

    context.log.info(f"Generating {num_rows} rows for {table_name}...")

    # 2. GENERATE INDEPENDENT COLUMNS (Eager Data)
    data = {}
    columns = table_def.get('columns', [])
    np.random.seed(42)

    for col in columns:
        col_name = col['name']
        provider = col['provider']
        
        if provider == "sequence":
            data[col_name] = pl.int_range(1, num_rows + 1, eager=True)
            
        elif provider == "choice":
            if 'options' not in col:
                raise ValueError(f"Column '{col_name}' (choice) missing required 'options' list.")
            data[col_name] = np.random.choice(col['options'], size=num_rows)
            
        elif provider == "uniform":
            min_v = col.get('min')
            max_v = col.get('max')
            if min_v is None or max_v is None:
                raise ValueError(f"Column '{col_name}' (uniform) missing required 'min' or 'max'.")
            data[col_name] = np.random.uniform(min_v, max_v, size=num_rows)
            
        elif provider == "foreign_key":
            target_table = col['target_table']
            target_def = dataset_config['tables'].get(target_table)
            
            target_expr = str(target_def.get('rows', 'rows'))
            target_rows = int(simpleeval.simple_eval(target_expr, names=eval_ctx))
            
            apply_orphan = col.get('apply_orphan_rate', False)
            orphan_pct = params.get('orphan_rate', 0.0) if apply_orphan else 0.0
            
            num_orphans = int(num_rows * orphan_pct)
            num_valid = num_rows - num_orphans
            
            max_valid_id = max(target_rows, 1)
            
            valid_ids = np.random.randint(1, max_valid_id + 1, size=num_valid)
            
            orphan_range_end = max_valid_id + max(num_rows, 1) 
            orphan_ids = np.random.randint(max_valid_id + 1, orphan_range_end + 1, size=num_orphans)
            
            combined = np.concatenate([valid_ids, orphan_ids])
            np.random.shuffle(combined)
            data[col_name] = combined

    # 3. CREATE DATAFRAME (Materialize Pass 1)
    # We do this NOW so we can use Expressions in Pass 2
    df = pl.DataFrame(data)

    # 4. GENERATE DEPENDENT COLUMNS (Expressions)
    concat_exprs = []
    for col in columns:
        if col['provider'] == "text_concat":
            col_name = col['name']
            prefix = col.get('prefix', '')
            source_col = col.get('source')
            
            if source_col not in df.columns:
                raise ValueError(f"Column '{col_name}' depends on missing source '{source_col}'")

            # Expression: "Prefix " + col(source)
            # This is fast and vectorized
            expr = (pl.lit(prefix) + pl.lit(" ") + pl.col(source_col).cast(pl.Utf8)).alias(col_name)
            concat_exprs.append(expr)

    # Apply all concatenations at once
    if concat_exprs:
        df = df.with_columns(concat_exprs)

    # 5. SAVE
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