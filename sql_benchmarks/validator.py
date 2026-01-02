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
        dataset = config_dict.get("dataset", {})
        tables = dataset.get("tables", {})
        
        if isinstance(tables, dict):
            # A. Stats Validation (Weights)
            for table_name, table_def in tables.items():
                if not isinstance(table_def, dict): continue
                for col in table_def.get("columns", []):
                    if "weights" in col:
                        weights = col["weights"]
                        if any(w < 0 for w in weights):
                            raise ValueError(f"LOGIC ERROR: Negative weight in {table_name}.{col['name']}")
                        if sum(weights) <= 0:
                            raise ValueError(f"LOGIC ERROR: Weights sum to zero or less in {table_name}.{col['name']}")

            # B. Integrity Validation (Foreign Keys)
            defined_tables = set(tables.keys())
            for table_name, table_def in tables.items():
                if not isinstance(table_def, dict): continue
                for col in table_def.get("columns", []):
                    if col.get("provider") == "foreign_key":
                        target = col.get("target_table")
                        if target not in defined_tables:
                             raise ValueError(f"INTEGRITY ERROR: Broken FK in '{table_name}'. Target '{target}' not defined.")

        print(f"[SUCCESS] Contract '{source_label}' validated.")
        return True
