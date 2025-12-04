import os

# 1. ANCHOR
CURRENT_FILE_PATH = os.path.abspath(__file__)

# 2. ZONES
PACKAGE_DIR = os.path.dirname(CURRENT_FILE_PATH)        # sql_benchmarks/
ROOT_DIR = os.path.dirname(PACKAGE_DIR)                 # sql-benchmarks-dagster/

# 3. SUB-DIRECTORIES
EXPERIMENTS_DIR = os.path.join(PACKAGE_DIR, "experiments")
SCRIPTS_DIR = os.path.join(PACKAGE_DIR, "scripts")
SQL_DIR = os.path.join(SCRIPTS_DIR, "sql")
DATA_DIR = os.path.join(ROOT_DIR, "data")

# Results are stored 
RESULTS_DIR = os.path.join(EXPERIMENTS_DIR, "results")

# 4. FILES
ACTIVE_CONFIG_PATH = os.path.join(EXPERIMENTS_DIR, "active.yaml")
CONFIG_ARCHIVE_DIR = os.path.join(EXPERIMENTS_DIR, "configs") # Also ensure this is here for the runner

# 5. DAGSTER CONFIG
_package_name = os.path.basename(PACKAGE_DIR) 
DAGSTER_MODULE_TARGET = f"{_package_name}.definitions"