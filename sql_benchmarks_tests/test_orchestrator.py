"""Tests for the specialist + orchestrator layer.

Model calls are mocked. HTTP calls (the poller + execute_tool) are
mocked where they cross a network boundary. What we're actually
verifying:

1. Specialists get a FILTERED tool set (progressive disclosure) —
   config_builder does NOT see analyzer tools, and vice versa.
2. Orchestrator threads the state machine correctly and short-circuits
   on any stage's failure.
3. The `delegate` event ties sub-run traces to the orchestrator trace.
4. Handoff/final-answer parsers detect completion signals correctly.
"""
import json
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from sql_benchmarks import agent_orchestrator, agent_specialist, agent_trace
from sql_benchmarks.agent_orchestrator import (
    ANALYZER, CONFIG_BUILDER, Orchestrator, _parse_analyzer_final,
    _parse_handoff, poll_until_terminal,
)
from sql_benchmarks.agent_specialist import (
    SpecialistRole, SpecialistResult, run_specialist,
)
from sql_benchmarks.agent_tools import filter_tools, TOOLS


@pytest.fixture(autouse=True)
def _isolate_trace_dir(tmp_path, monkeypatch):
    """Every test gets its own trace dir; no cross-test file pollution."""
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))


# ---------------------------------------------------------------------------
# Tool subsetting — progressive disclosure at the agent's structure level
# ---------------------------------------------------------------------------

def test_config_builder_gets_only_discovery_and_build_tools():
    tools = filter_tools(CONFIG_BUILDER.tool_names)
    names = {t["function"]["name"] for t in tools}
    # Has what it needs
    assert "list_categories" in names
    assert "list_suites" in names
    assert "submit_experiment" in names
    # Does NOT see analyzer tools
    assert "get_experiment_summary" not in names
    assert "get_scaling_factor" not in names
    assert "compare_engines" not in names


def test_analyzer_gets_only_result_reading_tools():
    tools = filter_tools(ANALYZER.tool_names)
    names = {t["function"]["name"] for t in tools}
    assert "get_experiment_summary" in names
    assert "get_scaling_factor" in names
    # Does NOT see config-building tools
    assert "submit_experiment" not in names
    assert "list_templates" not in names


def test_no_specialist_sees_the_full_tool_inventory():
    """Both specialists' tool sets must be strict subsets of TOOLS —
    the whole point of the decomposition."""
    full = {t["function"]["name"] for t in TOOLS}
    for role in (CONFIG_BUILDER, ANALYZER):
        subset = set(role.tool_names)
        assert subset < full  # strict subset
        assert len(subset) <= 7  # kept small


# ---------------------------------------------------------------------------
# Completion-signal parsers
# ---------------------------------------------------------------------------

def test_parse_handoff_extracts_valid_experiment_id():
    assert _parse_handoff("HANDOFF: experiment_id=abcd1234") == {"experiment_id": "abcd1234"}
    # Real-world variations
    assert _parse_handoff("  HANDOFF:experiment_id=deadbeef  ") == {"experiment_id": "deadbeef"}
    # Case insensitive
    assert _parse_handoff("handoff: experiment_id=aabbccdd") == {"experiment_id": "aabbccdd"}


def test_parse_handoff_rejects_bad_shapes():
    assert _parse_handoff("The experiment id is abcd1234") is None
    assert _parse_handoff("HANDOFF: experiment_id=xyz") is None  # not 8 hex
    assert _parse_handoff("") is None
    assert _parse_handoff(None) is None


def test_parse_analyzer_final_detects_final_answer():
    long = "FINAL ANSWER:\n\n" + "x" * 200
    assert _parse_analyzer_final(long) == {"analysis": long}


def test_parse_analyzer_final_rejects_short_or_missing():
    assert _parse_analyzer_final("FINAL ANSWER: short") is None  # too short
    assert _parse_analyzer_final("Some other prose without the signal") is None
    assert _parse_analyzer_final(None) is None


# ---------------------------------------------------------------------------
# Specialist loop — mocked LLM
# ---------------------------------------------------------------------------

