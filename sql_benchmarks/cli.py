"""Command-line entry point for sqlbench.

Exposed as the `sqlbench` console script (see pyproject.toml). The top-level
run_experiment.py is a thin shim over this so `./run.sh` keeps working.

Subcommands:
  sqlbench run <target> [--auto]       Run experiment(s) (default; also the
                                       legacy positional invocation).
  sqlbench project <projection> <id>   Print a granular projection over
                                       a completed experiment's fragments,
                                       as JSON. Projections: means, scaling,
                                       stability, summary. See
                                       `sql_benchmarks/api/logic/projections.py`.

Legacy invocation preserved: `sqlbench <target>` (no subcommand) behaves
exactly like `sqlbench run <target>` — this is what `run.sh` calls.
"""
import argparse
import json
import os
import sys

from .constants import EXPERIMENTS_DIR, EXPERIMENT_EXTENSIONS, PROCESSED_SUFFIX
from .coordinator import ExperimentCoordinator


# Known subcommands. Anything not in this set falls through to the legacy
# "positional target" behavior so `sqlbench <file>` keeps working.
SUBCOMMANDS = {"run", "project"}


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


def _cmd_run(target: str, auto: bool) -> int:
    targets = resolve_targets(target)
    if not targets:
        print(f"[ERROR] No valid targets found for '{target}'")
        return 1
    print(f"[RUNNER] Processing {len(targets)} targets...")
    overall_success = True
    for t in targets:
        print(f"\n>>> COORDINATING: {os.path.basename(t)}")
        coordinator = ExperimentCoordinator(t, headless=auto)
        if not coordinator.run():
            overall_success = False
            if not auto:
                break  # Stop on first failure in interactive mode
    return 0 if overall_success else 1


def _cmd_project(projection: str, exp_id: str) -> int:
    from .api.data.reader import ResultReader
    from .api.logic.projections import (
        get_experiment_summary,
        get_means_by_partition,
        get_replication_stability,
        get_scaling_factor,
    )

    dispatch = {
        "means": get_means_by_partition,
        "scaling": get_scaling_factor,
        "stability": get_replication_stability,
        "summary": get_experiment_summary,
    }
    if projection not in dispatch:
        print(f"[ERROR] Unknown projection '{projection}'. "
              f"Available: {sorted(dispatch.keys())}", file=sys.stderr)
        return 2

    reader = ResultReader()
    if not reader.results_exist(exp_id):
        print(f"[ERROR] Experiment '{exp_id}' not found", file=sys.stderr)
        return 1

    result = dispatch[projection](exp_id, reader)
    print(json.dumps(result, indent=2))
    return 0


def main():
    # Backwards-compat: `sqlbench <target> [--auto]` (no subcommand) still
    # runs the target. Preserves `./run.sh` and any external callers that
    # rely on the positional invocation.
    if len(sys.argv) >= 2 and sys.argv[1] not in SUBCOMMANDS:
        parser = argparse.ArgumentParser(description="sqlbench — legacy positional invocation")
        parser.add_argument("target", help="YAML file or directory (e.g., 'queue')")
        parser.add_argument("--auto", action="store_true", help="Automated mode")
        args = parser.parse_args()
        sys.exit(_cmd_run(args.target, args.auto))

    # New subcommand parser
    parser = argparse.ArgumentParser(prog="sqlbench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run experiment(s)")
    p_run.add_argument("target", help="YAML file or directory (e.g., 'queue')")
    p_run.add_argument("--auto", action="store_true", help="Automated mode")

    p_proj = sub.add_parser("project",
                            help="Print a granular projection over a completed experiment")
    p_proj.add_argument("projection",
                        choices=["means", "scaling", "stability", "summary"],
                        help="Which projection to compute")
    p_proj.add_argument("exp_id", help="Experiment ID (8-hex)")

    args = parser.parse_args()
    if args.cmd == "run":
        sys.exit(_cmd_run(args.target, args.auto))
    elif args.cmd == "project":
        sys.exit(_cmd_project(args.projection, args.exp_id))


if __name__ == "__main__":
    main()
