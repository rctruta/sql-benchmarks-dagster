import pytest
from sql_benchmarks.utils.semantic_auditor import SemanticAuditor

def test_auditor_pass():
    auditor = SemanticAuditor()
    fragment = {
        "metrics": {"duration_seconds": 1.5, "total_count": 100},
        "parameters": {"avg_value": 10}
    }
    report = auditor.audit_fragment(fragment)
    assert report["success"] is True
    assert len(report["violations"]) == 0

def test_auditor_fail_negative_duration():
    auditor = SemanticAuditor()
    fragment = {
        "metrics": {"duration_seconds": -0.5},
        "parameters": {}
    }
    report = auditor.audit_fragment(fragment)
    assert report["success"] is False
    assert "Negative duration detected" in report["violations"][0]

def test_auditor_fail_registry_constraint():
    auditor = SemanticAuditor()
    fragment = {
        "metrics": {"duration_seconds": 1.0, "total_count": -1},
        "parameters": {}
    }
    report = auditor.audit_fragment(fragment)
    assert report["success"] is False
    assert "total_count is below minimum" in report["violations"][0]