def _mock_llm_response(content: str = "", tool_calls=None, usage=None):
    """Build a fake litellm completion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def test_specialist_stops_on_parseable_output_first_turn():
    """If the first model turn produces parseable output, the specialist
    returns immediately — no tool loop needed."""
    role = SpecialistRole(
        name="test",
        tool_names=["list_categories"],
        system_prompt="test prompt",
        parse_output=lambda content, tc: {"ok": True} if "DONE" in content else None,
    )
    with patch.object(agent_specialist, "completion") as mock_completion:
        mock_completion.return_value = _mock_llm_response(content="DONE and here is the answer")
        result = run_specialist(role, brief="do the thing", model="test/model")

    assert result.outcome == "ok"
    assert result.output == {"ok": True}
    assert result.turns_used == 1
    assert result.sub_run_id is not None
    assert mock_completion.call_count == 1


def test_specialist_gives_up_after_max_empty_responses():
    role = SpecialistRole(
        name="test", tool_names=[], system_prompt="test",
        parse_output=lambda c, tc: None,  # never signals done
    )
    with patch.object(agent_specialist, "completion") as mock_completion:
        mock_completion.return_value = _mock_llm_response(content="thinking...")
        result = run_specialist(role, brief="do", model="test/model")
    assert result.outcome == "gave_up"
    assert "non-actionable" in (result.error or "")


def test_specialist_hits_max_turns_if_never_signals_done():
    """If parse_output never fires AND the model keeps calling tools,
    the specialist eventually hits max_turns."""
    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = "list_categories"
    tc.function.arguments = "{}"
    tc.model_dump = lambda: {"id": "call_1", "type": "function",
                             "function": {"name": "list_categories", "arguments": "{}"}}

    role = SpecialistRole(
        name="test", tool_names=["list_categories"],
        system_prompt="test", max_turns=2,
        parse_output=lambda c, tc_: None,
    )
    with patch.object(agent_specialist, "completion") as mock_completion, \
         patch.object(agent_specialist, "execute_tool", return_value='{"ok": true}'):
        mock_completion.return_value = _mock_llm_response(content="calling tool", tool_calls=[tc])
        result = run_specialist(role, brief="do", model="test/model")

    assert result.outcome == "max_turns"
    assert result.turns_used == 2


# ---------------------------------------------------------------------------
# Orchestrator state machine — short-circuits on any stage failure
# ---------------------------------------------------------------------------

def test_orchestrator_short_circuits_on_config_builder_failure():
    """If config_builder fails, poll + analyzer must not run."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        # config_builder gives up
        mock_run_spec.return_value = SpecialistResult(
            role="config_builder", outcome="gave_up", output=None,
            sub_run_id="cb-run", turns_used=15, error="stuck",
        )
        result = Orchestrator(goal="test", model="test/model").run()

    assert result.outcome == "config_builder_failed"
    assert result.experiment_id is None
    assert mock_poll.call_count == 0  # never got to polling
    assert mock_run_spec.call_count == 1  # analyzer never invoked


def test_orchestrator_short_circuits_on_poll_failure():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0001"},
                             sub_run_id="cb-run", turns_used=5),
        ]
        mock_poll.return_value = {"status": "failed", "polls": 3, "detail": "[execute] boom"}
        result = Orchestrator(goal="test", model="test/model").run()

    assert result.outcome == "poll_failed"
    assert result.experiment_id == "aabb0001"
    assert mock_run_spec.call_count == 1  # analyzer never invoked


def test_orchestrator_happy_path_returns_analysis_and_ids():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0002"},
                             sub_run_id="cb-run", turns_used=5),
            SpecialistResult(role="analyzer", outcome="ok",
                             output={"analysis": "FINAL ANSWER: DuckDB wins"},
                             sub_run_id="an-run", turns_used=3),
        ]
        mock_poll.return_value = {"status": "complete", "polls": 2}
        result = Orchestrator(goal="test goal", model="test/model").run()

    assert result.outcome == "complete"
    assert result.experiment_id == "aabb0002"
    assert result.analysis == "FINAL ANSWER: DuckDB wins"
    assert result.sub_run_ids == {"config_builder": "cb-run", "analyzer": "an-run"}


def test_orchestrator_trace_records_delegate_events(tmp_path, monkeypatch):
    """Orchestrator trace must record one `delegate` event per stage,
    naming each specialist's sub_run_id — that's how a reader walks
    the tree."""
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))

    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0003"},
                             sub_run_id="cb-run", turns_used=1),
            SpecialistResult(role="analyzer", outcome="ok",
                             output={"analysis": "done"},
                             sub_run_id="an-run", turns_used=1),
        ]
        mock_poll.return_value = {"status": "complete", "polls": 1}
        orch = Orchestrator(goal="test", model="test/model")
        result = orch.run()

    events = [json.loads(l) for l in open(orch.trace.path)]
    delegates = [e for e in events if e["event"] == "delegate"]
    assert [d["stage"] for d in delegates] == ["config_builder", "poll", "analyzer"]
    assert delegates[0]["sub_run_id"] == "cb-run"
    assert delegates[1]["sub_run_id"] is None  # poll is pure-Python
    assert delegates[2]["sub_run_id"] == "an-run"


# ---------------------------------------------------------------------------
# Pure-Python poller
# ---------------------------------------------------------------------------

def test_poll_until_terminal_returns_on_complete():
    with patch.object(agent_orchestrator.httpx, "get") as mock_get:
        mock_get.return_value.json.return_value = {"status": "complete"}
        result = poll_until_terminal("aabb0004", max_polls=5, interval_seconds=0)
    assert result["status"] == "complete"
    assert result["polls"] == 1


def test_poll_until_terminal_returns_on_failed_with_detail():
    with patch.object(agent_orchestrator.httpx, "get") as mock_get:
        mock_get.return_value.json.return_value = {"status": "failed", "detail": "oops"}
        result = poll_until_terminal("aabb0005", max_polls=5, interval_seconds=0)
    assert result["status"] == "failed"
    assert result["detail"] == "oops"


def test_poll_until_terminal_times_out():
    with patch.object(agent_orchestrator.httpx, "get") as mock_get:
        mock_get.return_value.json.return_value = {"status": "running"}
        result = poll_until_terminal("aabb0006", max_polls=3, interval_seconds=0)
    assert result["status"] == "timeout"
    assert result["polls"] == 3
