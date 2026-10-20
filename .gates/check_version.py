#!/usr/bin/env python3
"""
check_version — say when this repository's gates are older than the seed's.

  .gates/check_version.py            report
  .gates/check_version.py --check    exit 1 when behind (use in CI, not in a hook)

Gates arrive at init and never again. Two gates once sat in the seed and in no
project at all, including the one whose bug produced them. Nothing noticed,
because nothing was looking.

This looks. It never updates anything by itself — the decision to adopt a gate
belongs to whoever has to live with its findings.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Where the seed lives. A path, so it works before anything is published; set
# GATES_SEED to point elsewhere.
SEED = os.environ.get(
    "GATES_SEED", os.path.expanduser("~/Projects/ai-agent-utils/templates/gates"))


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def main():
    here = read(os.path.join(HERE, "VERSION"))
    seed = read(os.path.join(SEED, "VERSION"))

    if here is None:
        print("gates: no VERSION in this repository — installed before versioning")
    if seed is None:
        print(f"gates: seed not readable at {SEED}; cannot compare.")
        print("       Set GATES_SEED if it lives elsewhere.")
        return
    if here == seed:
        print(f"gates: current (version {here})")
        return

    print(f"gates: this repository has {here or 'none'}, the seed has {seed}")
    print("       Review and adopt:  ~/Projects/ai-agent-utils/templates/update_gates.sh --dry")
    print("       What changed and why:  ~/Projects/ai-agent-utils/GATES.md")
    if "--check" in sys.argv:
        sys.exit(1)


main()
