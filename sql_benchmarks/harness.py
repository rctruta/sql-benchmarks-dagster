import os
import shutil
import tempfile
import time
from .constants import ROOT_DIR, DATA_DIR, RESULTS_DIR, VIOLATIONS_DIR, REPORTS_DIR
from .utils.integrity_monitor import IntegrityMonitor

class IsolationHarness:
    """
    Provides a 'Clean Room' for experiment execution.
    Redirects all file outputs to a scratchpad to prevent state contamination.
    """
    
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self.scratchpad_root = None
        self._monitor = None
        
    def provision(self) -> dict:
        """Creates the scratchpad and returns the redirection environment."""
        self.scratchpad_root = tempfile.mkdtemp(prefix=f"sb_{self.experiment_id}_")
        
        # Create standard layout inside scratchpad
        paths = {
            "SB_DATA_DIR": os.path.join(self.scratchpad_root, "data"),
            "SB_RESULTS_DIR": os.path.join(self.scratchpad_root, "results"),
            "SB_VIOLATIONS_DIR": os.path.join(self.scratchpad_root, "violations"),
            "SB_REPORTS_DIR": os.path.join(self.scratchpad_root, "reports"),
            "SCRATCHPAD_ROOT": self.scratchpad_root
        }
        
        for p in paths.values():
            os.makedirs(p, exist_ok=True)
            
        # Ensure critical subdirectories exist
        os.makedirs(os.path.join(paths["SB_DATA_DIR"], "staging"), exist_ok=True)
        os.makedirs(os.path.join(paths["SB_DATA_DIR"], "duckdb"), exist_ok=True)
        os.makedirs(os.path.join(paths["SB_RESULTS_DIR"], "fragments"), exist_ok=True)

        # Snapshot the package source NOW: if any code changes while the
        # experiment runs, the Experiment ID no longer describes what ran.
        from .constants import PACKAGE_DIR
        self._monitor = IntegrityMonitor(PACKAGE_DIR)

        return paths

    def check_integrity(self) -> list:
        """
        Compares the package source against the snapshot taken at provision().
        Returns drift entries (MODIFIED/ADDED/DELETED) — any code change during
        an experiment invalidates the run, because the Experiment ID was
        computed from the code as it stood at submission.

        History note: a previous implementation here only inspected a
        sentinel file named secure_pill.txt (planted by its own test) and
        could never detect real tampering. Replaced with the IntegrityMonitor
        snapshot mechanism this docstring's promises always implied.
        """
        if self._monitor is None:
            return []
        return self._monitor.check_drift()

    def cleanup(self):
        """Removes the scratchpad."""
        if self.scratchpad_root and os.path.exists(self.scratchpad_root):
             # Wait a beat for any lagging file handles
            time.sleep(0.1)
            shutil.rmtree(self.scratchpad_root)
