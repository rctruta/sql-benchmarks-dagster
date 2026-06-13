#!/usr/bin/env python3
"""
Verify a published result capsule end to end:

  1. INTEGRITY  — recompute the seal over the capsule's files and compare it
                  to the stored integrity.seal (detects any byte change).
  2. TIMESTAMP  — if integrity.seal.ots is present, verify the OpenTimestamps
                  proof (the seal existed at/by a point in time; trustless,
                  Bitcoin-anchored). Requires the `ots` client; skipped with a
                  notice if unavailable.

Authorship (who produced it) is verified separately via the signed git tag:
  git verify-tag <tag>

Usage:  python scripts/dev/verify_capsule.py <experiment_id>
"""
import argparse
import os
import shutil
import subprocess
import sys

# Run standalone from anywhere: put the repo root (3 levels up) on the path.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from sql_benchmarks.utils.hasher import generate_integrity_seal


def verify_capsule(exp_id: str) -> bool:
    results_dir = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results", exp_id)
    if not os.path.isdir(results_dir):
        print(f"ERROR: Result capsule for {exp_id} not found at {results_dir}")
        return False

    seal_path = os.path.join(results_dir, "integrity.seal")
    if not os.path.exists(seal_path):
        print(f"WARNING: Capsule {exp_id} is UNSEALED (no integrity.seal).")
        return False

    # 1. INTEGRITY
    with open(seal_path) as f:
        stored = f.read().strip()
    computed = generate_integrity_seal(results_dir)
    if computed != stored:
        print(f"CRITICAL: integrity violation in {exp_id}!")
        print(f"  stored:   {stored}")
        print(f"  computed: {computed}")
        return False
    print(f"[1/2] INTEGRITY  OK — {exp_id} bytes match the seal.")

    # 2. TIMESTAMP (optional sidecar)
    ots_path = seal_path + ".ots"
    if not os.path.exists(ots_path):
        print(f"[2/2] TIMESTAMP  — no integrity.seal.ots (capsule not timestamped).")
        return True
    if not shutil.which("ots"):
        print(f"[2/2] TIMESTAMP  — integrity.seal.ots present but `ots` client not "
              f"installed; skipping (pip install opentimestamps-client).")
        return True
    proc = subprocess.run(["ots", "verify", ots_path], capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).lower()
    if "pending" in out:
        print(f"[2/2] TIMESTAMP  PENDING — calendars committed (submission time "
              f"attested); run `ots upgrade {ots_path}` after the next Bitcoin "
              f"block to finalize the trustless proof.")
    elif "success" in out or "attests existence" in out or "bitcoin block" in out:
        print(f"[2/2] TIMESTAMP  OK — seal anchored to the Bitcoin blockchain.")
    else:
        print(f"[2/2] TIMESTAMP  could not be verified:\n{proc.stdout}{proc.stderr}")
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify a result capsule (integrity + timestamp).")
    parser.add_argument("id", help="8-character Experiment ID")
    args = parser.parse_args()
    sys.exit(0 if verify_capsule(args.id) else 1)
