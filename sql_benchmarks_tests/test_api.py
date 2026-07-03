"""
Tests for the REST API layer (sql_benchmarks/api).

All filesystem-backed readers are pointed at tmp_path fixtures via monkeypatch;
no real experiments are run and no real results are touched.
"""
import json
import os
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from sql_benchmarks.api.app import create_app
from sql_benchmarks.api.data import catalog_reader as catalog_reader_module
from sql_benchmarks.api.data import reader as reader_module
from sql_benchmarks.api.logic.ranker import score_engines
from sql_benchmarks.api.models.results import Fragment, FragmentMeta, FragmentMetrics
from sql_benchmarks.api.routers import experiments as experiments_router

EXP_ID = "abc12345"


# ---------------------------------------------------------------------------
# Fixtures: fake results tree + fake SQL catalog, all under tmp_path
# ---------------------------------------------------------------------------

def write_fragment(results_dir, exp_id, asset, partition, engine, duration):
    frag_dir = os.path.join(results_dir, exp_id, "fragments")
    os.makedirs(frag_dir, exist_ok=True)
    payload = {
        "meta": {
            "timestamp": "2026-06-10T12:00:00",
            "experiment_id": exp_id,
            "dagster_run_id": "run123",
            "engine": engine,
            "asset": asset,
            "partition": partition,
        },
        "metrics": {"duration_seconds": duration, "replication_factor": 3},
        "parameters": {"rows": 1000},
    }
    path = os.path.join(frag_dir, f"{asset}__{partition}.json")
    with open(path, "w") as f:
        json.dump(payload, f)


