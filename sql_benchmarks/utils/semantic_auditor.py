import os
import json
import pandas as pd
from typing import List, Dict, Any

class OntologyRegistry:
    """
    Placeholder for Proof-of-Concept. 
    In the future, this would be a full business logic engine.
    """
    def __init__(self):
        # Example constraints
        self.constraints = {
            "total_count": {"min": 0},
            "avg_value": {"min": 0}
        }

    def validate_row(self, row: Dict[str, Any]) -> List[str]:
        violations = []
        for key, val in row.items():
            if key in self.constraints:
                limit = self.constraints[key].get("min")
                if limit is not None and val < limit:
                    violations.append(f"Value {val} for {key} is below minimum {limit}")
        return violations

class SemanticAuditor:
    """
    Audits result sets for semantic hallucinations or business logic violations.
    """
    def __init__(self):
        self.registry = OntologyRegistry()

    def audit_csv(self, csv_path: str) -> Dict[str, Any]:
        """
        Reads a CSV and checks for violations.
        """
        if not os.path.exists(csv_path):
            return {"success": False, "error": f"File not found: {csv_path}"}

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            return {"success": False, "error": f"Failed to read CSV: {e}"}

        all_violations = []
        for idx, row in df.iterrows():
            row_violations = self.registry.validate_row(row.to_dict())
            if row_violations:
                all_violations.append({
                    "row_index": idx,
                    "violations": row_violations
                })

        return {
            "success": len(all_violations) == 0,
            "violations": all_violations,
            "row_count": len(df)
        }

    def audit_fragment(self, fragment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Audits a single benchmark result fragment (JSON).
        """
        metrics = fragment_data.get("metrics", {})
        parameters = fragment_data.get("parameters", {})
        
        # Flatten metrics and parameters for validation
        flat_data = {**metrics, **parameters}
        
        violations = self.registry.validate_row(flat_data)
        
        # Additional logic: Timing hallucinations
        duration = metrics.get("duration_seconds")
        if duration is not None and duration < 0:
            violations.append(f"Negative duration detected: {duration}")
            
        return {
            "success": len(violations) == 0,
            "violations": violations
        }
