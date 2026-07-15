#!/usr/bin/env python3
"""
Automates the publication of a capsule to git based on its tier.
Usage: python scripts/dev/publish_capsule.py <id> [--topic <branch_topic>]
"""

import argparse
import os
import subprocess
import sys
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_cmd(cmd, check=True):
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=check, capture_output=True, text=True)

def main():
    parser = argparse.ArgumentParser(description="Automates publishing a capsule to git based on its tier.")
    parser.add_argument("id", help="Capsule 8-hex ID")
    parser.add_argument("--topic", help="Required for exploratory runs (e.g. malloy-tax)")
    args = parser.parse_args()
    
    exp_id = args.id
    
    # 1. Paths
    results_dir = f"sql_benchmarks/experiments/results/{exp_id}"
    config_file = f"sql_benchmarks/experiments/configs/config_{exp_id}.yaml"
    
    full_results = os.path.join(REPO_ROOT, results_dir)
    full_config = os.path.join(REPO_ROOT, config_file)
    
    if not os.path.exists(full_results):
        print(f"[ERROR] Capsule {exp_id} not found at {results_dir}")
        sys.exit(1)
        
    if not os.path.exists(full_config):
        print(f"[ERROR] Config not found at {config_file}")
        sys.exit(1)
        
    # 2. Safety Check (Working tree clean)
    status = run_cmd(["git", "status", "--porcelain=v1"]).stdout
    # Count only modified/staged files, ignore '??' (untracked)
    modified = [line for line in status.splitlines() if not line.startswith("??")]
    if modified:
        print("[ERROR] Git working tree has modified tracked files. Commit or stash them first.")
        print(status)
        sys.exit(1)
        
    # 3. Read Tier
    with open(full_config, "r") as f:
        # Ignore the first line if it's the # experiment_id header injected by coordinator
        content = f.read()
        if content.startswith("#"):
            content = content.split("\n", 1)[1]
        cfg = yaml.safe_load(content) or {}
        
    tier = str((cfg.get("meta") or {}).get("tier", "")).strip().strip("'\"")
    
    if tier == "verified":
        print(f"[INFO] Publishing VERIFIED capsule {exp_id}...")
        branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if branch != "main":
            print(f"[ERROR] Verified capsules must be published from 'main'. Currently on '{branch}'.")
            sys.exit(1)
            
        print("[INFO] Running timestamp_capsule.py...")
        subprocess.run([sys.executable, "scripts/dev/timestamp_capsule.py", exp_id], cwd=REPO_ROOT, check=True)
        
        run_cmd(["git", "add", "-f", results_dir])
        run_cmd(["git", "add", "-f", config_file])
        
        print("[INFO] Updating catalog...")
        subprocess.run([sys.executable, "scripts/tools/gen_experiment_catalog.py"], cwd=REPO_ROOT, check=True)
        run_cmd(["git", "add", "docs/experiments.md"])
        
        run_cmd(["git", "commit", "-m", f"feat: publish verified capsule {exp_id}"])
        
        print("\n[SUCCESS] Verified capsule committed locally.")
        print("Next steps (manual):")
        print(f"  git tag -s sqlbenchdag-<topic>-v1-YYYYMMDD -m \"release summary\"")
        print("  git push origin main")
        print("  git push origin <tag>")
        
    else:
        tier_label = tier if tier else "undeclared (assumed exploratory)"
        print(f"[INFO] Publishing {tier_label.upper()} capsule {exp_id}...")
        if not args.topic:
            print("[ERROR] --topic is required for exploratory runs (e.g. --topic malloy-tax)")
            sys.exit(1)
            
        branch_name = f"wip/{args.topic}"
        current_branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        
        if current_branch != branch_name:
            print(f"[INFO] Switching to branch {branch_name}...")
            if run_cmd(["git", "switch", branch_name], check=False).returncode != 0:
                run_cmd(["git", "switch", "-c", branch_name])
                
        run_cmd(["git", "add", "-f", results_dir])
        run_cmd(["git", "add", "-f", config_file])
        
        print("[INFO] Updating catalog...")
        subprocess.run([sys.executable, "scripts/tools/gen_experiment_catalog.py"], cwd=REPO_ROOT, check=True)
        run_cmd(["git", "add", "docs/experiments.md"])
        
        run_cmd(["git", "commit", "-m", f"chore: publish {tier_label} capsule {exp_id}"])
        print("[INFO] Pushing to origin...")
        
        # Pull before push to avoid simple conflicts if remote branch exists
        run_cmd(["git", "pull", "origin", branch_name], check=False)
        run_cmd(["git", "push", "-u", "origin", branch_name])
        
        print(f"\n[SUCCESS] Exploratory capsule published to branch {branch_name}")

if __name__ == "__main__":
    main()
