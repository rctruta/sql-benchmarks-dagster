"""Tests for the contract-driven study runner (scripts/run_study.py).

The runner imports litellm-dependent modules lazily (inside
run_cell_rep), so contract loading and matrix expansion are testable
without agent deps."""
import importlib.util
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "run_study", os.path.join(_REPO_ROOT, "scripts", "run_study.py"))
run_study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_study)


VALID = """\
meta:
  name: t
driver: monolith
model: test/model
replications: 2
goal: do the thing
cells:
  a:
    flags: {include_agents_md: true, include_skills: false}
  b:
    flags: {include_agents_md: false, include_skills: false}
"""


def _write(tmp_path, text, name="study.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_study_id_is_content_addressed(tmp_path):
    p1 = _write(tmp_path, VALID, "s1.yaml")
    p2 = _write(tmp_path, VALID, "s2.yaml")
    id1, _ = run_study.load_contract(p1)
    id2, _ = run_study.load_contract(p2)
    assert id1 == id2  # same bytes -> same study, regardless of filename
    assert len(id1) == 8

    # One changed byte -> different study
    p3 = _write(tmp_path, VALID.replace("replications: 2", "replications: 3"), "s3.yaml")
    id3, _ = run_study.load_contract(p3)
    assert id3 != id1


def test_contract_missing_key_rejected(tmp_path):
    import yaml as yaml_mod
    base = yaml_mod.safe_load(VALID)
    for key in ("driver", "model", "replications", "goal", "cells"):
        broken = {k: v for k, v in base.items() if k != key}
        with pytest.raises(ValueError, match=key):
            run_study.load_contract(
                _write(tmp_path, yaml_mod.dump(broken), f"broken_{key}.yaml"))


def test_contract_unknown_driver_rejected(tmp_path):
    with pytest.raises(ValueError, match="driver"):
        run_study.load_contract(
            _write(tmp_path, VALID.replace("driver: monolith", "driver: swarm")))


def test_cell_without_flags_rejected(tmp_path):
    broken = VALID + "  c:\n    note: no flags here\n"
    with pytest.raises(ValueError, match="flags"):
        run_study.load_contract(_write(tmp_path, broken))


def test_shipped_attribution_contract_loads():
    """The contract for the study already run (PR #139) must parse."""
    path = os.path.join(_REPO_ROOT, "sql_benchmarks", "experiments",
                        "studies", "attribution_2x2.yaml")
    study_id, contract = run_study.load_contract(path)
    assert len(study_id) == 8
    assert contract["driver"] == "monolith"
    assert set(contract["cells"]) == {"base", "noskills", "noagentsmd", "neither"}
    assert contract["replications"] >= 1
    # Every cell's flags must be valid run_agent kwargs
    for cell in contract["cells"].values():
        assert set(cell["flags"]) <= {"include_agents_md", "include_skills"}


def test_run_cell_rep_stamps_study_metadata(tmp_path, monkeypatch):
    """The runner must pass study_id/cell/rep through to run_agent."""
    p = _write(tmp_path, VALID)
    study_id, contract = run_study.load_contract(p)

    calls = []

    class FakeAgent:
        @staticmethod
        def run_agent(goal, model, study_stamp, **flags):
            calls.append({"goal": goal, "model": model,
                          "study_stamp": study_stamp, "flags": flags})

    monkeypatch.setitem(sys.modules, "autonomous_agent", FakeAgent)
    run_study.run_cell_rep(contract, study_id, "a", rep=2, model="test/model")

    assert len(calls) == 1
    c = calls[0]
    assert c["study_stamp"] == {"study_id": study_id, "cell": "a", "rep": 2,
                                "study_model": "test/model"}
    assert c["flags"] == {"include_agents_md": True, "include_skills": False}
    assert c["model"] == "test/model"


def test_models_list_normalization(tmp_path):
    """`model:` (single) normalizes to a one-item `models` list; a
    `models:` list passes through; neither is rejected."""
    _, single = run_study.load_contract(_write(tmp_path, VALID, "single.yaml"))
    assert single["models"] == ["test/model"]

    multi = VALID.replace("model: test/model",
                          "models: [weak/a, mid/b, strong/c]")
    _, c = run_study.load_contract(_write(tmp_path, multi, "multi.yaml"))
    assert c["models"] == ["weak/a", "mid/b", "strong/c"]

    neither = "\n".join(l for l in VALID.splitlines() if not l.startswith("model"))
    with pytest.raises(ValueError, match="model"):
        run_study.load_contract(_write(tmp_path, neither, "none.yaml"))
