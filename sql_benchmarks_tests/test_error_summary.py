"""Tests for the failure-marker enrichment helpers in coordinator.py.

Load-bearing contract these tests defend:
  - the agent's `/status` `detail` becomes actionable (carries the real
    executor error) instead of the useless generic "subprocess returned
    non-zero exit code" it produced before this change.
"""
from sql_benchmarks.coordinator import _extract_error_summary, _tail_lines


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