@pytest.fixture
def fake_lab(tmp_path, monkeypatch):
    """A minimal on-disk lab: one finished experiment with two engines."""
    results_dir = str(tmp_path / "results")
    experiments_dir = str(tmp_path / "experiments")
    config_archive = os.path.join(experiments_dir, "configs")
    os.makedirs(config_archive, exist_ok=True)
    os.makedirs(os.path.join(experiments_dir, "queue"), exist_ok=True)

    # Fragments: duckdb faster than postgres on both partitions
    write_fragment(results_dir, EXP_ID, "duckdb_benchmark_q1", "small_ssd", "duckdb", 0.5)
    write_fragment(results_dir, EXP_ID, "duckdb_benchmark_q1", "large_ssd", "duckdb", 1.0)
    write_fragment(results_dir, EXP_ID, "pg_benchmark_q1", "small_ssd", "postgres", 2.0)
    write_fragment(results_dir, EXP_ID, "pg_benchmark_q1", "large_ssd", "postgres", 4.0)

    # Metadata + archived config (marks experiment complete)
    with open(os.path.join(results_dir, EXP_ID, f"metadata_{EXP_ID}.json"), "w") as f:
        json.dump({"experiment_id": EXP_ID, "timestamp": 1760000000.0}, f)
    with open(os.path.join(config_archive, f"config_{EXP_ID}.yaml"), "w") as f:
        yaml.dump({"execution": {"test_suite": "selectivity"}}, f)
    # CSV present, dashboard absent
    with open(os.path.join(results_dir, EXP_ID, f"{EXP_ID}.csv"), "w") as f:
        f.write("engine,duration\n")

    monkeypatch.setattr(reader_module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(reader_module, "EXPERIMENTS_DIR", experiments_dir)
    monkeypatch.setattr(reader_module, "CONFIG_ARCHIVE_DIR", config_archive)
    monkeypatch.setattr(experiments_router, "EXPERIMENTS_DIR", experiments_dir)
    monkeypatch.setattr(experiments_router, "CONFIG_ARCHIVE_DIR", config_archive)
    return {"results": results_dir, "experiments": experiments_dir, "configs": config_archive}


@pytest.fixture
def fake_catalog(tmp_path, monkeypatch):
    sql_dir = str(tmp_path / "sql")
    for engine in ("duckdb", "postgres"):
        d = os.path.join(sql_dir, "selectivity", engine)
        os.makedirs(d)
        with open(os.path.join(d, "q_scan.sql"), "w") as f:
            f.write("SELECT 1;")
    monkeypatch.setattr(catalog_reader_module, "SQL_DIR", sql_dir)
    return sql_dir


@pytest.fixture
def client(fake_lab, fake_catalog):
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Ranker (pure logic)
# ---------------------------------------------------------------------------

def make_fragment(engine, partition, duration):
    return Fragment(
        meta=FragmentMeta(
            timestamp="t", experiment_id=EXP_ID, dagster_run_id="r",
            engine=engine, asset="a", partition=partition,
        ),
        metrics=FragmentMetrics(duration_seconds=duration, replication_factor=1),
        parameters={},
    )


def test_score_engines_ranks_fastest_first():
    fragments = [
        make_fragment("postgres", "p1", 4.0),
        make_fragment("duckdb", "p1", 1.0),
        make_fragment("duckdb", "p2", 2.0),
    ]
    rankings = score_engines(fragments)
    assert [r.engine for r in rankings] == ["duckdb", "postgres"]
    assert rankings[0].rank == 1
    assert rankings[0].mean_duration_seconds == 1.5
    assert rankings[0].sample_count == 2


def test_score_engines_partition_filter():
    fragments = [
        make_fragment("duckdb", "small", 1.0),
        make_fragment("duckdb", "large", 9.0),
    ]
    rankings = score_engines(fragments, partition_filter="large")
    assert rankings[0].mean_duration_seconds == 9.0
    assert rankings[0].sample_count == 1


def test_score_engines_empty():
    assert score_engines([]) == []


# ---------------------------------------------------------------------------
# Catalog endpoints
# ---------------------------------------------------------------------------

def test_list_engines(client):
    """Quack variants (`quack`, `quack_pushdown`, `quack_adbc`, `quack_arrow`)
    share the DuckDB SQL dialect and inherit its suite list. Similarly,
    `postgres_transport` shares the Postgres dialect. The catalog reader
    must expand dialect-shared SQL to the full engine set."""
    resp = client.get("/v1/catalog/engines")
    assert resp.status_code == 200
    engines = {e["name"]: e["available_suites"] for e in resp.json()["engines"]}
    # Fake catalog wrote SQL under selectivity/duckdb and selectivity/postgres.
    # Every engine mapped to one of those dialects gets that suite listed.
    assert engines == {
        "duckdb": ["selectivity"],
        "quack": ["selectivity"],
        "quack_pushdown": ["selectivity"],
        "quack_adbc": ["selectivity"],
        "quack_arrow": ["selectivity"],
        "postgres": ["selectivity"],
        "postgres_transport": ["selectivity"],
    }


def test_list_suites_includes_sql_content(client):
    resp = client.get("/v1/catalog/suites")
    assert resp.status_code == 200
    suites = resp.json()["suites"]
    assert len(suites) == 1
    suite = suites[0]
    assert suite["name"] == "selectivity"
    assert suite["benchmark_names"] == ["q_scan"]
    # sql_content is keyed by engine name (agent-friendly). Engines sharing
    # a dialect get the same SQL back — an agent asking for `quack` SQL
    # gets the same text as one asking for `duckdb` SQL.
    assert suite["sql_content"]["duckdb"]["q_scan"] == "SELECT 1;"
    assert suite["sql_content"]["quack"]["q_scan"] == "SELECT 1;"
    assert suite["sql_content"]["quack_pushdown"]["q_scan"] == "SELECT 1;"
    assert set(suite["engines"]) >= {
        "duckdb", "postgres",
        "quack", "quack_pushdown", "quack_adbc", "quack_arrow",
        "postgres_transport",
    }


def test_list_templates_endpoint(client, tmp_path, monkeypatch):
    """/v1/catalog/templates surfaces curated files under experiments/{templates,queue}/."""
    from sql_benchmarks.api.data import templates_reader as tr
    exp_dir = tmp_path / "exp"
    (exp_dir / "queue").mkdir(parents=True)
    (exp_dir / "queue" / "example.yaml").write_text(
        'meta:\n  name: "Example template"\ndataset: {}\n'
    )
    monkeypatch.setattr(tr, "EXPERIMENTS_DIR", str(exp_dir))

    resp = client.get("/v1/catalog/templates")
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    names = [t["name"] for t in templates]
    assert "example" in names
    example = next(t for t in templates if t["name"] == "example")
    assert example["description"] == "Example template"


def test_get_template_returns_content(client, tmp_path, monkeypatch):
    from sql_benchmarks.api.data import templates_reader as tr
    exp_dir = tmp_path / "exp"
    (exp_dir / "queue").mkdir(parents=True)
    yaml_body = 'meta:\n  name: "Example template"\ndataset: {}\n'
    (exp_dir / "queue" / "example.yaml").write_text(yaml_body)
    monkeypatch.setattr(tr, "EXPERIMENTS_DIR", str(exp_dir))

    resp = client.get("/v1/catalog/templates/example")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "example"
    assert body["content"] == yaml_body


def test_get_template_404_for_missing(client, tmp_path, monkeypatch):
    from sql_benchmarks.api.data import templates_reader as tr
    exp_dir = tmp_path / "exp"
    (exp_dir / "queue").mkdir(parents=True)
    monkeypatch.setattr(tr, "EXPERIMENTS_DIR", str(exp_dir))

    resp = client.get("/v1/catalog/templates/nonexistent")
    assert resp.status_code == 404


def test_get_template_404_for_runtime_id(client, tmp_path, monkeypatch):
    """Even if a runtime-id file exists on disk, it's not exposed as a template."""
    from sql_benchmarks.api.data import templates_reader as tr
    exp_dir = tmp_path / "exp"
    (exp_dir / "queue").mkdir(parents=True)
    (exp_dir / "queue" / "abcd1234.yaml").write_text("dataset: {}\n")
    monkeypatch.setattr(tr, "EXPERIMENTS_DIR", str(exp_dir))

    resp = client.get("/v1/catalog/templates/abcd1234")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Results endpoints
# ---------------------------------------------------------------------------

def test_list_results(client):
    resp = client.get("/v1/results")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    summary = body["experiments"][0]
    assert summary["experiment_id"] == EXP_ID
    assert summary["suite"] == "selectivity"
    assert sorted(summary["engines"]) == ["duckdb", "postgres"]
    assert summary["partition_count"] == 2
    assert summary["fragment_count"] == 4
    assert summary["has_csv"] is True
    assert summary["has_dashboard"] is False


def test_list_results_engine_filter_excludes(client):
    resp = client.get("/v1/results", params={"engine": "actian"})
    assert resp.json()["total"] == 0


def test_get_result(client):
    resp = client.get(f"/v1/results/{EXP_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["experiment_id"] == EXP_ID
    assert body["config"]["execution"]["test_suite"] == "selectivity"
    assert len(body["fragments"]) == 4


def test_get_result_404(client):
    resp = client.get("/v1/results/deadbeef")
    assert resp.status_code == 404


def test_compare_ranks_engines(client):
    resp = client.get(f"/v1/results/{EXP_ID}/compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["winner"] == "duckdb"
    # duckdb mean 0.75 vs postgres mean 3.0 -> 4x
    assert body["speedup_vs_slowest"] == 4.0
    assert [r["rank"] for r in body["rankings"]] == [1, 2]


def test_compare_partition_filter(client):
    resp = client.get(f"/v1/results/{EXP_ID}/compare", params={"partition": "small_ssd"})
    body = resp.json()
    assert body["winner"] == "duckdb"
    assert body["rankings"][0]["mean_duration_seconds"] == 0.5


# ---------------------------------------------------------------------------
# Recommend endpoint
# ---------------------------------------------------------------------------

def test_recommend(client):
    resp = client.get("/v1/recommend", params={"suite": "selectivity"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_engine"] == "duckdb"
    assert EXP_ID in body["supporting_experiments"]
    assert "No data for 'actian'" in " ".join(body["caveats"])


def test_recommend_no_data(client):
    resp = client.get("/v1/recommend", params={"suite": "nonexistent"})
    body = resp.json()
    assert body["recommended_engine"] == "unknown"
    assert body["confidence"] == "low"


# ---------------------------------------------------------------------------
# Experiment submission & status
# ---------------------------------------------------------------------------

VALID_YAML = "meta:\n  name: test\nexecution:\n  test_suite: selectivity\n"


def test_submit_invalid_yaml_rejected(client):
    resp = client.post("/v1/experiments", json={"config_yaml": "a: [unclosed"})
    assert resp.status_code == 422
    assert "Invalid YAML" in resp.json()["detail"]


def test_submit_validation_failure_rejected(client):
    with patch.object(
        experiments_router, "validate_experiment_config",
        side_effect=ValueError("missing dataset section"),
    ):
        resp = client.post("/v1/experiments", json={"config_yaml": VALID_YAML})
    assert resp.status_code == 422
    assert "missing dataset section" in resp.json()["detail"]


def test_submit_queues_and_writes_yaml(client, fake_lab):
    new_id = "feed0001"
    with patch.object(experiments_router, "validate_experiment_config"), \
         patch.object(experiments_router, "generate_experiment_hash", return_value=new_id), \
         patch.object(experiments_router, "_run_experiment") as run_mock:
        resp = client.post("/v1/experiments", json={"config_yaml": VALID_YAML})

    assert resp.status_code == 202
    body = resp.json()
    assert body == {"experiment_id": new_id, "status": "queued", "detail": None}

    queued_path = os.path.join(fake_lab["experiments"], "queue", f"{new_id}.yaml")
    assert os.path.exists(queued_path)
    with open(queued_path) as f:
        assert yaml.safe_load(f)["execution"]["test_suite"] == "selectivity"
    # Background task dispatched exactly once with the queued file
    run_mock.assert_called_once_with(queued_path)


def test_submit_duplicate_returns_existing_id(client):
    """VALID_YAML strips to the same non-meta content as the fake_lab archived
    config (both are {execution: {test_suite: selectivity}}), so this is a
    genuine duplicate — status 'duplicate', no background task fired."""
    with patch.object(experiments_router, "validate_experiment_config"), \
         patch.object(experiments_router, "generate_experiment_hash", return_value=EXP_ID), \
         patch.object(experiments_router, "_run_experiment") as run_mock:
        resp = client.post("/v1/experiments", json={"config_yaml": VALID_YAML})

    assert resp.status_code == 202
    assert resp.json()["status"] == "duplicate"
    run_mock.assert_not_called()


def test_submit_hash_collision_rejected_with_409(client):
    """A submission whose exp_id matches the archived one but whose CONFIG
    differs is a genuine 32-bit hash collision. Old behavior: 202 + duplicate
    pointing to the WRONG capsule. New behavior (TODO #5, this PR): 409 with
    an informative message."""
    # Submit a YAML that hashes to EXP_ID but parses to a DIFFERENT dict than
    # the fake_lab archived config (which is {execution: {test_suite: selectivity}}).
    colliding_yaml = "meta:\n  name: different experiment\nexecution:\n  test_suite: sort_spill\n"
    with patch.object(experiments_router.ExperimentValidator, "validate"), \
         patch.object(experiments_router, "generate_experiment_hash", return_value=EXP_ID), \
         patch.object(experiments_router, "_run_experiment") as run_mock:
        resp = client.post("/v1/experiments", json={"config_yaml": colliding_yaml})

    assert resp.status_code == 409
    assert "collision" in resp.json()["detail"].lower()
    run_mock.assert_not_called()


def test_status_complete(client):
    resp = client.get(f"/v1/experiments/{EXP_ID}/status")
    body = resp.json()
    assert body["status"] == "complete"
    assert body["fragment_count"] == 4
    assert body["has_csv"] is True


def test_status_lifecycle(client, fake_lab):
    # not_found
    assert client.get("/v1/experiments/eeee0000/status").json()["status"] == "not_found"

    # queued: yaml in queue dir, no results yet
    qid = "eeee0001"
    with open(os.path.join(fake_lab["experiments"], "queue", f"{qid}.yaml"), "w") as f:
        f.write("meta: {}\n")
    assert client.get(f"/v1/experiments/{qid}/status").json()["status"] == "queued"

    # running: results dir exists but config not archived
    os.makedirs(os.path.join(fake_lab["results"], qid))
    assert client.get(f"/v1/experiments/{qid}/status").json()["status"] == "running"


def test_status_failed_when_marker_present(client, fake_lab):
    """After TODO #2: coordinator writes results/<id>/failure.json when a run
    dies; /status returns 'failed' + detail so the agent stops polling a corpse."""
    from sql_benchmarks.failure_marker import write_failure_marker
    from sql_benchmarks.api.data import reader as reader_module

    fid = "eeee0002"
    write_failure_marker(
        reader_module.RESULTS_DIR, fid,
        stage="execution",
        error="Technical execution failed (subprocess returned non-zero exit code).",
    )
    body = client.get(f"/v1/experiments/{fid}/status").json()
    assert body["status"] == "failed"
    assert body["detail"] == "[execution] Technical execution failed (subprocess returned non-zero exit code)."


def test_status_failed_beats_running_when_both_apply(client, fake_lab):
    """A run that produced partial fragments and THEN crashed will satisfy both
    results_exist() (dir present) and has_failure() (marker present). The
    failure marker is the authoritative terminal state — it wins over 'running'."""
    from sql_benchmarks.failure_marker import write_failure_marker
    from sql_benchmarks.api.data import reader as reader_module

    fid = "eeee0003"
    # results dir exists (partial run)
    os.makedirs(os.path.join(reader_module.RESULTS_DIR, fid), exist_ok=True)
    # failure marker also present
    write_failure_marker(
        reader_module.RESULTS_DIR, fid,
        stage="coordinator_exception",
        error="TypeError: unhashable dict",
    )
    body = client.get(f"/v1/experiments/{fid}/status").json()
    assert body["status"] == "failed"
    assert "TypeError" in body["detail"]


def test_status_complete_still_wins_over_failed_marker(client, fake_lab):
    """If for whatever reason both a completion (archived config) AND a failure
    marker exist, 'complete' wins — a completed experiment cannot be undone by
    a stale marker. (Should not happen in practice; belt-and-suspenders.)"""
    from sql_benchmarks.failure_marker import write_failure_marker
    from sql_benchmarks.api.data import reader as reader_module

    write_failure_marker(
        reader_module.RESULTS_DIR, EXP_ID,
        stage="execution", error="stale marker",
    )
    body = client.get(f"/v1/experiments/{EXP_ID}/status").json()
    assert body["status"] == "complete"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
