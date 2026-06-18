#!/usr/bin/env python3
"""
Finalize a capsule's OpenTimestamps proof (the second, later half of timestamping).

`timestamp_capsule.py` submits the seal hash to calendar servers and writes a
*pending* integrity.seal.ots. A few hours later, once a Bitcoin block has
confirmed the calendar's commitment, run THIS to fetch the on-chain attestation
and bake it into the .ots so it verifies offline forever — no trust in the
calendar, no dependency on anyone.

Usage:  python scripts/dev/upgrade_capsule.py <experiment_id> [<experiment_id> ...]
Then commit the upgraded proof(s):
        git commit -am "chore: finalize OTS attestation"

Requires: pip install opentimestamps-client   (provides the `ots` CLI)

Resolves paths relative to THIS file's repo, so run it from whichever checkout
holds the capsule (normally your primary checkout after `git pull`).
"""
import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def upgrade_capsule(exp_id: str) -> bool:
    ots = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results",
                       exp_id, "integrity.seal.ots")
    if not os.path.exists(ots):
        print(f"ERROR: {exp_id} has no integrity.seal.ots — stamp it first with "
              f"`python scripts/dev/timestamp_capsule.py {exp_id}`.")
        return False
    if not shutil.which("ots"):
        print("ERROR: `ots` not found. pip install opentimestamps-client")
        return False

    # `ots upgrade` rewrites the .ots in place when the Bitcoin attestation is
    # ready, and leaves it untouched (exit 0) while still pending.
    proc = subprocess.run(["ots", "upgrade", ots], capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print(out or "(no output)")

    if "Success" in out or "Got 1 attestation" in out:
        print(f"\nFinalized: {ots}\nCommit it:  git commit -am 'chore: finalize OTS attestation for {exp_id}'")
        return True
    if "Pending" in out or "pending" in out:
        print("\nStill pending — the Bitcoin block hasn't confirmed yet. "
              "Try again in a few hours.")
        return False
    # Unknown state: surface it loudly rather than guess.
    print("\nUnexpected `ots upgrade` output — inspect manually before committing.")
    return proc.returncode == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finalize one or more capsules' OTS proofs.")
    parser.add_argument("ids", nargs="+", metavar="id", help="8-character Experiment ID(s)")
    args = parser.parse_args()
    results = [upgrade_capsule(exp_id) for exp_id in args.ids]
    sys.exit(0 if all(results) else 1)
