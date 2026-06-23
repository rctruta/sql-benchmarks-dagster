import numpy as np

def generate_sequence(rows: int, **kwargs):
    start = kwargs.get("start", 1)
    step = kwargs.get("step", 1)
    return np.arange(start, start + (rows * step), step)

def generate_random_int(rows: int, **kwargs):
    # Support both canonical (min_value) and YAML-style (min)
    mn = kwargs.get("min_value") or kwargs.get("min")
    mx = kwargs.get("max_value") or kwargs.get("max")
    
    # Fallback to defaults if still None
    if mn is None: mn = 0
    if mx is None: mx = 100
    return np.random.randint(mn, mx, size=rows)

def generate_random_float(rows: int, **kwargs):
    # Support both canonical (min_value) and YAML-style (min)
    mn = kwargs.get("min_value") or kwargs.get("min")
    mx = kwargs.get("max_value") or kwargs.get("max")
    
    # Fallback to defaults if still None
    if mn is None: mn = 0.0
    if mx is None: mx = 1.0
    return np.random.uniform(mn, mx, size=rows)

def generate_choice(rows: int, **kwargs):
    options = kwargs.get("options", [])
    weights = kwargs.get("weights", None)
    if not options:
        raise ValueError("Provider 'choice' requires 'options' list.")
    
    if weights is not None:
        # Robust Normalization (Restore your fixed arithmetic)
        w = np.array(weights, dtype=float)
        if w.sum() <= 0:
            raise ValueError("Weights must sum to a positive value.")
        p = w / w.sum()
        # Force strict 1.0 sum to satisfy numpy
        if len(p) > 0:
            p[-1] = 1.0 - p[:-1].sum()
    else:
        p = None
        
    return np.random.choice(options, size=rows, p=p)

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
    orphan_rate = float(kwargs.get("orphan_rate", 0.0))

    # Range of valid IDs
    mn = 1
    # If target_rows is set, use it. Else assume self-reference up to current rows.
    mx = (target_rows if target_rows else rows) + 1

    def _inject_orphans(parents):
        """Point a fraction of keys past the parent id range (>= mx, i.e. beyond
        target_rows) so they match no parent row — for studying outer-join /
        FK-enforcement effects. No-op when orphan_rate == 0."""
        if orphan_rate <= 0:
            return parents
        parents = parents.copy().astype(np.int64)
        mask = np.random.rand(len(parents)) < orphan_rate
        n = int(mask.sum())
        if n:
            parents[mask] = np.random.randint(mx, 2 * mx + 1, size=n)
        return parents

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
        return _inject_orphans(parents)

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
        return _inject_orphans(parents)

    else: # uniform
        return _inject_orphans(np.random.randint(mn, mx, size=rows))

def generate_zipf_edges(rows: int, **kwargs):
    """
    Generate a directed edge list for a Zipf-distributed supply graph.

    Each row represents one directed supply edge: (from_id, to_id).
    The number of *outgoing* edges per node follows a power-law / Zipf
    distribution controlled by the ``zipf_a`` parameter:

      - zipf_a=2.0  → moderate skew  (a few large hubs, long tail of leaves)
      - zipf_a=1.5  → heavy skew     (very dominant hubs)
      - zipf_a=3.0  → mild skew      (more uniform, closer to random graph)

    Self-loops are excluded.  The resulting edge list is what gets loaded as
    the ``supplies`` relation in TypeDB and as the ``supplies`` table in DuckDB.

    Columns produced: ``from_id`` (integer), ``to_id`` (integer).

    Note: ``rows`` here is the *total number of edges*, not nodes.  The number
    of nodes is controlled by the ``n_nodes`` kwarg (default 500).
    """
    n_nodes  = int(kwargs.get("n_nodes",  500))
    zipf_a   = float(kwargs.get("zipf_a", 2.0))
    seed     = kwargs.get("seed", 42)
    rng      = np.random.default_rng(seed)

    # --- 1. Assign each node an out-degree drawn from Zipf ---
    # numpy's Zipf returns values >= 1.  Cap at n_nodes-1 so a single node
    # can't supply more companies than exist.
    raw_degrees = rng.zipf(zipf_a, size=n_nodes)
    out_degrees = np.minimum(raw_degrees, n_nodes - 1).astype(int)

    # --- 2. Build edge list ---
    # For each source node, sample ``out_degree`` distinct target nodes
    # (excluding itself).  Collect until we have exactly ``rows`` edges,
    # cycling through nodes if needed.
    from_ids = []
    to_ids   = []
    node_ids = np.arange(1, n_nodes + 1)

    for src_idx, deg in enumerate(out_degrees):
        if len(from_ids) >= rows:
            break
        src_id   = src_idx + 1  # 1-indexed
        targets  = node_ids[node_ids != src_id]
        chosen   = rng.choice(targets, size=min(deg, len(targets)), replace=False)
        remaining = rows - len(from_ids)
        chosen = chosen[:remaining]
        from_ids.extend([src_id] * len(chosen))
        to_ids.extend(chosen.tolist())

    # Pad to exact row count if the degree distribution ran out early
    while len(from_ids) < rows:
        src = rng.integers(1, n_nodes + 1)
        tgt = rng.integers(1, n_nodes + 1)
        if src != tgt:
            from_ids.append(int(src))
            to_ids.append(int(tgt))

    return {
        "from_id": np.array(from_ids[:rows], dtype=np.int64),
        "to_id":   np.array(to_ids[:rows],   dtype=np.int64),
    }


PROVIDER_REGISTRY = {
    "sequence": generate_sequence,
    "random_int": generate_random_int,
    "random_float": generate_random_float,
    "choice": generate_choice,
    "text_concat": generate_text_concat,
    "foreign_key": generate_foreign_key,
    "foreign key": generate_foreign_key,  # Alias
    "zipf_edges": generate_zipf_edges,
}
