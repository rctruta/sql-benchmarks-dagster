import os

# 1. ANCHOR
CURRENT_FILE_PATH = os.path.abspath(__file__)

# 2. ZONES
PACKAGE_DIR = os.path.dirname(CURRENT_FILE_PATH)        # sql_benchmarks/
ROOT_DIR = os.path.dirname(PACKAGE_DIR)                 # sql-benchmarks-dagster/

# 3. SUB-DIRECTORIES (Environment-Aware Redirection)
# Fallback to absolute paths relative to ROOT_DIR
EXPERIMENTS_DIR = os.path.join(PACKAGE_DIR, "experiments")
SCRIPTS_DIR = os.path.join(PACKAGE_DIR, "scripts")
SQL_DIR = os.path.join(SCRIPTS_DIR, "sql")

# OUTPUT REDIRECTION (Used for Zero-Copy Isolation)
DATA_DIR = os.getenv("SB_DATA_DIR", os.path.join(ROOT_DIR, "data"))
RESULTS_DIR = os.getenv("SB_RESULTS_DIR", os.path.join(EXPERIMENTS_DIR, "results"))
VIOLATIONS_DIR = os.getenv("SB_VIOLATIONS_DIR", os.path.join(EXPERIMENTS_DIR, "violations"))
REPORTS_DIR = os.getenv("SB_REPORTS_DIR", os.path.join(EXPERIMENTS_DIR, "reports"))

# 4. FILES
ACTIVE_CONFIG_PATH = os.getenv("ACTIVE_CONFIG_PATH", os.path.join(EXPERIMENTS_DIR, "active.yaml"))
CONFIG_ARCHIVE_DIR = os.path.join(EXPERIMENTS_DIR, "configs")
PROCESSED_SUFFIX = ".processed"
EXPERIMENT_EXTENSIONS = (".yaml", ".yml")

# 5. DAGSTER CONFIG
_package_name = os.path.basename(PACKAGE_DIR) 
DAGSTER_MODULE_TARGET = f"{_package_name}.definitions"

# 6. EXECUTION TUNING
DEFAULT_CHUNK_SIZE = int(os.getenv("SB_CHUNK_SIZE", 500_000))

# 7. SAFETY
AUDIT_LOCK_PATH = os.path.join(ROOT_DIR, "audit.lock")
