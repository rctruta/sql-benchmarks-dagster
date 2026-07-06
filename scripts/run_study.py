#!/usr/bin/env python3
"""Contract-driven study runner.

A *study* is a matrix of agent runs (cells × replications) defined by a
YAML contract under `sql_benchmarks/experiments/studies/`. This runner:

  1. Loads the contract verbatim; study_id = sha256(bytes)[:8] — the
     same content-addressing discipline as experiment capsules.
  2. Executes every cell × replication sequentially.
  3. Stamps study_id / cell / rep into each run's trace (via the
     ablation_flags of prompt_provenance), so any trace is traceable
     back to the exact contract that produced it.
  4. Prints a per-run outcome line and a final summary.

Usage:
  python scripts/run_study.py sql_benchmarks/experiments/studies/attribution_2x2.yaml
  python scripts/run_study.py <contract.yaml> --cell base        # one cell only
  python scripts/run_study.py <contract.yaml> --dry-run          # show the matrix

Analysis afterwards:
  python scripts/tools/analyze_agent_traces.py
"""
import argparse
import hashlib
import os
import sys

try:
    from dotenv import load_dotenv
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    load_dotenv()
except ImportError:
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, _REPO_ROOT)

import yaml


def load_contract(path: str) -> tuple:
    """Returns (study_id, contract_dict). study_id is content-addressed
    from the file's exact bytes — edit the file, get a new study."""
    with open(path, "rb") as f:
        raw = f.read()
    study_id = hashlib.sha256(raw).hexdigest()[:8]
    contract = yaml.safe_load(raw)
    for key in ("driver", "model", "replications", "goal", "cells"):
        if key not in contract:
            raise ValueError(f"study contract missing required key: '{key}'")
    if contract["driver"] not in ("monolith", "multi_agent"):
        raise ValueError(f"unknown driver '{contract['driver']}' (monolith | multi_agent)")
    for cell_name, cell in contract["cells"].items():
        if "flags" not in cell:
            raise ValueError(f"cell '{cell_name}' missing 'flags'")
    return study_id, contract


def run_cell_rep(contract: dict, study_id: str, cell_name: str, rep: int) -> str:
    """Run one (cell, rep). Returns the outcome string."""
    flags = dict(contract["cells"][cell_name]["flags"])
    study_stamp = {"study_id": study_id, "cell": cell_name, "rep": rep}

    if contract["driver"] == "monolith":
        # Import inside so --dry-run works without litellm installed.
        sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))
        import autonomous_agent
        autonomous_agent.run_agent(
            contract["goal"], model=contract["model"],
            study_stamp=study_stamp, **flags,
        )
        return "ran"  # run_agent prints its own outcome; trace has run_end
    else:  # multi_agent
        from sql_benchmarks.agent_orchestrator import Orchestrator
        orch = Orchestrator(goal=contract["goal"], model=contract["model"])
        orch.trace.prompt_provenance(components={}, ablation_flags={
            "architecture": "orchestrator", **study_stamp})
        result = orch.run()
        return result.outcome


def main():
    parser = argparse.ArgumentParser(description="Contract-driven study runner")
    parser.add_argument("contract", help="Path to the study YAML")
    parser.add_argument("--cell", help="Run only this cell")
    parser.add_argument("--dry-run", action="store_true", help="Print the matrix and exit")
    args = parser.parse_args()

    study_id, contract = load_contract(args.contract)
    cells = list(contract["cells"])
    if args.cell:
        if args.cell not in cells:
            raise SystemExit(f"unknown cell '{args.cell}' (have: {cells})")
        cells = [args.cell]
    reps = int(contract["replications"])

    print(f"study_id={study_id}  driver={contract['driver']}  model={contract['model']}")
    print(f"matrix: {len(cells)} cell(s) x {reps} rep(s) = {len(cells) * reps} runs")
    for c in cells:
        print(f"  {c}: {contract['cells'][c]['flags']}")
    if args.dry_run:
        return

    outcomes = {}
    for cell in cells:
        for rep in range(1, reps + 1):
            print(f"\n=== study={study_id} cell={cell} rep={rep} ===")
            # Per-run isolation: a transient API error in one run must not
            # kill the rest of the matrix (it did, on the first execution
            # of guidance_floor_2x2 — floor reps 2-3 never ran).
            try:
                outcomes[(cell, rep)] = run_cell_rep(contract, study_id, cell, rep)
            except Exception as e:
                print(f"    EXCEPTION: {type(e).__name__}: {e}")
                outcomes[(cell, rep)] = f"exception: {e}"

    print(f"\nstudy {study_id} complete: {len(outcomes)} runs")
    print("analyze:  python scripts/tools/analyze_agent_traces.py")


if __name__ == "__main__":
    main()
