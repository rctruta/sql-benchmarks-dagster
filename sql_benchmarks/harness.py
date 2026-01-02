import os
import shutil
import tempfile
import time
from .constants import ROOT_DIR, DATA_DIR, RESULTS_DIR, VIOLATIONS_DIR, REPORTS_DIR

class IsolationHarness:
    """
    Provides a 'Clean Room' for experiment execution.
    Redirects all file outputs to a scratchpad to prevent state contamination.
    """
    
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self.scratchpad_root = None
        
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
            
        # Ensure fragments dir exists inside results
        os.makedirs(os.path.join(paths["SB_RESULTS_DIR"], "fragments"), exist_ok=True)
            
        return paths

    def cleanup(self):
        """Removes the scratchpad."""
        if self.scratchpad_root and os.path.exists(self.scratchpad_root):
             # Wait a beat for any lagging file handles
            time.sleep(0.1)
            shutil.rmtree(self.scratchpad_root)
