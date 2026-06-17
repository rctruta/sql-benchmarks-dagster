"""Command-line entry point for running experiments.

Exposed as the `sqlbench` console script (see pyproject.toml). The top-level
run_experiment.py is a thin shim over this so `./run.sh` keeps working.
"""
import os
import argparse
import sys

from .coordinator import ExperimentCoordinator
from .constants import EXPERIMENTS_DIR, EXPERIMENT_EXTENSIONS, PROCESSED_SUFFIX


def _is_safe_path(path: str, base: str) -> bool:
    """Returns True only if path is within base (prevents directory traversal)."""
    return os.path.realpath(path).startswith(os.path.realpath(base) + os.sep)


def resolve_targets(target_input: str) -> list:
    """Resolves input string to a list of YAML files."""
    # Absolute or relative path to a specific file
    if os.path.isfile(target_input):
        abs_path = os.path.abspath(target_input)
        # Must live within the experiments directory
        if not _is_safe_path(abs_path, EXPERIMENTS_DIR):
            print(f"[ERROR] Path '{target_input}' is outside the experiments directory.")
            return []
        return [abs_path]

    # Symbolic name (e.g. "queue", "archive") — resolved relative to EXPERIMENTS_DIR only
    symbolic_path = os.path.join(EXPERIMENTS_DIR, target_input)
    if os.path.isdir(symbolic_path) and _is_safe_path(symbolic_path, EXPERIMENTS_DIR):
        return sorted([
            os.path.join(symbolic_path, f)
            for f in os.listdir(symbolic_path)
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
            if not args.auto:
                break  # Stop on first failure in interactive mode

    if not overall_success:
        sys.exit(1)


if __name__ == "__main__":
    main()
