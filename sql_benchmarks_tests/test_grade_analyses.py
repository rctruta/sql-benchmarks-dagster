"""Tests for the answer-correctness grader (scripts/tools/grade_analyses.py).

The grader is the truth layer over the behavioral markers: it checks the
numbers an agent PUBLISHED against the sealed fragments, deterministically.
"""
import importlib.util
import json
import os

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "grade_analyses", os.path.join(_REPO_ROOT, "scripts", "tools", "grade_analyses.py"))
grade_analyses = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade_analyses)


EXP = "feed0001"


@pytest.fixture
def capsule(tmp_path, monkeypatch):
    """Synthetic sealed capsule: one engine, two partitions.
    small mean = 10.0 ms, large mean = 100.0 ms (ratio 10x)."""
    frag_dir = tmp_path / EXP / "fragments"
    frag_dir.mkdir(parents=True)
    for part, raws in (("small", [0.009, 0.010, 0.011]),
                       ("large", [0.099, 0.100, 0.101])):
        (frag_dir / f"e_{EXP}__duckdb__{part}.json").write_text(json.dumps({
            "meta": {"engine": "duckdb", "partition": part,
                     "experiment_id": EXP, "timestamp": "t",
                     "dagster_run_id": "r", "asset": "a"},
            "metrics": {"duration_seconds": sum(raws) / len(raws),
                        "durations_raw": raws, "replication_factor": 3},
        }))
    monkeypatch.setattr(grade_analyses, "RESULTS_DIR", str(tmp_path))
    return tmp_path


def _trace(tmp_path, answer):
    p = tmp_path / "run.jsonl"
    lines = [
        {"event": "run_start", "goal": "g", "model": "m"},
        {"event": "tool_call", "name": "get_experiment_summary",
         "arguments": {"experiment_id": EXP}},
        {"event": "final_answer", "turn": 5, "content": answer},
    ]
    p.write_text("\n".join(json.dumps(l) for l in lines))
    return str(p)


def test_pass_when_all_means_stated_correctly(capsule, tmp_path):
    g = grade_analyses.grade(_trace(
        tmp_path, "small: 10.0 ms, large: 100.0 ms — that's 10x for 10x rows, linear."))
    assert g["verdict"] == "PASS"
    assert g["coverage"] == 1.0
    assert g["ratio_matched"] >= 1


def test_fail_when_a_mean_is_misstated(capsule, tmp_path):
    """The core integrity check: a wrong number (42 ms where truth is
    100 ms) must FAIL — coverage drops because large/duckdb is never
    stated correctly."""
    g = grade_analyses.grade(_trace(
        tmp_path, "small: 10.0 ms, large: 42.0 ms."))
    assert g["verdict"] == "FAIL"
    assert "large/duckdb" in g["missing_means"]
    assert 42.0 in g["unmatched_claims_ms"]


def test_partial_when_extra_unverifiable_claim(capsule, tmp_path):
    """All means right + one number that matches nothing derivable
    (e.g. an extrapolation) -> PARTIAL, claim listed verbatim."""
    g = grade_analyses.grade(_trace(
        tmp_path, "small: 10.0 ms, large: 100.0 ms. Projected 100M rows: 950.0 ms."))
    assert g["verdict"] == "PARTIAL"
    assert g["coverage"] == 1.0
    assert 950.0 in g["unmatched_claims_ms"]


def test_tolerance_accepts_rounding(capsule, tmp_path):
    """Agents round: 9.99 ms for a 10.0 ms truth is within 2%."""
    g = grade_analyses.grade(_trace(
        tmp_path, "small: 9.99 ms, large: 100.4 ms."))
    assert g["verdict"] == "PASS"


def test_latex_notation_extracted(capsule, tmp_path):
    r"""gemini-3.5-flash writes $10.0\text{ ms}$ and $10\times$ — both
    must be extracted (was a FAIL false-negative before the fix)."""
    g = grade_analyses.grade(_trace(
        tmp_path,
        r"small is $10.0\text{ ms}$ and large is $100.0\text{ ms}$ — $10\times$ growth."))
    assert g["verdict"] == "PASS"
    assert g["ratio_matched"] >= 1


def test_seconds_normalized_to_ms(capsule, tmp_path):
    g = grade_analyses.grade(_trace(
        tmp_path, "small: 0.010 seconds, large: 0.100 seconds."))
    assert g["verdict"] == "PASS"


def test_no_capsule_reports_gap_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(grade_analyses, "RESULTS_DIR", str(tmp_path / "nowhere"))
    g = grade_analyses.grade(_trace(tmp_path, "small: 10 ms"))
    assert g["verdict"] == "NO-CAPSULE"


def test_ungradeable_trace_returns_none(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text(json.dumps({"event": "run_start", "goal": "g"}))
    assert grade_analyses.grade(str(p)) is None
