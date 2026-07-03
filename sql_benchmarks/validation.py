"""Single source of truth for experiment-config validation.

Called at BOTH surfaces that accept experiment configs:
  - API submission: sql_benchmarks/api/routers/experiments.py::submit_experiment
  - Executor entry: sql_benchmarks/config_loader.py::ConfigLoader._load_and_validate
    (also invoked indirectly via sql_benchmarks/coordinator.py::run)

Guarantees: if this passes, ConfigLoader will construct without semantic errors.
Any config the executor would later reject is rejected at submission instead.

Raises plain ValueError on failure — the same exception shape ExperimentValidator
has always used, so `except ValueError` handlers work unchanged.
"""
from .validator import ExperimentValidator


def validate_experiment_config(config: dict, source_label: str = "config") -> None:
    """Full validation of an experiment config dict. Raises ValueError on any failure.

    Layers:
      1. ExperimentValidator: schema, foreign keys, weights, numeric range checks.
      2. Matrix presence: `execution.matrix` must exist (was ConfigLoader-only).
      3. Alias resolvability: matrix string values must resolve through
         `definitions.<dim>` when a definition block exists (was ConfigLoader-only).
    """
    ExperimentValidator.validate(config, source_label)
    _check_matrix_present(config, source_label)
    _check_matrix_aliases_resolvable(config, source_label)


def _check_matrix_present(config: dict, source_label: str) -> None:
    execution = config.get("execution") or {}
    if "matrix" not in execution:
        raise ValueError(
            f"SEMANTIC ERROR in {source_label}: "
            "Experiment must define a 'matrix' strictly under 'execution.matrix'."
        )


def _check_matrix_aliases_resolvable(config: dict, source_label: str) -> None:
    """For each string value in the matrix, if the corresponding
    `definitions.<dim>` block exists, the value must be a key in it.
    Mirrors the strict check in ConfigLoader._compile_scenario_config."""
    execution = config.get("execution") or {}
    matrix = execution.get("matrix") or {}
    definitions = config.get("definitions") or {}
    for dim_name, values in matrix.items():
        definition_map = definitions.get(dim_name)
        if not isinstance(definition_map, dict) or not definition_map:
            continue
        for value in values or []:
            if isinstance(value, str) and value not in definition_map:
                raise ValueError(
                    f"SEMANTIC ERROR in {source_label}: "
                    f"Alias '{value}' in matrix dimension '{dim_name}' could not "
                    f"be resolved. Definition block 'definitions.{dim_name}' exists "
                    "but is missing this alias."
                )
