import os
import yaml
import jinja2
import jinja2.meta
import numpy as np
from ..constants import ACTIVE_CONFIG_PATH, SQL_DIR
from ..config_loader import ConfigLoader
from typing import Dict, Any

# Initialize the compiler once globally
# NOTE: If this fails to initialize due to a strict violation, the error will propagate up 
# when Dagster tries to load definitions, which is the correct fail-hard behavior.
# ==========================================
# 1. CONTEXT & CONFIG LOADING
# ==========================================
try:
    _GLOBAL_COMPILER = ConfigLoader()
except ValueError as e:
    # Propagate structural errors during load time
    raise e 

def load_context() -> Dict[str, Any]:
    """
    Returns a consolidated context dictionary containing all derived and raw configuration
    needed by asset factories. This replaces the old context loading logic.
    """
    raw_config = _GLOBAL_COMPILER.get_full_config()
    
    # --- Tracing All Necessary Context for Asset Factories ---
    
    # 1. Core Config Blocks
    context = {
        "full_config": raw_config,
        "execution": _GLOBAL_COMPILER.execution,
        "definitions": _GLOBAL_COMPILER.definitions,
        "dataset_config": _GLOBAL_COMPILER.dataset, # Used by benchmark_factory for schema inference
    }

    # 2. Derived/Extracted Context (Crucial for Downstream Logic)
    
   # A. Active Engines (Used by benchmark_factory to loop over engines)
    context["engines"] = context["execution"].get("engines", [])
    
    # B. Valid Tables (Set of table names for dependency checking)
    table_defs = context["dataset_config"].get("tables", {})
    context["tables"] = set(table_defs.keys())
    
    # C. Legacy Contract Fulfillment
    context["table_defs"] = table_defs
    
    # D. Experiment Metadata
    context["meta"] = raw_config.get("meta", {})
    
    # E. Full Scenario Config
    context["scenario_config"] = _GLOBAL_COMPILER.scenario_config
    
    return context

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
        print(f"Jinja Parse Error {sql_path}: {e}")
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
    
    # THE FIX: Handle floating point drift (numpy strict division)
    # Guaranteed to sum to exactly 1.0
    if len(norm_weights) > 0:
        norm_weights[-1] = 1.0 - norm_weights[:-1].sum()
        
    return options, norm_weights

# ==========================================
# 4. METADATA INFERENCE
# ==========================================
def infer_metadata_from_sql(sql_content, dataset_config):
    """Scans SQL for known data keys to derive metadata."""
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

# ==========================================
# 5. PARTITION KEYS
# ==========================================

def generate_partition_keys(matrix_config):
    """
    Takes a matrix dict and returns sorted partition keys.
    Used by: sensors.py, run_experiment.py (CLI), and potentially partitions.py
    """
    import itertools
    
    if not matrix_config:
        return []

    # 1. Sort keys to ensure consistent naming
    keys = sorted(matrix_config.keys())
    values = [matrix_config[k] for k in keys]
    
    # 2. Cartesian Product
    partition_keys = []
    for combination in itertools.product(*values):
        key_str = "_".join(str(v) for v in combination)
        partition_keys.append(key_str)
        
    return partition_keys

# ==========================================
# 6. ASSET NAMING UTILITY 
# ==========================================

def get_engine_asset_prefix(engine_name: str) -> str:
    """
    Resolves the engine resource key ('postgres', 'duckdb')
    to the canonical asset prefix ('pg_', 'duckdb_').
    This is the single source of truth for asset naming conventions across all factories.
    """
    if engine_name == 'postgres':
        return 'pg_'
    # Default: Use the engine name itself followed by an underscore
    return f'{engine_name}_'

# Engines whose SQL dialect is another engine's: they reuse that engine's
# scenario directory instead of duplicating SQL files. Quack is DuckDB served
# over a client-server protocol — identical dialect, different transport.
ENGINE_SQL_DIALECTS = {
    "quack": "duckdb",
}

def get_engine_sql_dialect(engine_name: str) -> str:
    """
    Resolves an engine resource key to the SQL scenario directory it executes
    (sql/<suite>/<dialect>/). The single source of truth for dialect reuse.
    """
    return ENGINE_SQL_DIALECTS.get(engine_name, engine_name)

def get_engine_benchmark_group(engine_name: str) -> str:
    """
    Dagster group name for an engine's benchmark assets. Shared by the
    benchmark factory (asset creation) and execute_run (asset selection) so
    the two can never drift apart.
    """
    return f"dynamic_bench_{engine_name}"

def get_scoped_asset_name(base_name: str, exp_id: str) -> str:
    """
    Generates a globally unique asset name prefixed by the experiment ID.
    Format: e_<exp_id>__<base_name>
    """
    if not exp_id or exp_id == "unknown":
        return base_name
    return f"e_{exp_id}__{base_name}"