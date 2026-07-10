#!/usr/bin/env python3
"""Reorganize flat agent_runs/ folder.

Groups historical and current flat trace files (.jsonl) into structured folders:
  agent_runs/<study_id>/<primary_run_id>/<trace_files>
or
  agent_runs/<primary_run_id>/<trace_files> (if not part of a study).
"""
import os
import json
import shutil

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_RUNS_DIR = os.path.join(_REPO_ROOT, "sql_benchmarks", "experiments", "agent_runs")


def main():
    if not os.path.exists(AGENT_RUNS_DIR):
        print(f"Directory {AGENT_RUNS_DIR} does not exist.")
        return

    # 1. Scan and collect metadata for all flat jsonl files
    files_meta = []
    all_items = os.listdir(AGENT_RUNS_DIR)
    
    # We only process files directly in AGENT_RUNS_DIR
    jsonl_files = [f for f in all_items if f.endswith(".jsonl") and os.path.isfile(os.path.join(AGENT_RUNS_DIR, f))]
    
    print(f"Found {len(jsonl_files)} flat trace files in {AGENT_RUNS_DIR}.")

    for fname in jsonl_files:
        fpath = os.path.join(AGENT_RUNS_DIR, fname)
        run_id = os.path.splitext(fname)[0]
        
        study_id = None
        delegates = []
        
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    # Extract study_id from prompt_provenance / ablation_flags
                    if event.get("event") == "prompt_provenance":
                        flags = event.get("ablation_flags") or {}
                        if "study_id" in flags:
                            study_id = flags["study_id"]
                    
                    # Extract delegated runs (specialists)
                    if event.get("event") == "delegate":
                        sub_id = event.get("sub_run_id")
                        if sub_id:
                            delegates.append(sub_id)
        except Exception as e:
            print(f"Error reading {fname}: {e}")
            continue

        files_meta.append({
            "filename": fname,
            "run_id": run_id,
            "study_id": study_id,
            "delegates": delegates
        })

    # 2. Build mapping from sub_run_id to parent (primary) run_id
    sub_to_primary = {}
    for meta in files_meta:
        if meta["delegates"]:
            for d in meta["delegates"]:
                sub_to_primary[d] = meta["run_id"]

    # 3. Move files to their structured directories
    moved_count = 0
    for meta in files_meta:
        fname = meta["filename"]
        src = os.path.join(AGENT_RUNS_DIR, fname)
        
        # Primary run ID is either the mapped parent run_id, or itself
        primary_run_id = sub_to_primary.get(meta["run_id"], meta["run_id"])
        
        # Target directory: agent_runs/<study_id>/<primary_run_id>/ or agent_runs/<primary_run_id>/
        parts = [AGENT_RUNS_DIR]
        if meta["study_id"]:
            parts.append(meta["study_id"])
        
        # We also need to check if the parent run has a study ID. If we are a sub-run
        # and our metadata didn't capture a study ID, but our parent run did, we should
        # inherit the parent's study ID!
        if not meta["study_id"] and primary_run_id in sub_to_primary:
            # Let's find the parent's metadata
            parent_meta = next((m for m in files_meta if m["run_id"] == primary_run_id), None)
            if parent_meta and parent_meta["study_id"]:
                parts.append(parent_meta["study_id"])
        elif not meta["study_id"] and primary_run_id != meta["run_id"]:
            # If our primary_run_id is not ourselves, find the parent meta
            parent_meta = next((m for m in files_meta if m["run_id"] == primary_run_id), None)
            if parent_meta and parent_meta["study_id"]:
                parts.append(parent_meta["study_id"])
                
        parts.append(primary_run_id)
        
        dest_dir = os.path.join(*parts)
        os.makedirs(dest_dir, exist_ok=True)
        
        dest = os.path.join(dest_dir, fname)
        try:
            shutil.move(src, dest)
            moved_count += 1
        except Exception as e:
            print(f"Failed to move {fname} -> {dest}: {e}")

    print(f"Successfully reorganized {moved_count} trace files.")


if __name__ == "__main__":
    main()
