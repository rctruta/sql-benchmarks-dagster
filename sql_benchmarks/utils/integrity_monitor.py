import os
import hashlib

class IntegrityMonitor:
    """
    Monitors a directory for any changes after an initial snapshot.
    Used to ensure the 'Clean Room' staging area remains isolated.
    """
    def __init__(self, target_dir):
        self.target_dir = target_dir
        self.initial_state = self._compute_state()

    def _compute_state(self):
        state = {}
        for root, _, files in os.walk(self.target_dir):
            for file in files:
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, self.target_dir)
                
                # Ignore runtime artifacts and transient directories
                if "__pycache__" in rel_path or rel_path.endswith(".pyc"):
                    continue
                    
                try:
                    with open(path, "rb") as f:
                        state[rel_path] = hashlib.sha256(f.read()).hexdigest()
                except Exception:
                    continue
        return state

    def check_drift(self):
        """Returns a list of files that have been modified, added, or deleted."""
        current_state = self._compute_state()
        drift = []
        
        # Check for modifications and deletions
        for path, original_hash in self.initial_state.items():
            if path not in current_state:
                drift.append(f"DELETED: {path}")
            elif current_state[path] != original_hash:
                curr_hash = current_state[path]
                drift.append(f"MODIFIED: {path} (Expected: {original_hash[:8]}... Got: {curr_hash[:8]}...)")
        
        # Check for additions
        for path in current_state:
            if path not in self.initial_state:
                drift.append(f"ADDED: {path}")
                
        return drift
