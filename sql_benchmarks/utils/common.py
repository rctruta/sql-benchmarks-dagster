import os
import yaml
import jinja2
import jinja2.meta
import numpy as np
from ..constants import ACTIVE_CONFIG_PATH, SQL_DIR

# ==========================================
# 1. CONTEXT & CONFIG LOADING
# ==========================================
def load_context():
    """Single source of truth for the active experiment."""
    if not os.path.exists(ACTIVE_CONFIG_PATH):
        raise FileNotFoundError(f"CRITICAL: Config not found at {ACTIVE_CONFIG_PATH}")
  
    with open(ACTIVE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f) or {}

    execution = config.get("execution", {})
    
    engines = execution.get("engines") or config.get("engines")
    if not engines:
        raise ValueError("Critical: 'engines' not found in execution block or root.")
        
    # We support 'matrix' (V7 name) or 'dimensions' (V6 name)
    dimensions = execution.get("matrix") or execution.get("dimensions") or config.get("dimensions", {})

    if "engines" not in execution:
        # Create it if missing so downstream code doesn't crash accessing ['execution']['engines']
        if "execution" not in config: config["execution"] = {}
        config["execution"]["engines"] = engines
        config["execution"]["matrix"] = dimensions

    raw_tables = config['dataset']['tables']
    # Normalize tables to list of names and dict of configs
    if isinstance(raw_tables, list):
        table_names = raw_tables
        table_configs = {t: {} for t in raw_tables}
    elif isinstance(raw_tables, dict):
        table_names = list(raw_tables.keys())
        table_configs = raw_tables
    else:
        raise ValueError("'dataset.tables' must be a List or Dictionary.")

    return {
        "full_config": config,
        "engines": engines,
        "dataset_config": config["dataset"],
        "tables": table_names,
        "table_defs": table_configs,
        "meta": config.get("meta", {"experiment_id": "unknown"})
    }

def get_target_sql_dir(config):
    suite = config.get("execution", {}).get("test_suite", "")
    return os.path.join(SQL_DIR, suite) if suite else SQL_DIR

# ==========================================
# 2. SCHEMA PARSING
# ==========================================
def get_tables_used_in_sql(sql_path, valid_tables_set):
    """Parses SQL template to find dependencies ({{ table_name }})."""
    with open(sql_path, "r") as f:
        raw_template = f.read()

    env = jinja2.Environment()
    try:
        ast = env.parse(raw_template)
        required_vars = jinja2.meta.find_undeclared_variables(ast)
    except Exception as e:
        print(f"⚠️ Jinja Parse Error {sql_path}: {e}")
        return [], raw_template

    used_tables = [
        var.replace("_table", "") 
        for var in required_vars 
        if var.endswith("_table") and var.replace("_table", "") in valid_tables_set
    ]
    return used_tables, raw_template

def extract_foreign_keys(table_def):
    """Returns list of dicts: [{'col': 'x', 'target': 'y', 'target_col': 'z'}]"""
    fks = []
    for col in table_def.get('columns', []):
        if col.get('provider') == 'foreign_key':
            fks.append({
                'col': col['name'],
                'target': col.get('target_table'),
                'target_col': col.get('target_column')
            })
    return fks

def get_data_dependencies(table_name, table_configs):
    """Returns upstream dependencies for a specific table."""
    deps = set()
    t_conf = table_configs.get(table_name, {})
    
    # Implicit FK deps
    for fk in extract_foreign_keys(t_conf):
        if fk['target']: deps.add(fk['target'])
                
    # Explicit deps
    for d in t_conf.get('deps', []): deps.add(d)
        
    return list(deps)

# ==========================================
# 3. MATH & NORMALIZATION
# ==========================================
def normalize_distribution(options: list, weights: list):
    """
    Robustly normalizes weights for numpy generation.
    Used by BOTH Data Generator (Plugin) and Metadata (Dashboard).
    """
    if len(options) != len(weights):
        raise ValueError(f"Mismatch: {len(options)} options vs {len(weights)} weights")
        
    w_arr = np.array(weights, dtype=float)
    if w_arr.sum() <= 0: raise ValueError("Sum of weights must be positive")
    
    # Normalize to sum to 1.0
    norm_weights = w_arr / w_arr.sum()
    return options, norm_weights

# ==========================================
# 4. METADATA INFERENCE
# ==========================================
def infer_metadata_from_sql(sql_content, dataset_config):
    """Scans SQL for known data keys (e.g. 'sel_1') to derive metadata."""
    mapping = {}
    tables = dataset_config.get('tables', {})
    
    # Build Value Map
    if isinstance(tables, dict):
        for table_def in tables.values():
            for col in table_def.get('columns', []):
                if 'options' in col and 'weights' in col:
                    try:
                        opts, probs = normalize_distribution(col['options'], col['weights'])
                        for opt, p in zip(opts, probs):
                            mapping[str(opt)] = float(p)
                    except ValueError: continue 

    # Scan SQL
    meta = {}
    for key, weight in mapping.items():
        if f"'{key}'" in sql_content or f'"{key}"' in sql_content:
            meta['selectivity_pct'] = weight * 100.0
            meta['data_slice'] = key
            break 
    return meta
