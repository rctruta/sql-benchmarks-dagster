import os
import yaml
import jinja2
import jinja2.meta
from ..constants import ACTIVE_CONFIG_PATH, SQL_DIR

def load_context():
    """
    Single source of truth for the active experiment.
    Reads YAML, validates schema, and returns a clean Context object.
    """
    # 1. Check Existence
    if not os.path.exists(ACTIVE_CONFIG_PATH):
        raise FileNotFoundError(f"CRITICAL: Config not found at {ACTIVE_CONFIG_PATH}. Run 'python run_experiment.py <file>'")

    # 2. Read File
    with open(ACTIVE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f) or {}

    # 3. Validate Schema (Strict Mode)
    # We crash immediately if keys are missing. No defaults.
    if "engines" not in config:
        raise ValueError(f"Invalid Config: Missing 'engines' list.")
    
    if "dataset" not in config:
        raise ValueError(f"Invalid Config: Missing 'dataset' block.")

    if "tables" not in config["dataset"]:
        raise ValueError(f"Invalid Config: Missing 'dataset.tables'.")

    # 4. Normalize Tables
    # Supports both List ['a'] and Dict {'a': {}} formats
    raw_tables = config['dataset']['tables']
    if isinstance(raw_tables, list):
        table_names = raw_tables
        table_configs = {t: {} for t in raw_tables}
    elif isinstance(raw_tables, dict):
        table_names = list(raw_tables.keys())
        table_configs = raw_tables
    else:
        raise ValueError("'dataset.tables' must be a List or Dictionary.")

    # 5. Return The Context Bundle
    return {
        "full_config": config,
        "engines": config["engines"], # List of active engines
        "dataset_config": config["dataset"],
        "tables": table_names,        # List of names ["orders", "customers"]
        "table_defs": table_configs,  # Dict of details {"orders": {deps...}}
        "meta": config.get("meta", {"experiment_id": "unknown"})
    }

def get_tables_used_in_sql(sql_path, valid_tables_set):
    """Parses SQL template to find dependencies."""
    with open(sql_path, "r") as f:
        raw_template = f.read()

    env = jinja2.Environment()
    try:
        ast = env.parse(raw_template)
        required_vars = jinja2.meta.find_undeclared_variables(ast)
    except Exception as e:
        print(f"⚠️ Jinja Parse Error {sql_path}: {e}")
        return [], raw_template

    used_tables = []
    for var in required_vars:
        if var.endswith("_table"):
            t_name = var.replace("_table", "")
            if t_name in valid_tables_set:
                used_tables.append(t_name)
                
    return used_tables, raw_template

def get_data_dependencies(table_name, table_configs):
    """Returns upstream dependencies for a specific table based on schema."""
    deps = set()
    t_conf = table_configs.get(table_name, {})
    
    # Look for foreign keys in columns
    columns = t_conf.get('columns', [])
    for col in columns:
        if col.get('provider') == 'foreign_key':
            target = col.get('target_table')
            if target:
                deps.add(target)
                
    # Look for explicit deps (if defined in YAML)
    explicit = t_conf.get('deps', [])
    for d in explicit:
        deps.add(d)
        
    return list(deps)

def get_target_sql_dir(config):
    """
    Determines the specific SQL folder to use based on 'test_suite' in config.
    """
    suite = config.get("execution", {}).get("test_suite", "")
    
    # If suite is defined, look in SQL_DIR/suite/ (e.g. .../sql/joins)
    if suite:
        return os.path.join(SQL_DIR, suite)
    
    # Otherwise default to SQL_DIR root (backward compatibility)
    return SQL_DIR