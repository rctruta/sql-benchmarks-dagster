
import sys
import os
import logging
from dagster import build_asset_context

# Setup paths (Robust)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from sql_benchmarks.assets.reporting import performance_dashboard
from sql_benchmarks.utils import common as common_utils

import sql_benchmarks.assets.reporting
print(f"[DEBUG] Loaded reporting from: {sql_benchmarks.assets.reporting.__file__}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def regenerate(exp_id):
    print(f"Regenerating Dashboard for: {exp_id}")
    
    # 1. Mock Context for Experiment ID
    import sql_benchmarks.assets.reporting
    
    def mock_load():
        return {"meta": {"experiment_id": exp_id}}
    
    sql_benchmarks.assets.reporting.load_context = mock_load
    
    try:
        # 2. Build Asset Context
        context = build_asset_context()
        # Redirect Dagster log to stdout
        context.log.setLevel(logging.INFO)
        context.log.addHandler(logging.StreamHandler(sys.stdout))
        
        # 3. Run Asset Logic
        result = performance_dashboard(context)
        
        if result:
            print("Dashboard Generated Successfully!")
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Restore (Optional, script is ending anyway)
        pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python regenerate_dashboard.py <experiment_id>")
        sys.exit(1)
        
    regenerate(sys.argv[1])
