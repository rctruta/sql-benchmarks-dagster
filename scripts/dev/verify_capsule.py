#!/usr/bin/env python3
import os
import sys
import argparse
from sql_benchmarks.utils.hasher import generate_integrity_seal

def verify_capsule(exp_id):
    """
    Verifies the cryptographic integrity of an experiment result capsule.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(root_dir, "sql_benchmarks", "experiments", "results", exp_id)
    
    if not os.path.exists(results_dir):
        print(f"ERROR: Result capsule for {exp_id} not found.")
        return False
        
    seal_path = os.path.join(results_dir, "integrity.seal")
    if not os.path.exists(seal_path):
        print(f"WARNING: Result capsule for {exp_id} is UNSEALED (No integrity.seal found).")
        return False
        
    with open(seal_path, "r") as f:
        stored_seal = f.read().strip()
        
    # Re-compute seal based on current disk contents
    computed_seal = generate_integrity_seal(results_dir)
    
    if computed_seal == stored_seal:
        print(f"SUCCESS: Result capsule for {exp_id} is VERIFIED and consistent.")
        return True
    else:
        print(f"CRITICAL ERROR: Integrity violation detected in capsule {exp_id}!")
        print(f"Stored Seal:   {stored_seal}")
        print(f"Computed Seal: {computed_seal}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify the integrity of an experiment result capsule.")
    parser.add_argument("id", help="The 8-character Experiment ID to verify.")
    args = parser.parse_args()
    
    if verify_capsule(args.id):
        sys.exit(0)
    else:
        sys.exit(1)
