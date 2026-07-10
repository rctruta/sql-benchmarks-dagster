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
    for key in ("driver", "replications", "goal", "cells"):
        if key not in contract:
            raise ValueError(f"study contract missing required key: '{key}'")
    # Single `model:` or a `models:` list (weak→strong sweeps in ONE
    # contract). Normalized to a list either way.
    if "models" in contract:
        if not isinstance(contract["models"], list) or not contract["models"]:
            raise ValueError("'models' must be a non-empty list")
    elif "model" in contract:
        contract["models"] = [contract["model"]]
    else:
        raise ValueError("study contract missing required key: 'model' (or 'models')")
    if contract["driver"] not in ("monolith", "multi_agent"):
        raise ValueError(f"unknown driver '{contract['driver']}' (monolith | multi_agent)")
    for cell_name, cell in contract["cells"].items():
        if "flags" not in cell:
            raise ValueError(f"cell '{cell_name}' missing 'flags'")
    return study_id, contract


def run_cell_rep(contract: dict, study_id: str, cell_name: str, rep: int,
                 model: str) -> str:
    """Run one (cell, rep, model). Returns the outcome string."""
    flags = dict(contract["cells"][cell_name]["flags"])
    study_stamp = {"study_id": study_id, "cell": cell_name, "rep": rep,
                   "study_model": model}

    if contract["driver"] == "monolith":
        # Import inside so --dry-run works without litellm installed.
        sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))
        import autonomous_agent
        autonomous_agent.run_agent(
            contract["goal"], model=model,
            study_stamp=study_stamp, **flags,
        )
        return "ran"  # run_agent prints its own outcome; trace has run_end
    else:  # multi_agent
        from sql_benchmarks.agent_orchestrator import Orchestrator
        orch = Orchestrator(goal=contract["goal"], model=model,
                            poll_budget_seconds=float(
                                contract.get("poll_budget_seconds", 180)))
        orch.trace.prompt_provenance(components={}, ablation_flags={
            "architecture": "orchestrator", **study_stamp})
        result = orch.run()
        return result.outcome


def main():
    parser = argparse.ArgumentParser(description="Contract-driven study runner")
    parser.add_argument("contract", help="Path to the study YAML")
    parser.add_argument("--cell", help="Run only this cell")
    parser.add_argument("--model", help="Run only this model (from the contract's list)")
    parser.add_argument("--dry-run", action="store_true", help="Print the matrix and exit")
    args = parser.parse_args()

    study_id, contract = load_contract(args.contract)
    
    from datetime import datetime
    import shutil
    from sql_benchmarks.agent_trace import AGENT_RUNS_DIR, slugify
    
    study_name = os.path.splitext(os.path.basename(args.contract))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    study_dir = os.path.join(AGENT_RUNS_DIR, f"{study_name}_{timestamp}")
    os.makedirs(study_dir, exist_ok=True)
    shutil.copy(args.contract, os.path.join(study_dir, "contract.yaml"))
    
    os.environ["AGENT_STUDY_DIR"] = study_dir
    
    cells = list(contract["cells"])
    if args.cell:
        if args.cell not in cells:
            raise SystemExit(f"unknown cell '{args.cell}' (have: {cells})")
        cells = [args.cell]
    models = contract["models"]
    if args.model:
        if args.model not in models:
            raise SystemExit(f"unknown model '{args.model}' (have: {models})")
        models = [args.model]
    reps = int(contract["replications"])

    print(f"study_id={study_id}  driver={contract['driver']}  models={models}")
    print(f"matrix: {len(models)} model(s) x {len(cells)} cell(s) x {reps} rep(s) "
          f"= {len(models) * len(cells) * reps} runs")
    for c in cells:
        print(f"  {c}: {contract['cells'][c]['flags']}")
    if args.dry_run:
        return

    outcomes = {}
    for model in models:
        for cell in cells:
            for rep in range(1, reps + 1):
                print(f"\n=== study={study_id} model={model} cell={cell} rep={rep} ===")
                model_slug = slugify(model)
                os.environ["AGENT_TRACE_PREFIX"] = f"trace_{model_slug}_{cell}_r{rep}"
                # Per-run isolation: a transient API error in one run must
                # not kill the rest of the matrix.
                try:
                    outcomes[(model, cell, rep)] = run_cell_rep(
                        contract, study_id, cell, rep, model)
                except Exception as e:
                    print(f"    EXCEPTION: {type(e).__name__}: {e}")
                    outcomes[(model, cell, rep)] = f"exception: {e}"

    print(f"\nstudy {study_id} complete: {len(outcomes)} runs")
    print("analyze:  python scripts/tools/analyze_agent_traces.py")


if __name__ == "__main__":
    main()
