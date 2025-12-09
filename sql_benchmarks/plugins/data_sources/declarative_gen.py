import os
import polars as pl
import numpy as np

def generate(context, params, table_name, output_dir, dataset_config):
    # 1. VALIDATION
    if 'tables' not in dataset_config:
        raise ValueError("Missing 'tables' definition in dataset config.")

    table_def = dataset_config['tables'].get(table_name)
    if not table_def:
        raise ValueError(f"Schema for table '{table_name}' not found in YAML.")

    # 2. RESOLVE ROW COUNT (The Fix)
    # ---------------------------------------------------------
    # Attempt A: Look in the Matrix (params) - Priority for scaling tests
    base_rows = params.get('rows')

    # Attempt B: Look in the Static Config (table_def) - Priority for simple tests
    if base_rows is None:
        base_rows = table_def.get('rows')

    # Attempt C: Handle Variable Pointers (e.g. rows: "size_var")
    # If the YAML string is a variable name, look it up in params
    if isinstance(base_rows, str) and not base_rows.isdigit():
        var_name = base_rows
        if var_name in params:
            base_rows = params[var_name]
        else:
            # Explicit error if the variable is missing
            raise ValueError(
                f"Table '{table_name}' refers to variable '{var_name}', "
                f"but it is missing from matrix params: {list(params.keys())}"
            )
    
    # Final Sanity Check
    if base_rows is None:
         raise ValueError(f"Row count for '{table_name}' is missing. Must be in Matrix or Table Config.")
    
    base_rows = int(base_rows)
    # ---------------------------------------------------------

    # 3. GENERATION LOGIC (Unchanged)
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
            # Use numpy for fast weighted sampling
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
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{table_name}.parquet")
    df.write_parquet(output_path)
    
    return output_path