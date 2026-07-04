"""Tests for the granular projections (sql_benchmarks/api/logic/projections.py)
and their REST + CLI wrappers.

Same-code-path parity between Python function, REST endpoint, and CLI
subcommand is verified explicitly: each surface hits the identical
projection function, so a shape mismatch would fail one of these tests
first."""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sql_benchmarks.api.app import create_app
from sql_benchmarks.api.data import reader as reader_module
from sql_benchmarks.api.data.reader import ResultReader
from sql_benchmarks.api.logic.projections import (
    get_experiment_summary,
    get_means_by_partition,
    get_replication_stability,
    get_scaling_factor,
)


EXP = "aabb1234"


def _write_fragment(results_dir, exp_id, asset, partition, engine, duration,
                    durations_raw=None):
    frag_dir = os.path.join(results_dir, exp_id, "fragments")
    os.makedirs(frag_dir, exist_ok=True)
    payload = {
        "meta": {
            "timestamp": "2026-07-04T00:00:00",
            "experiment_id": exp_id,
            "dagster_run_id": "run-x",
            "engine": engine,
            "asset": asset,
            "partition": partition,
        },
        "metrics": {
            "duration_seconds": duration,
            "replication_factor": 5,
            **({"durations_raw": durations_raw} if durations_raw is not None else {}),
        },
        "parameters": {"rows": 1000},
    }
    with open(os.path.join(frag_dir, f"{asset}__{partition}.json"), "w") as f:
        json.dump(payload, f)


