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
      5. Memory limits must fit the host. See _check_memory_limits_fit_host.
      6. Query files must bind to the dataset via Jinja table placeholders —
         the placeholder is the DAG edge. See _check_query_placeholders_bind.
    """
    ExperimentValidator.validate(config, source_label)
    _check_matrix_present(config, source_label)
    _check_matrix_aliases_resolvable(config, source_label)
    _check_table_rows_are_aliases(config, source_label)
    _check_memory_limits_fit_host(config, source_label)
    _check_query_placeholders_bind(config, source_label)


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


# --- Query/pipeline binding guard (fail-closed) -------------------------------
#
# Observed live 2026-07-15 (malloy engine bring-up): a dialect file that
# hardcoded the table name instead of using {{ <table>_table }} didn't just
# render wrong — the Jinja placeholder IS the dependency edge
# (get_tables_used_in_sql derives asset deps from it), so the benchmark asset
# silently detached from ingestion, ran first, and aborted the job. The DAG
# was structurally wrong and nothing said so until runtime. Placeholder
# binding is a compile-time property; enforce it at the validation choke
# point instead of relying on the implicit convention.


def _check_query_placeholders_bind(config: dict, source_label: str) -> None:
    """Every query file of every configured engine's dialect must bind to the
    dataset through Jinja table placeholders. Three failure modes, all
    rejected before anything runs:

      1. Engine dialect directory missing or empty → the factory would
         silently drop the engine from the benchmark (`continue`).
      2. Query file with NO `{{ <table>_table }}` placeholder → the asset
         would have no dependency edge on ingestion (the live failure).
      3. Placeholder referencing a table not in `dataset.tables` → would
         render empty/undefined at runtime.
    """
    import glob
    import os

    import jinja2
    import jinja2.meta

    from .utils.common import get_engine_sql_dialect, get_target_sql_dir

    execution = config.get("execution") or {}
    engines = execution.get("engines") or []
    tables = set(((config.get("dataset") or {}).get("tables") or {}).keys())
    # No suite declared = nothing to bind (loader-only configs in unit tests);
    # a declared suite is validated strictly.
    if not execution.get("test_suite") or not engines or not tables:
        return

    target_dir = get_target_sql_dir(config)
    env = jinja2.Environment()

    for engine in engines:
        dialect_dir = os.path.join(target_dir, get_engine_sql_dialect(engine))
        query_files = sorted(
            glob.glob(os.path.join(dialect_dir, "*.sql"))
            + glob.glob(os.path.join(dialect_dir, "*.malloy"))
        )
        query_files = [f for f in query_files if os.path.getsize(f) > 0]
        if not query_files:
            raise ValueError(
                f"SEMANTIC ERROR in {source_label}: engine '{engine}' has no "
                f"query files under '{dialect_dir}'. The benchmark factory "
                f"would silently drop this engine from the run. Add the "
                f"dialect's query files or remove the engine."
            )
        for path in query_files:
            with open(path, "r") as fh:
                raw = fh.read()
            try:
                ast = env.parse(raw)
            except jinja2.TemplateSyntaxError as e:
                raise ValueError(
                    f"SEMANTIC ERROR in {source_label}: query file '{path}' "
                    f"is not a valid Jinja template: {e}"
                )
            placeholders = jinja2.meta.find_undeclared_variables(ast)
            table_refs = {v[: -len("_table")] for v in placeholders
                          if v.endswith("_table")}
            unknown = table_refs - tables
            if unknown:
                raise ValueError(
                    f"SEMANTIC ERROR in {source_label}: query file '{path}' "
                    f"references {sorted(unknown)} via '_table' placeholders, "
                    f"but dataset.tables defines only {sorted(tables)}."
                )
            if not table_refs:
                raise ValueError(
                    f"SEMANTIC ERROR in {source_label}: query file '{path}' "
                    f"uses no '{{{{ <table>_table }}}}' placeholder. The "
                    f"placeholder is the dependency edge to ingestion — "
                    f"without it the benchmark asset detaches from the data "
                    f"pipeline and runs against nothing (observed live, "
                    f"malloy 2026-07-15). Reference one of: "
                    + ", ".join(f"{{{{ {t}_table }}}}" for t in sorted(tables))
                )


# --- Host-memory guard (fail-closed) -----------------------------------------
#
# Observed live 2026-07-06: an agent-built sort_spill config swept
# `duckdb.memory_limit: [512MB, 16GB]` on a 16GB machine. DuckDB takes the
# memory it is granted; the 16GB lane froze the host (hard freeze, not a
# clean OOM). No OS-level sandbox exists (harness-tenets gap), so the
# validation surface — the single choke point every submission passes
# through — is where the lab fails closed.
#
# Rule: any engine memory-limit value (matrix lane or engine_params) above
# MEMORY_CAP_FRACTION of physical RAM is rejected at submission with an
# explicit override (`meta.allow_high_memory: true`) for machines/operators
# that know what they're doing.

MEMORY_CAP_FRACTION = 0.5

_MEMORY_UNIT_BYTES = {
    "kb": 1024, "kib": 1024,
    "mb": 1024 ** 2, "mib": 1024 ** 2,
    "gb": 1024 ** 3, "gib": 1024 ** 3,
    "tb": 1024 ** 4, "tib": 1024 ** 4,
}


def _parse_memory_bytes(value) -> "int | None":
    """'512MB' / '16GB' / '1.5GiB' -> bytes. None if not a memory string."""
    import re
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]i?B)\s*", value, re.IGNORECASE)
    if not m:
        return None
    return int(float(m.group(1)) * _MEMORY_UNIT_BYTES[m.group(2).lower()])


def _host_memory_bytes() -> int:
    import os
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def _iter_memory_limit_values(config: dict):
    """Yield (path, value) for every engine memory-limit setting: matrix
    lanes like `execution.matrix.'duckdb.memory_limit'` and static
    `engine_params.<engine>.memory_limit`."""
    matrix = (config.get("execution") or {}).get("matrix") or {}
    for dim, values in matrix.items():
        if str(dim).endswith(".memory_limit"):
            for v in values or []:
                yield f"execution.matrix.{dim}", v
    engine_params = config.get("engine_params") or {}
    if isinstance(engine_params, dict):
        for engine, params in engine_params.items():
            if isinstance(params, dict) and "memory_limit" in params:
                yield f"engine_params.{engine}.memory_limit", params["memory_limit"]


def _check_memory_limits_fit_host(config: dict, source_label: str) -> None:
    meta = config.get("meta") or {}
    if meta.get("allow_high_memory") is True:
        return  # explicit operator override — on their head, loudly opted in
    host = _host_memory_bytes()
    cap = int(host * MEMORY_CAP_FRACTION)
    for path, value in _iter_memory_limit_values(config):
        limit = _parse_memory_bytes(value)
        if limit is not None and limit > cap:
            raise ValueError(
                f"SEMANTIC ERROR in {source_label}: {path} = '{value}' exceeds "
                f"{int(MEMORY_CAP_FRACTION * 100)}% of this host's physical RAM "
                f"({host / 1024**3:.0f}GB). Granting an engine that much memory "
                f"can freeze the machine (observed live). Use a value at or "
                f"below {cap / 1024**3:.0f}GB, or set 'meta.allow_high_memory: "
                f"true' if this host can genuinely afford it."
            )
