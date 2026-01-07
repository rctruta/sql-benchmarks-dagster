import os
from .utils.schema import validate_yaml_content
from .utils.semantic_auditor import OntologyRegistry

class ExperimentValidator:
    """
    Ensures the experiment "Contract" is strictly valid before any execution.
    Combines Pydantic schema validation with business logic rules.
    """
    
    @staticmethod
    def validate(config_dict: dict, source_label: str = "config"):
        # 1. Structural & Static Schema Validation
        try:
            validate_yaml_content(config_dict)
        except Exception as e:
            raise ValueError(f"SCHEMA ERROR in {source_label}:\n{e}")

        # 2. Logic & Ontology Validation
        execution = config_dict.get("execution", {})
        matrix = execution.get("matrix") or execution.get("dimensions") or {}
        
        # A. Matrix Validation (Numeric constraints)
        if "rows" in matrix:
            for r in matrix["rows"]:
                if isinstance(r, (int, float)) and r < 0:
                    raise ValueError(f"Negative value {r} not allowed in 'rows'")
        
        if "selectivity" in matrix:
            for s in matrix["selectivity"]:
                if isinstance(s, (int, float)) and (s < 0 or s > 1):
                    raise ValueError(f"Selectivity {s} for 'selectivity' must be between 0 and 1")

        dataset = config_dict.get("dataset", {})
        tables = dataset.get("tables", {})
        
        if isinstance(tables, dict):
            # B. Stats Validation (Weights)
            for table_name, table_def in tables.items():
                if not isinstance(table_def, dict): continue
                for col in table_def.get("columns", []):
                    if "weights" in col:
                        weights = col["weights"]
                        if any(w < 0 for w in weights):
                            raise ValueError(f"LOGIC ERROR: Negative weight in {table_name}.{col['name']}")
                        if sum(weights) <= 0:
                            raise ValueError(f"LOGIC ERROR: Weights sum to zero or less in {table_name}.{col['name']}")

            # C. Integrity Validation (Foreign Keys)
            defined_tables = set(tables.keys())
            for table_name, table_def in tables.items():
                if not isinstance(table_def, dict): continue
                for col in table_def.get("columns", []):
                    if col.get("provider") == "foreign_key":
                        target = col.get("target_table")
                        if target not in defined_tables:
                             raise ValueError(f"Broken FK in 'orders'. Target '{target}' not defined")

        print(f"[SUCCESS] Contract '{source_label}' validated.")
        return True
