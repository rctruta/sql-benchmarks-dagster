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
      4. Table rows must be aliases, not literals. See _check_table_rows_are_aliases.
    """
    ExperimentValidator.validate(config, source_label)
    _check_matrix_present(config, source_label)
    _check_matrix_aliases_resolvable(config, source_label)
    _check_table_rows_are_aliases(config, source_label)


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


def _check_table_rows_are_aliases(config: dict, source_label: str) -> None:
    """`dataset.tables.<name>.rows` must be a string alias (referenced under
    `definitions.rows.<alias>`), not a literal integer.

    Why enforce this: aliases feed the Jinja substitution pipeline that turns
    `{{ <table>_table }}` in SQL into the concrete table name. Literal ints
    silently break the substitution — SQL comes out as `FROM ` (empty), and
    the executor dies with a downstream Parser Error that the agent has no
    way to attribute to the literal-rows footgun. Rather than fix the
    pipeline to handle literals, we enforce a single form: alias-only. See
    docs/AGENTS.md 'Experiment YAML essentials' and the annotated template.

    (This is the "one way to do it" principle: every accepted variation is
    another surface for the same bug to leak through somewhere else.)"""
    dataset = config.get("dataset") or {}
    tables = dataset.get("tables") or {}
    if not isinstance(tables, dict):
        return
    for name, tdef in tables.items():
        if not isinstance(tdef, dict):
            continue
        rows = tdef.get("rows")
        if rows is None:
            continue
        if isinstance(rows, int) and not isinstance(rows, bool):
            raise ValueError(
                f"SEMANTIC ERROR in {source_label}: "
                f"table '{name}' has literal 'rows: {rows}'. "
                f"Use an alias into definitions.rows instead — e.g. "
                f"'rows: my_scale' with 'definitions.rows.my_scale: {rows}'. "
                f"Literals are rejected because they don't feed the SQL "
                f"template substitution pipeline correctly."
            )
