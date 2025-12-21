import numpy as np

def generate_sequence(rows: int, **kwargs):
    start = kwargs.get("start", 1)
    step = kwargs.get("step", 1)
    return np.arange(start, start + (rows * step), step)

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
    Supports distributions:
    - 'uniform' (Default): Random parent. Avg Depth ~ O(log N).
    - 'chain': Linked List structure (parent = id - 1). Depth = N.
    - 'zipf': Power law. Wide tree. Most nodes point to top few IDs.
    """
    target_rows = kwargs.get("target_rows")
    distribution = kwargs.get("distribution", "uniform")
    
    # Range of valid IDs
    mn = 1
    # If target_rows is set, use it. Else assume self-reference up to current rows.
    mx = (target_rows if target_rows else rows) + 1 
    
    if distribution == "chain":
        # Point to previous ID. ID 1 points to NULL (represnted as 0 or 1? Let's say 1 to be valid FK)
        # Actually standard FK usually allows NULL. But our schema might be strict int64.
        # Let's point root to itself (id=1 -> parent=1) or make it a forest.
        # For simplicity: parent_id = max(1, id - 1)
        # But we generate an array of *values*. We don't know the current ID *per row* easily unless we assume row_idx+1 = ID.
        # Yes, declarative_gen assumes sequence ID 1..N.
        ids = np.arange(1, rows + 1)
        parents = ids - 1
        parents[0] = 1 # Root points to self? Or we need NULL support.
        # If we return ints, we can't have None.
        # Sticking to valid ID range [1, mx).
        parents = np.maximum(1, parents)
        return parents

    elif distribution == "zipf":
        # numpy zipf is z ~ 1/k^a. Returns ints >= 1.
        # We need to map this to valid ID range.
        # A common trick: parent_id = 1 + (zipf sample % mx)
        # But we want frequent *low* IDs (1, 2, 3 as roots).
        # Zipf(a=2) generates many 1s.
        a = kwargs.get("zipf_a", 2.0)
        samples = np.random.zipf(a, size=rows)
        # Map samples to range [1, mx-1] using modulo? 
        # Better: min(samples, mx-1) to preserve frequency of 1.
        parents = np.minimum(samples, mx - 1)
        return parents

    else: # uniform
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
