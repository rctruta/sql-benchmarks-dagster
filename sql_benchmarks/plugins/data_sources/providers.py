import numpy as np

def generate_sequence(rows: int, **kwargs):
    return np.arange(1, rows + 1)

def generate_random_int(rows: int, **kwargs):
    mn = kwargs.get("min_value", 0)
    mx = kwargs.get("max_value", 100)
    return np.random.randint(mn, mx, size=rows)

def generate_random_float(rows: int, **kwargs):
    mn = kwargs.get("min_value", 0.0)
    mx = kwargs.get("max_value", 1.0)
    return np.random.uniform(mn, mx, size=rows)

def generate_choice(rows: int, **kwargs):
    options = kwargs.get("options", [])
    weights = kwargs.get("weights", None)
    if not options:
        raise ValueError("Provider 'choice' requires 'options' list.")
    return np.random.choice(options, size=rows, p=weights)

def generate_text_concat(rows: int, existing_data: dict, **kwargs):
    source_col = kwargs.get("source")
    prefix = kwargs.get("prefix", "")
    
    if not source_col:
        raise ValueError("Provider 'text_concat' requires 'source' column name.")
        
    if source_col not in existing_data:
        # Fallback if source hasn't been generated yet (should rely on column ordering)
        # For now, just return prefixes to avoid crash, but warn?
        # Ideally, we sort generation/topological sort columns.
        # Assuming table definitions are ordered correctly by user.
        return [prefix] * rows
        
    return [f"{prefix}{x}" for x in existing_data[source_col]]

def generate_foreign_key(rows: int, table_name: str, **kwargs):
    """
    Generates foreign keys.
    For hierarchy tables, enforces tree-like structure (parent_id < id) if possible, 
    or random links (allowing cycles) based on user intent.
    Current Default: Random(1, rows) which simulates 'contained in' relationship.
    """
    # For self-referencing hierarchy (recursion test), we simulate a tree/graph.
    # To strictly prevent cycles (DAG), we'd need parent < id.
    # To allow full graphs (recursive queries), we allow any ID.
    # 
    # Logic: Simply point to any existing row in the referenced table.
    # We assume referenced table has IDs 1..rows.
    # If target table size differs, this logic needs 'target_rows' param.
    # For now, we assume self-reference or 1:1 sizing for simplicty in benchmarks.
    
    # Validation constraint for Recursivity Test:
    # "foreign_key" usually points to an EXISTING ID.
    # If we are pointing to *ourselves* (parent_id), the IDs 1..N exist.
    mn = 1
    mx = rows + 1 # Exclusive
    
    return np.random.randint(mn, mx, size=rows)

PROVIDER_REGISTRY = {
    "sequence": generate_sequence,
    "random_int": generate_random_int,
    "random_float": generate_random_float,
    "choice": generate_choice,
    "text_concat": generate_text_concat,
    "foreign_key": generate_foreign_key,
    "foreign key": generate_foreign_key # Alias
}
