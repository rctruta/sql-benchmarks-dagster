import os
import yaml
import itertools
from typing import Dict, Any, Tuple, List
from .constants import ACTIVE_CONFIG_PATH

class ConfigLoader:
    def __init__(self, config_path: str = ACTIVE_CONFIG_PATH):
        self.config_path = config_path
        self._raw_config: Dict[str, Any] = {}
        self.execution: Dict[str, Any] = {}
        self.definitions: Dict[str, Any] = {}
        self.dataset: Dict[str, Any] = {}
        
        # Public, consolidated artifacts
        self.scenario_config: Dict[str, Dict[str, Any]] = {}
        self.partition_keys: List[str] = []

        self._load_and_validate()
        self._compile_scenario_config()

    def _load_and_validate(self) -> None:
        """Loads YAML and performs initial structural checks."""
        if not os.path.exists(self.config_path):
            return

        try:
            with open(self.config_path, "r") as f:
                self._raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            raise ValueError(f"CRITICAL: Failed to parse {self.config_path}: {e}")

        # --- STRICT SCHEMA & SEMANTIC VALIDATION ---
        from .validator import ExperimentValidator
        ExperimentValidator.validate(self._raw_config, source_label=self.config_path)

        self.execution = self._raw_config.get("execution", {})
        self.definitions = self._raw_config.get("definitions", {})
        self.dataset = self._raw_config.get("dataset", {})

    def _compile_scenario_config(self) -> None:
        """
        Translates the symbolic matrix into numeric parameters and generates partition keys.
        This is the consolidated logic from partitions.py.
        """
        if "matrix" not in self.execution:
             raise ValueError("CRITICAL: Experiment must define a 'matrix' strictly under 'execution.matrix'.")
             
        matrix = self.execution["matrix"]
        keys = sorted(list(matrix.keys()))
        symbolic_values = [matrix[k] for k in keys]

        for symbolic_combination in itertools.product(*symbolic_values):
            
            # A. Create the Symbolic Partition Key (e.g., 'tiny_ssd')
            key_str = "_".join(str(v) for v in symbolic_combination)
            self.partition_keys.append(key_str)
            
            # B. Translate to Numeric/Literal Values for Execution (The Payload)
            numeric_params = {}
            for dim_name, symbolic_value in zip(keys, symbolic_combination):
                definition_map = self.definitions.get(dim_name, {})
                
                # 1. Try to resolve the alias using the definition map
                if symbolic_value in definition_map:
                    numeric_value = definition_map[symbolic_value]
                
                # 2. STRICT VALIDATION (Non-hardcoded): Fail if expected alias is missing
                elif isinstance(symbolic_value, str) and definition_map and symbolic_value not in definition_map:
                     raise ValueError(
                        f"STRICT VIOLATION: Alias '{symbolic_value}' in matrix dimension '{dim_name}' "
                        f"could not be resolved. Definition block 'definitions.{dim_name}' exists "
                        "but is missing this alias."
                     )
                
                # 3. Otherwise, the value is a literal (e.g., 'ssd', 1000).
                else:
                    numeric_value = symbolic_value
                
                numeric_params[dim_name] = numeric_value

            # C. Assemble namespaced engine params: the static execution.engine_params
            # block merged with namespaced matrix dimensions ('postgres.work_mem'
            # -> engine_params['postgres']['work_mem']). Varied dimensions override
            # static values. Stored as a nested key so consumers never have to
            # derive it themselves; the factory hands each engine ONLY its own
            # namespace at run time.
            engine_params = {
                ns: dict(settings)
                for ns, settings in (self.execution.get("engine_params") or {}).items()
            }
            for dim_name, value in numeric_params.items():
                if "." in dim_name:
                    ns, param = dim_name.split(".", 1)
                    engine_params.setdefault(ns, {})[param] = value
            if engine_params:
                numeric_params["engine_params"] = engine_params

            # D. Store the Numeric/Literal parameters under the Symbolic Key
            self.scenario_config[key_str] = numeric_params
    
    def get_full_config(self) -> Dict[str, Any]:
        """Returns the full parsed configuration."""
        return self._raw_config