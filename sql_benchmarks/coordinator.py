import os
import yaml
import shutil
import time
import subprocess
import sys
import json
import traceback
from .validation import validate_experiment_config
from .failure_marker import write_failure_marker
from .constants import ROOT_DIR, CONFIG_ARCHIVE_DIR, EXPERIMENTS_DIR, PROCESSED_SUFFIX, RESULTS_DIR, VIOLATIONS_DIR, REPORTS_DIR, AUDIT_LOCK_PATH, ACTIVE_CONFIG_PATH
from .utils.hasher import generate_experiment_hash, generate_integrity_seal
from .utils.common import copy_suite_queries
from .utils.semantic_auditor import SemanticAuditor
from .harness import IsolationHarness

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
        # Raw source bytes, captured at validation — the exact text that was
        # parsed and hashed. Archived verbatim into the capsule so the stored
        # config is the author's file, not a re-serialization of it.
        self._source_yaml = None

    def _write_failure(self, stage: str, error: str, tb: str = None) -> None:
        """Write results/<exp_id>/failure.json so /status can surface the failure.
        No-op if the exp_id hasn't been assigned yet (validation failures happen
        before the hash is computed and have no ID to key the marker on)."""
        if not self.exp_id:
            return
        try:
            write_failure_marker(RESULTS_DIR, self.exp_id, stage, error, tb)
        except Exception as e:
            print(f"[WARN] could not write failure marker for {self.exp_id}: {e}")

    def run(self) -> bool:
        # 0. Safety Check
        if os.path.exists(AUDIT_LOCK_PATH):
            print("[CRITICAL] AUDIT LOCK ACTIVE. Experiment aborted for safety.")
            return False

        # Phase 1: STRICT VALIDATION
        try:
            with open(self.target_yaml, "r") as f:
                self._source_yaml = f.read()
            self.config = yaml.safe_load(self._source_yaml)

            validate_experiment_config(self.config, source_label=os.path.basename(self.target_yaml))
            
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

        # Phase 2: PREPARE EXECUTION (Isolated)
        #
        # Write the canonical active.yaml FIRST (with experiment_id injected).
        # This is the single source of truth: every component that reads
        # active.yaml will see the same config, and the file can be traced back
        # to the exact experiment being run.
        with open(ACTIVE_CONFIG_PATH, 'w') as f:
            yaml.dump(self.config, f, sort_keys=False)
        print(f"[INFO] active.yaml updated → experiment_id: {self.exp_id}")

        harness = IsolationHarness(self.exp_id)
        redirects = harness.provision()
        os.environ.update(redirects)

        # Point the scratchpad's active.yaml at the same config so that
        # subprocesses running inside the scratchpad read the correct experiment.
        active_path = os.path.join(redirects["SCRATCHPAD_ROOT"], "active.yaml")
        os.environ["ACTIVE_CONFIG_PATH"] = active_path
        os.makedirs(os.path.dirname(active_path), exist_ok=True)
        with open(active_path, 'w') as f:
            yaml.dump(self.config, f, sort_keys=False)

        # Phase 3: EXECUTION
        print(f"[INFO] Executing {self.exp_id} in isolated scratchpad...")
        
        try:
            try:
                # Prepare environment
                local_env = os.environ.copy()
                success = self._execute_direct(local_env)

                if not success:
                    self._write_failure(
                        "execution",
                        "Technical execution failed (subprocess returned non-zero exit code).",
                    )
                    print(f"[FAILURE] Technical execution failed.")
                    return False

                # Phase 4: CODE-DRIFT GATE
                # The Experiment ID was computed from the code at submission; if
                # the package changed during execution, the ID no longer names
                # what actually ran. Refuse to finalize — loudly.
                drift = harness.check_integrity()
                if drift:
                    self._write_failure(
                        "drift",
                        "Code drift detected during execution: " + "; ".join(drift),
                    )
                    print(f"[CRITICAL] Code drift detected during execution — results NOT committed:")
                    for d in drift:
                        print(f"           {d}")
                    return False

                # Phase 5: FINAL VERIFICATION & REGISTRY
                return self._finalize_results()

            except Exception as e:
                # Catch-all so unexpected exceptions in the execution/finalize
                # path still produce a failure marker the /status endpoint can
                # surface. Without this, the FastAPI background task would
                # swallow the exception and the poller would hang on 'queued'.
                self._write_failure(
                    "coordinator_exception",
                    f"{type(e).__name__}: {e}",
                    traceback.format_exc(),
                )
                raise
        finally:
            harness.cleanup()

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
            
            p = subprocess.run(cmd, cwd=ROOT_DIR, env=local_env)
            if p.returncode != 0:
                overall_success = False
        
        # Final Reporting
        cmd_report = [sys.executable, "execute_run.py", "--reporting"]
        p_report = subprocess.run(cmd_report, cwd=ROOT_DIR, env=local_env)
        
        return overall_success and p_report.returncode == 0

    def _finalize_results(self) -> bool:
        """
        Verifies results in the scratchpad, then commits them to the canonical
        results directory.

        The scratchpad env var (SB_RESULTS_DIR) is set by the harness AFTER
        coordinator constants are imported, so the module-level RESULTS_DIR
        still points to the real experiments/results/ dir.  We therefore look
        for results in the scratchpad first, then copy them to the canonical dir.
        """
        # The subprocess wrote results here (env-redirected scratchpad)
        scratchpad_results = os.environ.get("SB_RESULTS_DIR", RESULTS_DIR)
        scratch_exp_folder = os.path.join(scratchpad_results, self.exp_id)

        # Canonical destination (the real experiments/results/ dir)
        canonical_exp_folder = os.path.join(RESULTS_DIR, self.exp_id)

        csv_target = os.path.join(scratch_exp_folder, f"{self.exp_id}.csv")
        dashboard_target = os.path.join(scratch_exp_folder, f"{self.exp_id}.html")

        if not os.path.exists(csv_target) and not os.path.exists(dashboard_target):
            self._write_failure(
                "no_results",
                f"Run finished but produced no CSV or dashboard (looked at {csv_target}).",
            )
            print(f"[ERROR] Run finished but no results found (Checked {csv_target} and {dashboard_target})")
            return False

        # 1. Capture Metadata (in scratchpad first)
        from .utils.system import capture_environment, generator_id
        metadata = {
            "experiment_id": self.exp_id,
            "timestamp": time.time(),
            "config_id": f"config_{self.exp_id}",
            # Conditions, not identity: the bench this question was answered on
            "environment": capture_environment(),
            # Effective data seed (declarative_gen): explicit even when the
            # YAML omits it — a capsule must state the seed its data came
            # from, never leave it implied by a code default.
            "dataset_seed": (self.config.get("dataset") or {}).get("seed", 42),
            # Maker's mark: which tool + build produced this capsule.
            "generator": generator_id(),
        }
        with open(os.path.join(scratch_exp_folder, f"metadata_{self.exp_id}.json"), "w") as f:
            json.dump(metadata, f, indent=4)

        # 1.5 Semantic Audit
        auditor = SemanticAuditor()
        violations = []
        fragments_dir = os.path.join(scratch_exp_folder, "fragments")

        if os.path.exists(fragments_dir):
            for filename in os.listdir(fragments_dir):
                file_path = os.path.join(fragments_dir, filename)
                if filename.endswith(".json"):
                    with open(file_path, 'r') as f:
                        try:
                            data = json.load(f)
                            audit_res = auditor.audit_fragment(data)
                            if not audit_res["success"]:
                                violations.append(f"JSON {filename} failed audit: {audit_res['violations']}")
                        except json.JSONDecodeError as e:
                            violations.append(f"JSON {filename} is malformed: {e}")

        is_semantically_valid = len(violations) == 0
        if not is_semantically_valid:
            print(f"[WARNING] Semantic Violation Detected in {self.exp_id}: {violations}")
            violation_dest = os.path.join(VIOLATIONS_DIR, self.exp_id)
            os.makedirs(violation_dest, exist_ok=True)
            shutil.copy(csv_target, os.path.join(violation_dest, "results.csv"))
            return False

        # 2. Commit scratchpad → canonical results dir
        # Guard: source and destination must be disjoint trees. A destination
        # nested inside its source turns copytree into infinite recursive
        # nesting (historical incident: 5K+ file explosion -> OOM).
        src_real = os.path.realpath(scratch_exp_folder)
        dst_real = os.path.realpath(canonical_exp_folder)
        if src_real.startswith(dst_real + os.sep) or dst_real.startswith(src_real + os.sep):
            raise RuntimeError(
                f"REFUSED: nested copy {src_real} <-> {dst_real} would recurse infinitely."
            )
        if scratch_exp_folder != canonical_exp_folder:
            if os.path.exists(canonical_exp_folder):
                # Only ever delete a folder named exactly for this experiment
                if os.path.basename(dst_real) != self.exp_id:
                    raise RuntimeError(
                        f"REFUSED: rmtree target '{dst_real}' is not this experiment's capsule."
                    )
                shutil.rmtree(canonical_exp_folder)
            shutil.copytree(scratch_exp_folder, canonical_exp_folder)
            print(f"[INFO] Results committed: {scratch_exp_folder} → {canonical_exp_folder}")

        # Update csv_target to canonical location for final log message
        csv_target = os.path.join(canonical_exp_folder, f"{self.exp_id}.csv")

        # 3. Archive the EXACT source config into the capsule.
        # Byte-faithful: the author's original file, NOT a yaml.dump
        # re-serialization. A round-trip launders formatting that carries intent
        # — underscored ints (1_000_000 -> 1000000), folded prose blocks ->
        # escaped one-liners, real unicode dashes -> \uXXXX — and so the stored
        # file would misrepresent "the exact config that ran." The Experiment ID
        # is hashed from the PARSED dict, so byte-faithful archival changes no
        # ID; the ID itself is recorded in the folder name and metadata_<ID>.json.
        experiment_config_dest = os.path.join(canonical_exp_folder, "experiment_config.yaml")
        self._archive_source_config(experiment_config_dest)

        # 3.4 Embed the queries that ran — the selected engines' dialect SQL —
        # into queries/ so a reader sees them without tracing fragments to
        # source. A convenience copy; the Experiment ID hashes the full suite
        # from source independently (see utils.common.copy_suite_queries).
        copy_suite_queries(canonical_exp_folder)

        # 3.5 Seal the capsule: aggregate hash over every file in the final
        # canonical folder (the seal itself excluded). verify_capsule.py
        # recomputes and compares — tamper evidence for published results.
        # (Designed in docs/integrity_sealing.md; wiring completed here.)
        seal = generate_integrity_seal(canonical_exp_folder)
        with open(os.path.join(canonical_exp_folder, "integrity.seal"), "w") as f:
            f.write(seal)

        # 4. Archive Config registry
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{self.exp_id}.yaml")
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        shutil.copy(ACTIVE_CONFIG_PATH, registry_path)

        # 5. Archive copy in experiments/archive
        filename = os.path.basename(self.target_yaml)
        clean_name = filename if not filename.endswith(PROCESSED_SUFFIX) else filename[:-len(PROCESSED_SUFFIX)]
        archive_dest = os.path.join(EXPERIMENTS_DIR, "archive", clean_name)
        os.makedirs(os.path.dirname(archive_dest), exist_ok=True)
        shutil.copy(os.environ["ACTIVE_CONFIG_PATH"], archive_dest)

        print(f"[SUCCESS] Experiment {self.exp_id} finalized. Results at {csv_target}")
        return is_semantically_valid

    def _archive_source_config(self, dest_path: str) -> None:
        """Write the captured source YAML (the exact bytes that were parsed and
        hashed) into the capsule, prefixed with a one-line provenance header that
        stamps the Experiment ID. The header is a YAML comment, so it is invisible
        to the hash (the ID is computed from the parsed config) and the body below
        stays byte-identical to the author's source. Fail loud if never captured —
        an empty/missing archived config is a silent provenance hole."""
        if not self._source_yaml:
            raise RuntimeError(
                "REFUSED: no source config captured; cannot archive the capsule's "
                "experiment_config.yaml. (Was the coordinator run via run()?)"
            )
        header = f"# experiment_id: {self.exp_id}  (run conditions: metadata_{self.exp_id}.json)\n"
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(header + self._source_yaml)
