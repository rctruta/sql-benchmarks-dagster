import os
import yaml
import shutil
import time
import subprocess
import sys
import json
from .validator import ExperimentValidator
from .constants import ROOT_DIR, CONFIG_ARCHIVE_DIR, EXPERIMENTS_DIR, PROCESSED_SUFFIX, RESULTS_DIR, VIOLATIONS_DIR, REPORTS_DIR, AUDIT_LOCK_PATH, ACTIVE_CONFIG_PATH
from .utils.hasher import generate_experiment_hash, generate_integrity_seal
from .utils.semantic_auditor import SemanticAuditor

class ExperimentCoordinator:
    """
    Orchestrates the Zero-Copy experiment lifecycle:
    Validation -> Redirection -> Execution -> Monitoring -> Commitment
    """
    
    
    def __init__(self, target_yaml: str, headless: bool = False):
        self.target_yaml = target_yaml
        self.headless = headless
        self.config = None
        self.exp_id = None
        
    def run(self) -> bool:
        # 0. Safety Check
        if os.path.exists(AUDIT_LOCK_PATH):
            print("[CRITICAL] AUDIT LOCK ACTIVE. Experiment aborted for safety.")
            return False

        # Phase 1: STRICT VALIDATION
        try:
            with open(self.target_yaml, "r") as f:
                self.config = yaml.safe_load(f)
            
            ExperimentValidator.validate(self.config, source_label=os.path.basename(self.target_yaml))
            
            # Derive Identity (STRICT SHA-BASED)
            self.exp_id = generate_experiment_hash(self.config, ROOT_DIR)
            
            self.config["meta"] = self.config.get("meta", {})
            self.config["meta"]["experiment_id"] = self.exp_id
            
            # Check Registry
            if os.path.exists(os.path.join(CONFIG_ARCHIVE_DIR, f"config_{self.exp_id}.yaml")):
                print(f"[INFO] SKIPPING: Experiment {self.exp_id} already exists in registry.")
                return True
                
        except Exception as e:
            print(f"[REJECTED] Experiment contract failed validation: {e}")
            return False

        # Phase 2: PREPARE EXECUTION (Direct)
        # Write ACTIVE config to the standard location
        os.makedirs(os.path.dirname(ACTIVE_CONFIG_PATH), exist_ok=True)
        with open(ACTIVE_CONFIG_PATH, 'w') as f:
            yaml.dump(self.config, f, sort_keys=False)

        # Phase 3: EXECUTION
        print(f"[INFO] Executing {self.exp_id} directly...")
        
        # Prepare environment (Standard)
        local_env = os.environ.copy()
        # We rely on constants.py picking up defaults or existing env vars
        
        success = self._execute_direct(local_env)
        
        if not success:
            print(f"[FAILURE] Technical execution failed.")
            return False

        # Phase 5: FINAL VERIFICATION & REGISTRY
        return self._finalize_results()

    def _execute_direct(self, local_env: dict) -> bool:
        from .utils.common import generate_partition_keys
        
        # Generate Partition Keys
        matrix = self.config.get("execution", {}).get("matrix") or self.config.get("execution", {}).get("dimensions")
        keys = generate_partition_keys(matrix)
        
        overall_success = True
        keys = keys if keys else [None]
            
        for pk in keys:
            cmd = [sys.executable, "execute_run.py"]
            if pk:
                print(f"       -> Partition: {pk}")
                cmd.extend(["--partition", pk])
            else:
                cmd.append("--all")
            
            print(f"[DEBUG] Running command: {' '.join(cmd)}")
            p = subprocess.run(cmd, cwd=ROOT_DIR, env=local_env)
            if p.returncode != 0:
                overall_success = False
        
        # Final Reporting
        cmd_report = [sys.executable, "execute_run.py", "--reporting"]
        p_report = subprocess.run(cmd_report, cwd=ROOT_DIR, env=local_env)
        
        return overall_success and p_report.returncode == 0

    def _finalize_results(self) -> bool:
        """Verifies that results were successfully generated in the isolated experiment folder."""
        
        # Isolated Architecture: results/{exp_id}/{exp_id}.csv and .html
        exp_folder = os.path.join(RESULTS_DIR, self.exp_id)
        csv_target = os.path.join(exp_folder, f"{self.exp_id}.csv")
        dashboard_target = os.path.join(exp_folder, f"{self.exp_id}.html")
        
        if not os.path.exists(csv_target) and not os.path.exists(dashboard_target):
            print(f"[ERROR] Run finished but no results found (Checked {csv_target} and {dashboard_target})")
            return False

        # 1. Capture Metadata (Isolated)
        metadata = {
            "experiment_id": self.exp_id,
            "timestamp": time.time(),
            "config_id": f"config_{self.exp_id}"
        }
        with open(os.path.join(exp_folder, f"metadata_{self.exp_id}.json"), "w") as f:
            json.dump(metadata, f, indent=4)

        # 1.5 Semantic Audit
        auditor = SemanticAuditor()
        violations = []
        # Audit isolated fragment directory
        fragments_dir = os.path.join(exp_folder, "fragments")
        
        if os.path.exists(fragments_dir):
             for filename in os.listdir(fragments_dir):
                file_path = os.path.join(fragments_dir, filename)
                if filename.endswith(".json"):
                    with open(file_path, 'r') as f:
                        try:
                            data = json.load(f)
                            # Audit fragments in this isolated folder
                            audit_res = auditor.audit_fragment(data)
                            if not audit_res["success"]:
                                violations.append(f"JSON {filename} failed audit: {audit_res['violations']}")
                        except Exception: pass

        is_semantically_valid = len(violations) == 0
        if not is_semantically_valid:
            print(f"[WARNING] Semantic Violation Detected in {self.exp_id}: {violations}")
            # Move semantic violations to VIOLATIONS_DIR/exp_id
            violation_dest = os.path.join(VIOLATIONS_DIR, self.exp_id)
            os.makedirs(violation_dest, exist_ok=True)
            # We copy the failing fragments/results for inspection
            shutil.copy(csv_target, os.path.join(violation_dest, "results.csv"))
            return False

        # 2. Archive Config
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{self.exp_id}.yaml")
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        shutil.copy(ACTIVE_CONFIG_PATH, registry_path)
        
        # 3. Archive copy in experiments/archive
        filename = os.path.basename(self.target_yaml)
        clean_name = filename if not filename.endswith(PROCESSED_SUFFIX) else filename[:-len(PROCESSED_SUFFIX)]
        archive_dest = os.path.join(EXPERIMENTS_DIR, "archive", clean_name)
        os.makedirs(os.path.dirname(archive_dest), exist_ok=True)
        shutil.copy(ACTIVE_CONFIG_PATH, archive_dest)

        print(f"[SUCCESS] Experiment {self.exp_id} finalized. Results at {csv_target}")
        return is_semantically_valid
