"""Tests for the scaling-law analysis (sql_benchmarks.utils.scaling)."""
import json
import os

from sql_benchmarks.utils import scaling


def test_power_law_recovers_known_exponent():
    # t = 2 * N^0.5 exactly → alpha must be 0.5, R^2 = 1
    pts = {100: 2 * 100 ** 0.5, 10000: 2 * 10000 ** 0.5, 1000000: 2 * 1000000 ** 0.5}
    alpha, r2 = scaling.power_law(pts)
    assert abs(alpha - 0.5) < 1e-9
    assert abs(r2 - 1.0) < 1e-9


def test_regime_labels():
    assert scaling.regime(0.05) == "near-constant"
    assert scaling.regime(0.30) == "sublinear"
    assert scaling.regime(0.51) == "~O(sqrt N)"
    assert scaling.regime(1.0) == "~linear"
    assert scaling.regime(1.5) == "superlinear"


def _frag(eid, engine, rows, durations):
    return {
        "meta": {"experiment_id": eid, "engine": engine, "asset": "a"},
        "metrics": {"duration_seconds": sum(durations) / len(durations), "durations_raw": durations},
        "parameters": {"rows": rows},
    }


def _write(results_dir, eid, name, payload):
    d = os.path.join(results_dir, eid, "fragments")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        json.dump(payload, f)


def test_analyze_capsule_from_fragments(tmp_path):
    rd = str(tmp_path)
    eid = "scaletest"
    # duckdb: near-flat ; quack: steep
    _write(rd, eid, "d_small.json", _frag(eid, "duckdb", 1000, [0.010, 0.011]))
    _write(rd, eid, "d_large.json", _frag(eid, "duckdb", 1000000, [0.020, 0.022]))
    _write(rd, eid, "q_small.json", _frag(eid, "quack", 1000, [0.010, 0.010]))
    _write(rd, eid, "q_large.json", _frag(eid, "quack", 1000000, [0.300, 0.320]))

    report = scaling.analyze_capsule(rd, eid)
    assert set(report) == {"duckdb", "quack"}
    # quack must scale with a larger exponent than duckdb
    assert report["quack"]["alpha"] > report["duckdb"]["alpha"]
    assert report["duckdb"]["n_points"] == 2


def test_analyze_capsule_none_without_row_axis(tmp_path):
    """Experiments keyed on scale_factor (no 'rows') yield no scaling report."""
    rd = str(tmp_path)
    eid = "tpch_like"
    payload = {
        "meta": {"experiment_id": eid, "engine": "duckdb", "asset": "a"},
        "metrics": {"duration_seconds": 1.0, "durations_raw": [1.0]},
        "parameters": {"scale_factor": 0.1},
    }
    _write(rd, eid, "f1.json", payload)
    assert scaling.analyze_capsule(rd, eid) is None


def test_dnf_fragments_excluded(tmp_path):
    rd = str(tmp_path)
    eid = "withdnf"
    _write(rd, eid, "ok1.json", _frag(eid, "duckdb", 1000, [0.01]))
    _write(rd, eid, "ok2.json", _frag(eid, "duckdb", 1000000, [0.02]))
    dnf = {"meta": {"experiment_id": eid, "engine": "quack", "asset": "a"},
           "metrics": {"duration_seconds": None, "durations_raw": [], "dnf": True},
           "parameters": {"rows": 1000}}
    _write(rd, eid, "dnf.json", dnf)
    report = scaling.analyze_capsule(rd, eid)
    assert "quack" not in report  # single DNF point, no fit
    assert "duckdb" in report
