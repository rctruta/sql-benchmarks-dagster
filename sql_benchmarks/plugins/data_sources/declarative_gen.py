import os
import polars as pl
import numpy as np
from dagster import MaterializeResult, MetadataValue
from ...utils.schema import TableDef  # Strict Pydantic Model
from ...utils.providers import PROVIDER_REGISTRY
from ...constants import DEFAULT_CHUNK_SIZE


def resolve_params_recursive(obj, params):
    """Recursively replace string values in obj that match keys in params."""
    if isinstance(obj, dict):
        return {k: resolve_params_recursive(v, params) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_params_recursive(i, params) for i in obj]
    elif isinstance(obj, str) and obj in params:
        return params[obj]
    # Handle Pydantic Models by dumping them first (if passed directly)
    elif hasattr(obj, "model_dump"):
        return resolve_params_recursive(obj.model_dump(), params)
    return obj

def _derive_table(table_name, target_path, derive):
    """Carve a NULL-free fragment from its parent's already-generated parquet.

    horizontal: keep rows whose null-pattern over `on` matches `present`
                (present cols non-null, the rest null), then select `select`.
    vertical:   optionally keep rows where `where_not_null` is present, then
                select `select` (the core's mandatory cols, or [pk, attribute]).
    """
    parent = derive["from"]
    fname = os.path.basename(target_path)
    # target filename is "{table_name}_{partition_key}.parquet"; the parent's
    # parquet sits beside it as "{parent}_{partition_key}.parquet".
    suffix = fname[len(table_name) + 1:]
    parent_path = os.path.join(os.path.dirname(target_path), f"{parent}_{suffix}")
    df = pl.read_parquet(parent_path)

    if derive["strategy"] == "horizontal":
        present = set(derive["present"])
        cond = None
        for c in derive["on"]:
            term = pl.col(c).is_not_null() if c in present else pl.col(c).is_null()
            cond = term if cond is None else (cond & term)
        if cond is not None:
            df = df.filter(cond)
    elif derive["strategy"] == "vertical" and derive.get("where_not_null"):
        df = df.filter(pl.col(derive["where_not_null"]).is_not_null())

    df = df.select(derive["select"])
    df.write_parquet(target_path)
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(target_path),
            "row_count": MetadataValue.int(df.height),
            "table": table_name,
            "derived_from": parent,
        }
    )


def generate(context, params, table_name, target_path, dataset_config):
    
    # 1. SCHEMA VALIDATION
    if 'tables' not in dataset_config:
        raise ValueError("Missing 'tables' section in dataset config.")
        
    dataset_config = resolve_params_recursive(dataset_config, params)
    
    tables = dataset_config.get("tables", {})
    raw_table_def = tables.get(table_name)
    if not raw_table_def:
        raise ValueError(f"Table '{table_name}' not defined in dataset config.")

    # Derived (decomposed) tables are carved from their parent's already-generated
    # parquet, not generated fresh. See ConfigLoader._expand_decompositions.
    derive = raw_table_def.get("_derive")
    if derive:
        return _derive_table(table_name, target_path, derive)

    # Validate using Pydantic (Throws ValidationError if invalid)
    # We strip unknown fields if strict mode is issue, but Schema is set to 'allow' extra.
    table_model = TableDef(**tables[table_name])

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

    # ... (rest of logic) ...
    
    chunk_count = (row_count // DEFAULT_CHUNK_SIZE) + (1 if row_count % DEFAULT_CHUNK_SIZE > 0 else 0)

    print(f"[Gen] Generating {row_count} rows in batches of {DEFAULT_CHUNK_SIZE}...")

    # Initialize empty list for temp chunks
    temp_files = []
    
    try:
        for i in range(chunk_count):
            offset = i * DEFAULT_CHUNK_SIZE
            current_size = min(DEFAULT_CHUNK_SIZE, row_count - offset)
            
            chunk_path = f"{target_path}.part_{i}"
            _generate_chunk(offset, current_size, table_model, dataset_config, params, row_count, chunk_path,
                            base_seed=dataset_config.get("seed", 42))
            temp_files.append(chunk_path)
            print(f"[Gen] Batch {i+1} done.")
            
        # Merge efficiently using Polars scan
        # If single chunk, just rename
        if len(temp_files) == 1:
            import shutil
            shutil.move(temp_files[0], target_path)
        else:
            pl.scan_parquet(f"{target_path}.part_*").collect().write_parquet(target_path)
            
    finally:
        # Cleanup
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(target_path),
            "row_count": MetadataValue.int(row_count),
            "table": table_name
        }
    )

def _generate_chunk(offset, size, table_model, dataset_config, params, total_rows, output_path,
                    base_seed=42):
    # Enable reproducible generation. The base seed comes from dataset.seed
    # in the YAML (default 42, preserving all pre-seed-param experiment IDs'
    # data). Because the config is hashed, a different seed automatically
    # yields a different Experiment ID — seed changes are never silent.
    # Offset ensures different chunks get different sequences, but the same
    # chunk always gets the same sequence.
    np.random.seed(base_seed + offset)

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
            # Note: kwargs are already resolved at the top level
            
            # Dynamic Params substitution - Removed as per instruction
            # for k, v in kwargs.items():
            #     if isinstance(v, str) and v in params:
            #         kwargs[k] = params[v]
            
            kwargs['table_name'] = params.get('table_name', 'unknown') 
            
            # Contextual Handling
            # Foreign Key needs target_rows to generate valid IDs
            if p_name in ["foreign_key", "foreign key"]:
                target_table = col_def.target_table
                if target_table:
                    tables = dataset_config.get("tables", {})
                    target_def = tables.get(target_table, {})
                    target_rows = None

                    # Resolve target table's row count
                    target_row_val = target_def.get('rows') or params.get('rows')
                    if isinstance(target_row_val, str) and target_row_val in params:
                        target_rows = int(params[target_row_val])
                    elif target_row_val is not None:
                        target_rows = int(target_row_val)
                    else:
                        target_rows = total_rows  # Fallback to current table's row count

                    kwargs['target_rows'] = target_rows

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

            # Multi-column providers return a dict of {col_name: array}.
            # Expand them directly into data instead of nesting under one key.
            if isinstance(results, dict):
                data.update(results)
            else:
                data[col_def.name] = results
            
    df = pl.DataFrame(data)

    # Apply Null Masks natively
    for col_def in table_model.columns:
        # null_probability will be a float here because it was resolved globally
        if col_def.null_probability > 0:
            mask = np.random.rand(size) < col_def.null_probability
            
            # Use Polars expression to nullify values
            # This preserves the underlying Arrow type (Int64, Utf8) instead of casting to Object
            df = df.with_columns(
                pl.when(pl.lit(mask)).then(None).otherwise(pl.col(col_def.name)).alias(col_def.name)
            )

    df.write_parquet(output_path)