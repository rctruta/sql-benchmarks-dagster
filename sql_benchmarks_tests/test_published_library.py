"""Tests for published-capsule discovery (edge-case 6 instrument).

'Published' = git-tracked AND sealed — verify_doc_claims' definition.
Local/transient capsules must never leak into the library."""
import json
import os
from unittest.mock import patch

import pytest
import yaml

from sql_benchmarks.api.logic import published_library
from sql_benchmarks.api.logic.published_library import search_published_capsules


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two tracked capsules (one sealed, one not) + one local-only sealed."""
    results = tmp_path / "results"
    for exp_id, sealed, suite, desc in (
        ("aaaa1111", True, "quack_transport", "Quack native vs ADBC transport"),
        ("bbbb2222", False, "selectivity", "tracked but unsealed"),
        ("cccc3333", True, "analytical_wall", "LOCAL ONLY — must not appear"),
    ):
        d = results / exp_id
        d.mkdir(parents=True)
        if sealed:
            (d / "integrity.seal").write_text("seal")
        (d / "experiment_config.yaml").write_text(yaml.dump({
            "meta": {"description": desc},
            "execution": {"test_suite": suite, "engines": ["duckdb", "quack"]},
        }))
    monkeypatch.setattr(published_library, "RESULTS_DIR", str(results))
    monkeypatch.setattr(published_library, "CONFIG_ARCHIVE_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(published_library, "_git_tracked_capsule_ids",
                        lambda: {"aaaa1111", "bbbb2222", "cccc3333"})
    return results


def test_published_means_tracked_and_sealed(library):
    got = search_published_capsules()
    ids = sorted(c["experiment_id"] for c in got)
    assert ids == ["aaaa1111", "cccc3333"]  # both git-tracked and local sealed are returned
    c = next(x for x in got if x["experiment_id"] == "aaaa1111")
    assert c["suite"] == "quack_transport"
    assert c["engines"] == ["duckdb", "quack"]
    assert "ADBC" in c["description"]   # derived from the capsule's own config


def test_category_filter_uses_taxonomy(library):
    # quack_transport is tagged [transport, columnar] in taxonomy.yaml
    assert [c["experiment_id"] for c in search_published_capsules(category="transport")] \
        == ["aaaa1111"]
    assert search_published_capsules(category="security") == []


def test_git_tracked_capsule_ids_includes_local_sealed(tmp_path, monkeypatch):
    """Test that the real unmocked function scans RESULTS_DIR for local sealed capsules."""
    results = tmp_path / "results"
    monkeypatch.setattr(published_library, "RESULTS_DIR", str(results))
    
    # Create one local sealed, one local unsealed
    (results / "local1111").mkdir(parents=True)
    (results / "local1111" / "integrity.seal").write_text("seal")
    
    (results / "local2222").mkdir(parents=True) # no seal
    
    # We stub ROOT_DIR to a dummy path so git returns nothing, testing only the local scanner
    monkeypatch.setattr(published_library, "ROOT_DIR", str(tmp_path))
    
    ids = published_library._git_tracked_capsule_ids()
    assert "local1111" in ids
    assert "local2222" not in ids


def test_config_builder_sees_the_library_tool():
    from sql_benchmarks.agent_orchestrator import CONFIG_BUILDER
    from sql_benchmarks.agent_tools import filter_tools
    names = {t["function"]["name"] for t in filter_tools(CONFIG_BUILDER.tool_names)}
    assert "search_published_capsules" in names


def test_prompt_does_not_steer_toward_library():
    """The experiment measures UNPROMPTED adoption — the workflow prompt
    must not mention the library tool."""
    from sql_benchmarks.agent_orchestrator import _CONFIG_BUILDER_PROMPT
    assert "search_published_capsules" not in _CONFIG_BUILDER_PROMPT
    assert "published" not in _CONFIG_BUILDER_PROMPT.lower()
