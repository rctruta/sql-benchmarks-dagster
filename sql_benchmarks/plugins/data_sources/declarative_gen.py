import os
import polars as pl
import numpy as np
from dagster import MaterializeResult, MetadataValue
from ...utils.schema import TableDef  # Strict Pydantic Model
from .providers import PROVIDER_REGISTRY

# Batch generation to prevent OOM
CHUNK_SIZE = 500_000

def generate(context, params, table_name, target_path, dataset_config):
    
    # 1. SCHEMA VALIDATION
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

    # Helper to resolve rows for ANY table (current or target)
    def _resolve_rows(t_name, t_def):
        r = params.get('rows')
        if r is None:
            r = t_def.get('rows') 
        
        # Handle variable references
        if isinstance(r, str) and not r.isdigit():
             if r in params:
                 r = params[r]
             else:
                 # Fallback: maybe the target table uses a fixed number?
                 # If we can't resolve it from params, we can't guess.
                 pass
        
        return int(r) if r else None

    # Batch Generation Strategy
    
    # Prepare parent directory
    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    if row_count <= CHUNK_SIZE:
        # Small data: Run normally (in-memory)
        _generate_chunk(0, row_count, table_model, dataset_config, params, row_count, target_path)
    else:
        # Large data: Batch and Append
        temp_dir = os.path.join(parent_dir, f"temp_{table_name}_{row_count}")
        os.makedirs(temp_dir, exist_ok=True)
        
        md_files = []
        remaining = row_count
        offset = 0
        part_idx = 0
        
        print(f"[Gen] Generating {row_count} rows in batches of {CHUNK_SIZE}...")
        
        while remaining > 0:
            current_batch = min(CHUNK_SIZE, remaining)
            part_path = os.path.join(temp_dir, f"part_{part_idx}.parquet")
            
            _generate_chunk(offset, current_batch, table_model, dataset_config, params, row_count, part_path)
            
            md_files.append(part_path)
            remaining -= current_batch
            offset += current_batch
            part_idx += 1
            print(f"[Gen] Batch {part_idx} done.")

        # Stream Merge to Single File (Memory Safe)
        # scan_parquet is lazy. sink_parquet streams execution.
        try:
            pl.scan_parquet(os.path.join(temp_dir, "*.parquet")).sink_parquet(target_path)
            print(f"[Gen] Merged to {target_path}")
        finally:
            # Cleanup temp files
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(target_path),
            "row_count": MetadataValue.int(row_count),
            "table": table_name
        }
    )

def _generate_chunk(offset, size, table_model, dataset_config, params, total_rows, output_path):
    data = {}
    if not table_model.columns:
        # Empty table with rows?
        data["_row_id"] = np.arange(offset, offset + size) # Dummy
    else:
        for col_def in table_model.columns:
            p_name = col_def.provider
            generator_func = PROVIDER_REGISTRY.get(p_name)
            
            if not generator_func:
                 raise ValueError(f"Unknown provider '{p_name}'")

            kwargs = col_def.model_dump()
            
            # Dynamic Params substitution
            for k, v in kwargs.items():
                if isinstance(v, str) and v in params:
                    kwargs[k] = params[v]
            
            kwargs['table_name'] = params.get('table_name', 'unknown') # Contextual name?
            
            # Contextual Handling
            # Foreign Key needs specific logic
            if p_name in ["foreign_key", "foreign key"]:
                 # ... (Same logic as before, passed down) ...
                 # Ideally, generator_func handles 'offset' if needed?
                 # No, providers are stateless usually.
                 pass

            # EXECUTE PROVIDER
            # Note: Most providers don't care about offset (random). 
            # Sequence might? 'sequence' provider usually starts at 1.
            # We need to handle 'sequence' specially or pass offset via kwargs if provider supports it.
            if p_name == "sequence":
                kwargs['start'] = offset + 1 
            
            # Text Concat needs existing data (in this chunk)
            if p_name == "text_concat":
                results = generator_func(size, existing_data=data, **kwargs)
            else:
                results = generator_func(size, **kwargs)
                
            data[col_def.name] = results
            
    df = pl.DataFrame(data)
    df.write_parquet(output_path)