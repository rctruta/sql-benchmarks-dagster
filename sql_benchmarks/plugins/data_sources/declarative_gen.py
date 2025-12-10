import os
import polars as pl
import numpy as np

# CHANGE 1: We accept 'target_path' instead of 'output_dir'
def generate(context, params, table_name, target_path, dataset_config):

    if 'tables' not in dataset_config:
        raise ValueError("Missing 'tables' definition in dataset config.")

    table_def = dataset_config['tables'].get(table_name)
    if not table_def:
        raise ValueError(f"Schema for table '{table_name}' not found in YAML.")

    base_rows = params.get('rows')

    if base_rows is None:
        base_rows = table_def.get('rows')

    if isinstance(base_rows, str) and not base_rows.isdigit():
        var_name = base_rows
        if var_name in params:
            base_rows = params[var_name]
        else:
            raise ValueError(
                f"Table '{table_name}' refers to variable '{var_name}', "
                f"but it is missing from matrix params: {list(params.keys())}"
            )
    if base_rows is None:
         raise ValueError(f"Row count for '{table_name}' is missing. Must be in Matrix or Table Config.")
    
    base_rows = int(base_rows)
 
    columns = table_def.get("columns", [])
    data = {}

    for col in columns:
        col_name = col['name']
        provider = col['provider']
        
        if provider == "sequence":
            data[col_name] = np.arange(1, base_rows + 1)
            
        elif provider == "choice":
            options = col.get("options", [])
            weights = col.get("weights", None)
            data[col_name] = np.random.choice(options, size=base_rows, p=weights)
            
        elif provider == "random_int":
            mn = col.get("min_value", 0)
            mx = col.get("max_value", 100)
            data[col_name] = np.random.randint(mn, mx, size=base_rows)
            
        elif provider == "random_float":
            mn = col.get("min_value", 0.0)
            mx = col.get("max_value", 1.0)
            data[col_name] = np.random.uniform(mn, mx, size=base_rows)
            
        elif provider == "text_concat":
            source = col.get("source")
            prefix = col.get("prefix", "")
            if source and source in data:
                data[col_name] = [f"{prefix}{x}" for x in data[source]]
            else:
                data[col_name] = [prefix] * base_rows

    # 4. SAVE
    df = pl.DataFrame(data)
    
    # CHANGE 2: Ensure the parent folder exists (Defensive)
    # We take the directory part of the full path (e.g., '.../staging')
    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
        
    # CHANGE 3: Write exactly where told
    # No more os.path.join(output_dir, f"{table_name}.parquet")
    df.write_parquet(target_path)
    
    return target_path