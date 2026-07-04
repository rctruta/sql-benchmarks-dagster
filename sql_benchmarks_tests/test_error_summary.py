"""Tests for the failure-marker enrichment helpers in coordinator.py.

Load-bearing contract these tests defend:
  - the agent's `/status` `detail` becomes actionable (carries the real
    executor error) instead of the useless generic "subprocess returned
    non-zero exit code" it produced before this change.
  - in multi-engine runs, the failing engine is named — `[duckdb] Parser
    Error ...` — so the agent can attribute the failure without guessing.
"""
from sql_benchmarks.coordinator import (
    _extract_error_summary,
    _extract_failing_engine,
    _tail_lines,
)


# ---------------------------------------------------------------------------
# _extract_error_summary
# ---------------------------------------------------------------------------

def test_finds_catalog_error_from_real_dagster_log():
    """The specific failure the agent hit during the live-fire smoke run.
    Dagster prints a lot before and after the actual DB error; the helper
    must dig it out."""
    log = """
    2026-07-03 15:30:59 - dagster - DEBUG - benchmark_job - RUN_START
    [SDK] Executing job 'benchmark_job' with partition='100'...
    [SDK] Exception during execution: Catalog Error: Table with name c does not exist!
    Did you mean "pg_class"?
    dagster._core.errors.DagsterExecutionStepExecutionError: Error occurred while executing op
    """
    summary = _extract_error_summary(log)
    # Should NOT be the last Dagster INFO line — should be the load-bearing one.
    assert "Table with name c does not exist" in summary


def test_finds_python_exception():
    log = """
    Loading config...
    Traceback (most recent call last):
      File "execute_run.py", line 42, in <module>
        raise ValueError("matrix missing")
    ValueError: matrix missing
    """
    summary = _extract_error_summary(log)
    assert "ValueError" in summary
    assert "matrix missing" in summary


def test_finds_failure_tag():
    log = """
    Starting run
    [FAILURE] Something specific went wrong here
    """
    summary = _extract_error_summary(log)
    assert "[FAILURE] Something specific went wrong here" in summary


def test_falls_back_to_last_line_when_no_marker():
    """If nothing looks like an error but the process failed anyway, use
    the last non-blank line — better than a generic 'no output' message."""
    log = "  first line\nsecond line\nthird line  \n\n"
    summary = _extract_error_summary(log)
    assert summary == "third line"


def test_empty_output_produces_diagnostic_string():
    assert _extract_error_summary("") == "subprocess produced no output"
    assert _extract_error_summary("   \n  \n") == "subprocess produced no output"


def test_prefers_last_matching_marker_when_multiple():
    """Two errors in the output — the later one is what actually killed
    the run. Walk from the end."""
    log = """
    Error: an early error that recovered
    ...more output...
    Catalog Error: THIS is the one that killed it
    """
    summary = _extract_error_summary(log)
    assert "THIS is the one" in summary


# ---------------------------------------------------------------------------
# _tail_lines
# ---------------------------------------------------------------------------

def test_tail_returns_last_n_lines():
    text = "\n".join(f"line {i}" for i in range(100))
    tail = _tail_lines(text, n=10)
    assert tail.startswith("line 90")
    assert tail.endswith("line 99")
    assert tail.count("\n") == 9  # 10 lines = 9 separators


def test_tail_returns_all_when_shorter_than_n():
    text = "a\nb\nc"
    assert _tail_lines(text, n=100) == "a\nb\nc"


def test_tail_of_empty_string():
    assert _tail_lines("", n=50) == ""
    assert _tail_lines(None, n=50) == ""


# ---------------------------------------------------------------------------
# _extract_failing_engine  (Gap 5)
# ---------------------------------------------------------------------------

def test_engine_extracted_from_duckdb_op_name():
    """The exact pattern the 2026-07-03 v5 live-fire produced: DuckDB was
    the failing engine but the bare 'Parser Error' didn't name it. The op
    name in Dagster's error wrapper is where the engine lives."""
    log = """
    dagster._core.errors.DagsterExecutionStepExecutionError: Error occurred
    while executing op "e_155eddf8__duckdb_benchmark_analytical_wall":
    _duckdb.ParserException: Parser Error: syntax error at or near "GROUP"
    """
    assert _extract_failing_engine(log) == "duckdb"


def test_engine_extracted_from_postgres_asset_prefix():
    """Postgres uses the asymmetric asset prefix `pg_` (per
    utils/common.py::get_engine_asset_prefix). The extractor must invert
    that so agents see the engine name, not the prefix."""
    log = 'Error occurred while executing op "e_abcd1234__pg_benchmark_selectivity"'
    assert _extract_failing_engine(log) == "postgres"


def test_engine_extracted_from_quack_pushdown_prefix():
    """Multi-underscore engine names (like quack_pushdown) must round-trip
    correctly through the non-greedy regex."""
    log = 'Error occurred while executing op "e_deadbeef__quack_pushdown_benchmark_tpch"'
    assert _extract_failing_engine(log) == "quack_pushdown"


def test_last_failing_engine_wins_when_multiple():
    """A multi-engine run may log several op errors as Dagster tears the
    step down. The engine we care about is the one that actually killed
    the run — walk from the end."""
    log = """
    Error occurred while executing op "e_abcd1234__duckdb_benchmark_selectivity"
    ...more output between failures...
    Error occurred while executing op "e_abcd1234__pg_benchmark_selectivity"
    """
    assert _extract_failing_engine(log) == "postgres"


def test_no_engine_when_no_op_pattern():
    """If the traceback doesn't contain a Dagster op-name (e.g., a purely
    Python-level exception before any op ran), return None so the caller
    can fall back to the raw error line without a bogus prefix."""
    log = "ValueError: matrix missing\nTraceback (most recent call last):\n..."
    assert _extract_failing_engine(log) is None


def test_no_engine_on_empty_input():
    assert _extract_failing_engine("") is None
    assert _extract_failing_engine(None) is None


def test_engine_extraction_ignores_op_names_without_benchmark_segment():
    """Only benchmark ops carry the engine prefix. Non-benchmark ops (e.g.,
    the `performance_dashboard` reporting step) don't match the pattern
    and shouldn't produce a false positive."""
    log = 'Error occurred while executing op "e_abcd1234__performance_dashboard"'
    assert _extract_failing_engine(log) is None
