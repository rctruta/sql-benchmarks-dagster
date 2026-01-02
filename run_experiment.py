import os
import argparse
import sys
from sql_benchmarks.coordinator import ExperimentCoordinator
from sql_benchmarks.constants import EXPERIMENTS_DIR, EXPERIMENT_EXTENSIONS, PROCESSED_SUFFIX

def resolve_targets(target_input: str) -> list:
    """Resolves input string to a list of YAML files."""
    if os.path.isfile(target_input):
        return [os.path.abspath(target_input)]
        
    # Check for symbolic names (queue, archive)
    symbolic_path = os.path.join(EXPERIMENTS_DIR, target_input)
    if os.path.isdir(symbolic_path):
        return sorted([
            os.path.join(symbolic_path, f) 
            for f in os.listdir(symbolic_path) 
            if f.endswith(EXPERIMENT_EXTENSIONS) and not f.endswith(PROCESSED_SUFFIX)
        ])
        
    if os.path.isdir(target_input):
         return sorted([
            os.path.join(target_input, f) 
            for f in os.listdir(target_input) 
            if f.endswith(EXPERIMENT_EXTENSIONS) and not f.endswith(PROCESSED_SUFFIX)
        ])
    return []

def main():
    parser = argparse.ArgumentParser(description="SQL Benchmarks Experiment Runner (Thin Wrapper)")
    parser.add_argument("target", help="YAML file or directory (e.g., 'queue')")
    parser.add_argument("--auto", action="store_true", help="Automated mode")
    args = parser.parse_args()

    targets = resolve_targets(args.target)
    if not targets:
        print(f"[ERROR] No valid targets found for '{args.target}'")
        sys.exit(1)

    print(f"[RUNNER] Processing {len(targets)} targets...")
    
    overall_success = True
    for target in targets:
        print(f"\n>>> COORDINATING: {os.path.basename(target)}")
        coordinator = ExperimentCoordinator(target, headless=args.auto)
        if not coordinator.run():
            overall_success = False
            if not args.auto: break # Stop on first failure in interactive mode
            
    if not overall_success:
        sys.exit(1)

if __name__ == "__main__":
    main()