@pytest.fixture
def three_scale_lab(tmp_path, monkeypatch):
    """Small three-scale experiment: duckdb+postgres × small/medium/large."""
    results_dir = str(tmp_path / "results")
    experiments_dir = str(tmp_path / "experiments")
    config_archive = os.path.join(experiments_dir, "configs")
    os.makedirs(config_archive, exist_ok=True)

    # duckdb: linear 10x scaling
    _write_fragment(results_dir, EXP, "duckdb_analytical", "small",  "duckdb", 0.010,
                    durations_raw=[0.009, 0.010, 0.011])
    _write_fragment(results_dir, EXP, "duckdb_analytical", "medium", "duckdb", 0.100,
                    durations_raw=[0.098, 0.100, 0.102])
    _write_fragment(results_dir, EXP, "duckdb_analytical", "large",  "duckdb", 1.000,
                    durations_raw=[0.980, 1.000, 1.020])
    # postgres: linear 5x scaling
    _write_fragment(results_dir, EXP, "pg_analytical", "small",  "postgres", 0.050,
                    durations_raw=[0.048, 0.050, 0.052])
    _write_fragment(results_dir, EXP, "pg_analytical", "medium", "postgres", 0.250,
                    durations_raw=[0.240, 0.250, 0.260])
    _write_fragment(results_dir, EXP, "pg_analytical", "large",  "postgres", 1.250,
                    durations_raw=[1.200, 1.250, 1.300])

    with open(os.path.join(results_dir, EXP, f"metadata_{EXP}.json"), "w") as f:
        json.dump({"experiment_id": EXP, "timestamp": 1760000000.0}, f)
    import yaml
    with open(os.path.join(config_archive, f"config_{EXP}.yaml"), "w") as f:
        yaml.dump({"execution": {"test_suite": "analytical_wall"}}, f)
    with open(os.path.join(results_dir, EXP, f"{EXP}.csv"), "w") as f:
        f.write("engine,duration\n")

    monkeypatch.setattr(reader_module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(reader_module, "EXPERIMENTS_DIR", experiments_dir)
    monkeypatch.setattr(reader_module, "CONFIG_ARCHIVE_DIR", config_archive)
    return {"results": results_dir, "experiments": experiments_dir, "configs": config_archive}


# ---------------------------------------------------------------------------
# Python function surface (the core layer)
# ---------------------------------------------------------------------------

def test_get_means_by_partition_returns_mean_and_sample_count(three_scale_lab):
    result = get_means_by_partition(EXP, ResultReader())
    assert result["experiment_id"] == EXP
    # Alphabetic partition order — matches existing lab convention
    assert list(result["partitions"].keys()) == ["large", "medium", "small"]
    small = result["partitions"]["small"]
    assert small["duckdb"]["mean_duration_seconds"] == 0.010
    assert small["duckdb"]["sample_count"] == 1
    assert small["postgres"]["mean_duration_seconds"] == 0.050


def test_get_means_provenance_names_every_fragment(three_scale_lab):
    result = get_means_by_partition(EXP, ResultReader())
    prov = result["provenance"]
    assert prov["fragment_count"] == 6
    assert set(prov["fragment_keys"]) == {
        "duckdb_analytical__small", "duckdb_analytical__medium", "duckdb_analytical__large",
        "pg_analytical__small", "pg_analytical__medium", "pg_analytical__large",
    }
    assert "computed_at" in prov


def test_get_scaling_factor_computes_ratios_in_alpha_order(three_scale_lab):
    """The synthetic data has partitions large=1.0, medium=0.1, small=0.01
    for duckdb — in alphabetic order (large,medium,small) that's a
    DECREASING series with ratios 0.1, 0.1. Overall ratio: 0.01."""
    result = get_scaling_factor(EXP, ResultReader())
    duckdb = result["engines"]["duckdb"]
    assert duckdb["partitions_order"] == ["large", "medium", "small"]
    assert duckdb["mean_durations"] == [1.0, 0.1, 0.01]
    assert duckdb["adjacent_ratios"] == [0.1, 0.1]
    assert duckdb["overall_ratio"] == 0.01
    # And the tool must emit the ordering caveat so the caller can
    # reinterpret when semantic order differs
    assert "alphabetically" in result["note"].lower()


def test_get_replication_stability_uses_durations_raw(three_scale_lab):
    result = get_replication_stability(EXP, ResultReader())
    small_duckdb = result["partitions"]["small"]["duckdb"]
    assert small_duckdb["sample_count"] == 3
    assert small_duckdb["min_duration_seconds"] == 0.009
    assert small_duckdb["max_duration_seconds"] == 0.011
    assert small_duckdb["std_duration_seconds"] > 0
    assert small_duckdb["coefficient_of_variation"] is not None


def test_get_replication_stability_falls_back_when_raw_missing(tmp_path, monkeypatch):
    """Older fragments (no `durations_raw`) get sample_count=1 and std=0
    — the machine-readable signal that stability isn't measurable from
    what was stored."""
    results_dir = str(tmp_path / "results")
    experiments_dir = str(tmp_path / "experiments")
    config_archive = os.path.join(experiments_dir, "configs")
    os.makedirs(config_archive, exist_ok=True)
    _write_fragment(results_dir, EXP, "asset", "only", "duckdb", 0.5)  # no durations_raw
    with open(os.path.join(results_dir, EXP, f"metadata_{EXP}.json"), "w") as f:
        json.dump({"experiment_id": EXP, "timestamp": 1760000000.0}, f)
    import yaml
    with open(os.path.join(config_archive, f"config_{EXP}.yaml"), "w") as f:
        yaml.dump({"execution": {"test_suite": "x"}}, f)
    monkeypatch.setattr(reader_module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(reader_module, "EXPERIMENTS_DIR", experiments_dir)
    monkeypatch.setattr(reader_module, "CONFIG_ARCHIVE_DIR", config_archive)

    result = get_replication_stability(EXP, ResultReader())
    only = result["partitions"]["only"]["duckdb"]
    assert only["sample_count"] == 1
    assert only["std_duration_seconds"] == 0.0


def test_get_experiment_summary_includes_narrative_and_machine_readable(three_scale_lab):
    result = get_experiment_summary(EXP, ResultReader())
    assert result["experiment_id"] == EXP
    assert result["suite"] == "analytical_wall"
    assert sorted(result["engines"]) == ["duckdb", "postgres"]
    assert result["partitions"] == ["large", "medium", "small"]
    # Prose narrative for humans
    assert "duckdb" in result["narrative"]
    assert "postgres" in result["narrative"]
    assert "scaling" in result["narrative"]
    # Machine-readable structure preserved
    assert result["means"]["small"]["duckdb"]["mean_duration_seconds"] == 0.010
    assert "overall_ratio" in result["scaling"]["duckdb"]


# ---------------------------------------------------------------------------
# REST surface — must hit the same code path as the Python function
# ---------------------------------------------------------------------------

@pytest.fixture
def rest_client(three_scale_lab):
    return TestClient(create_app())


def test_rest_projection_means_matches_python(rest_client):
    py = get_means_by_partition(EXP, ResultReader())
    rest = rest_client.get(f"/v1/results/{EXP}/projections/means").json()
    # `computed_at` will differ by microseconds between the two calls
    py.pop("provenance", None)["computed_at"] if False else None
    py["provenance"].pop("computed_at")
    rest["provenance"].pop("computed_at")
    assert py == rest


def test_rest_projection_scaling_matches_python(rest_client):
    py = get_scaling_factor(EXP, ResultReader())
    rest = rest_client.get(f"/v1/results/{EXP}/projections/scaling").json()
    py["provenance"].pop("computed_at")
    rest["provenance"].pop("computed_at")
    assert py == rest


def test_rest_projection_stability_matches_python(rest_client):
    py = get_replication_stability(EXP, ResultReader())
    rest = rest_client.get(f"/v1/results/{EXP}/projections/stability").json()
    py["provenance"].pop("computed_at")
    rest["provenance"].pop("computed_at")
    assert py == rest


def test_rest_projection_summary_matches_python(rest_client):
    py = get_experiment_summary(EXP, ResultReader())
    rest = rest_client.get(f"/v1/results/{EXP}/projections/summary").json()
    py["provenance"].pop("computed_at")
    rest["provenance"].pop("computed_at")
    assert py == rest


def test_rest_projection_404_on_missing_experiment(rest_client):
    for path in ("means", "scaling", "stability", "summary"):
        resp = rest_client.get(f"/v1/results/deadbeef/projections/{path}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CLI surface — same code path via the `sqlbench project` subcommand
# ---------------------------------------------------------------------------

def test_cli_project_dispatches_to_python_function(three_scale_lab, capsys):
    """CLI must produce byte-identical JSON to the Python function (modulo
    `computed_at`). Verified in-process to avoid subprocess startup cost."""
    from sql_benchmarks import cli

    py = get_means_by_partition(EXP, ResultReader())

    with patch.object(sys, "argv", ["sqlbench", "project", "means", EXP]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    cli_result = json.loads(out)
    py["provenance"].pop("computed_at")
    cli_result["provenance"].pop("computed_at")
    assert cli_result == py


def test_cli_project_rejects_unknown_projection(three_scale_lab, capsys):
    from sql_benchmarks import cli

    with patch.object(sys, "argv", ["sqlbench", "project", "bogus", EXP]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
    # argparse rejects at parse time with code 2
    assert exc_info.value.code == 2


def test_cli_project_returns_error_for_missing_experiment(three_scale_lab, capsys):
    from sql_benchmarks import cli

    with patch.object(sys, "argv", ["sqlbench", "project", "means", "deadbeef"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "not found" in err


def test_cli_legacy_positional_invocation_still_dispatches_to_run(monkeypatch):
    """`sqlbench <target>` (no subcommand) must still route to _cmd_run —
    this is what `./run.sh` depends on."""
    from sql_benchmarks import cli

    calls = []
    monkeypatch.setattr(cli, "_cmd_run", lambda target, auto: calls.append((target, auto)) or 0)
    with patch.object(sys, "argv", ["sqlbench", "queue", "--auto"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
    assert exc_info.value.code == 0
    assert calls == [("queue", True)]
