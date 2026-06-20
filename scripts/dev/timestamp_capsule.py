#!/usr/bin/env python3
"""
Timestamp a published capsule's seal with OpenTimestamps.

Publication-time action (deliberate, network-required), distinct from sealing
(automatic, offline, every run). Creates integrity.seal.ots — a trustless,
Bitcoin-anchored proof that the seal hash existed by a point in time, so a
result cannot be silently backdated or tampered-then-resealed.

Usage:  python scripts/dev/timestamp_capsule.py <experiment_id> [<experiment_id> ...]
Then later (after a Bitcoin block confirms, ~hours):
        python scripts/dev/upgrade_capsule.py <experiment_id> [<experiment_id> ...]

Requires: pip install opentimestamps-client
"""
import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def timestamp_capsule(exp_id: str) -> bool:
    seal = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results",
                        exp_id, "integrity.seal")
    if not os.path.exists(seal):
        print(f"ERROR: {exp_id} has no integrity.seal — seal the capsule first "
              f"(produced automatically when an experiment finalizes).")
        return False
    if not shutil.which("ots"):
        print("ERROR: `ots` not found. pip install opentimestamps-client")
        return False
    proc = subprocess.run(["ots", "stamp", seal])
    if proc.returncode != 0:
        return False
    print(f"\nStamped: {seal}.ots")
    print("Commit it alongside the capsule. Run `ots upgrade` on it in a few "
          "hours to finalize the Bitcoin attestation.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenTimestamp one or more capsule seals.")
    parser.add_argument("ids", nargs="+", metavar="id", help="8-character Experiment ID(s)")
    args = parser.parse_args()
    results = [timestamp_capsule(exp_id) for exp_id in args.ids]
    sys.exit(0 if all(results) else 1)
