import os

# 1. ANCHOR: The location of THIS file
# Must be inside sql_benchmarks/ folder
CURRENT_FILE_PATH = os.path.abspath(__file__)
PACKAGE_DIR = os.path.dirname(CURRENT_FILE_PATH)
ROOT_DIR = os.path.dirname(PACKAGE_DIR)

# 2. KEY DIRECTORIES
DATA_DIR = os.path.join(ROOT_DIR, "data")
EXPERIMENTS_DIR = os.path.join(PACKAGE_DIR, "experiments")
SCRIPTS_DIR = os.path.join(PACKAGE_DIR, "scripts")
SQL_DIR = os.path.join(SCRIPTS_DIR, "sql")

# 3. THE REGISTRY (New Structure)
# Stores config_{hash}.yaml
CONFIG_ARCHIVE_DIR = os.path.join(EXPERIMENTS_DIR, "configs")

# Stores results_{hash}.csv
RESULTS_DIR = os.path.join(EXPERIMENTS_DIR, "results")

# 4. ACTIVE CONFIG
ACTIVE_CONFIG_PATH = os.path.join(EXPERIMENTS_DIR, "active.yaml")

# Ensure directories exist (Auto-create)
os.makedirs(CONFIG_ARCHIVE_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)