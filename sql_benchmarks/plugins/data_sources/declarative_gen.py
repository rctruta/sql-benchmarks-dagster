import os
import polars as pl
import numpy as np
from ...utils.schema import TableDef  # Strict Pydantic Model
from .providers import PROVIDER_REGISTRY

def generate(context, params, table_name, target_path, dataset_config):
    
    # 1. SCHEMA VALIDATION (Strict)
    # implementation_plan.md Reqt: "remove .get defaults"
    if 'tables' not in dataset_config:
        raise ValueError("Missing 'tables' section in dataset config.")
        
    raw_table_def = dataset_config['tables'].get(table_name)
    if not raw_table_def:
        raise ValueError(f"Table '{table_name}' not defined in dataset config.")

    # Validate using Pydantic (Throws ValidationError if invalid)
    # We strip unknown fields if strict mode is issue, but Schema is set to 'allow' extra.
    table_model = TableDef(**raw_table_def)

    # 2. RESOLVE ROW COUNT
    # Priority: Matrix Params > Table Config
    base_rows = params.get('rows')
    if base_rows is None:
        base_rows = table_model.rows
    
    # Handle variable reference (e.g. rows: "small")
    if isinstance(base_rows, str) and not base_rows.isdigit():
        var_name = base_rows
        if var_name in params:
            base_rows = params[var_name]
        else:
            raise ValueError(f"Table '{table_name}' expects param '{var_name}' (from matrix) but it was missing.")
            
    if base_rows is None:
        raise ValueError(f"Could not resolve row count for '{table_name}'.")
        
    row_count = int(base_rows)

    # 3. GENERATE COLUMNS
    data = {}
    
    # If using Pydantic, columns is a list of ColumnDef objects
    if not table_model.columns:
        # Graceful exit for empty tables? Or raise?
        # Let's assume empty table is valid but useless.
        pass
    else:
        for col_def in table_model.columns:
            p_name = col_def.provider
            
            generator_func = PROVIDER_REGISTRY.get(p_name)
            if not generator_func:
                raise ValueError(f"Unknown provider '{p_name}' for column '{col_def.name}'. Available: {list(PROVIDER_REGISTRY.keys())}")
            
            # Pack arguments (dump model to dict)
            # We enforce Pydantic model usage, so we access fields directly or dump.
            kwargs = col_def.model_dump()
            
            # Pass context-aware args
            kwargs['table_name'] = table_name
            
            # Execute
            # Note: 'text_concat' needs existing_data
            if p_name == "text_concat":
                results = generator_func(row_count, existing_data=data, **kwargs)
            else:
                results = generator_func(row_count, **kwargs)
                
            data[col_def.name] = results

    # 4. SAVE
    df = pl.DataFrame(data)
    
    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
        
    df.write_parquet(target_path)
    
    return target_path