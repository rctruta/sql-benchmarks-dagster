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
        assert len(subset) <= 9  # kept small (analyzer gained the per-benchmark projection)


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


def _librarian_routes_to_build():
    """run() now begins with the reference librarian (Finding 21's
    structural fix); tests of the downstream stages prepend this."""
    return SpecialistResult(role="librarian", outcome="ok",
                            output={"build": "not in corpus"},
                            sub_run_id="lib-run", turns_used=2)

def test_orchestrator_short_circuits_on_config_builder_failure():
    """If config_builder fails, poll + analyzer must not run."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        # config_builder gives up
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
            SpecialistResult(role="config_builder", outcome="gave_up", output=None,
                             sub_run_id="cb-run", turns_used=15, error="stuck"),
        ]
        result = Orchestrator(goal="test", model="test/model").run()

    assert result.outcome == "config_builder_failed"
    assert result.experiment_id is None
    assert mock_poll.call_count == 0  # never got to polling
    assert mock_run_spec.call_count == 2  # librarian + config_builder; analyzer never invoked


def test_orchestrator_short_circuits_on_poll_failure():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0001"},
                             sub_run_id="cb-run", turns_used=5),
        ]
        mock_poll.return_value = {"status": "failed", "polls": 3, "detail": "[execute] boom"}
        result = Orchestrator(goal="test", model="test/model").run()

    assert result.outcome == "poll_failed"
    assert result.experiment_id == "aabb0001"
    assert mock_run_spec.call_count == 2  # analyzer never invoked


def test_orchestrator_happy_path_returns_analysis_and_ids():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
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
    assert result.sub_run_ids == {"librarian": "lib-run",
                                  "config_builder": "cb-run", "analyzer": "an-run"}


def test_orchestrator_trace_records_delegate_events(tmp_path, monkeypatch):
    """Orchestrator trace must record one `delegate` event per stage,
    naming each specialist's sub_run_id — that's how a reader walks
    the tree."""
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))

    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
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
    assert [d["stage"] for d in delegates] == ["librarian", "config_builder", "poll", "analyzer"]
    assert delegates[0]["sub_run_id"] == "lib-run"
    assert delegates[1]["sub_run_id"] == "cb-run"
    assert delegates[2]["sub_run_id"] is None  # poll is pure-Python
    assert delegates[3]["sub_run_id"] == "an-run"


# ---------------------------------------------------------------------------
# Pure-Python poller
# ---------------------------------------------------------------------------

def test_poll_until_terminal_returns_on_complete():
    with patch.object(agent_orchestrator, "_get_client") as mock_client:
        mock_get = mock_client.return_value.get
        mock_get.return_value.json.return_value = {"status": "complete"}
        result = poll_until_terminal("aabb0004", max_polls=5, interval_seconds=0)
    assert result["status"] == "complete"
    assert result["polls"] == 1


def test_poll_until_terminal_returns_on_failed_with_detail():
    with patch.object(agent_orchestrator, "_get_client") as mock_client:
        mock_get = mock_client.return_value.get
        mock_get.return_value.json.return_value = {"status": "failed", "detail": "oops"}
        result = poll_until_terminal("aabb0005", max_polls=5, interval_seconds=0)
    assert result["status"] == "failed"
    assert result["detail"] == "oops"


def test_poll_until_terminal_times_out():
    with patch.object(agent_orchestrator, "_get_client") as mock_client:
        mock_get = mock_client.return_value.get
        mock_get.return_value.json.return_value = {"status": "running"}
        result = poll_until_terminal("aabb0006", max_polls=3, interval_seconds=0)
    assert result["status"] == "timeout"
    assert result["polls"] == 3


# ---------------------------------------------------------------------------
# Harness hardening (from llama3 live-fire failures, 2026-07-05)
# ---------------------------------------------------------------------------

from sql_benchmarks.agent_specialist import try_recover_tool_call_from_text


def test_recover_tool_call_from_function_name_json_text():
    """llama3 emitted `{"function_name": "submit_experiment", ...}` as raw
    TEXT instead of a native tool call (turns 5/6/11 of the live-fire).
    The monolith's recovery only knew the `name` key and missed it."""
    text = '{"function_name": "submit_experiment", "arguments": {"config_yaml": "meta: {}"}}'
    call, reason = try_recover_tool_call_from_text(text, {"submit_experiment"})
    assert reason is None
    assert call.function.name == "submit_experiment"
    assert json.loads(call.function.arguments) == {"config_yaml": "meta: {}"}


def test_recover_tool_call_from_fenced_json():
    text = '```json\n{"name": "list_categories", "arguments": {}}\n```'
    call, reason = try_recover_tool_call_from_text(text, {"list_categories"})
    assert reason is None
    assert call.function.name == "list_categories"


def test_recover_rejects_unknown_tool_with_reason():
    """Hallucinated tool names (llama3 called its own ROLE as a tool) are
    rejected with a coaching reason, not silently dropped."""
    text = '{"name": "CONFIG-BUILDER", "arguments": {"category": "scaling"}}'
    call, reason = try_recover_tool_call_from_text(text, {"list_suites"})
    assert call is None
    assert "CONFIG-BUILDER" in reason
    assert "list_suites" in reason


def test_recover_ignores_non_call_text():
    assert try_recover_tool_call_from_text("plain prose", {"x"}) == (None, None)
    assert try_recover_tool_call_from_text('{"categories": [1,2]}', {"x"}) == (None, None)
    assert try_recover_tool_call_from_text("", {"x"}) == (None, None)


def test_precondition_gate_blocks_submit_before_get_template():
    """Mechanical workflow gate: submit_experiment refuses to dispatch
    until get_template has succeeded this run. Live-fire lesson: prompt
    exhortation doesn't bind on weak models; a procedural gate does."""
    submit_tc = MagicMock()
    submit_tc.id = "call_s"
    submit_tc.function.name = "submit_experiment"
    submit_tc.function.arguments = '{"config_yaml": "meta: {}"}'
    submit_tc.model_dump = lambda: {"id": "call_s", "type": "function",
                                    "function": {"name": "submit_experiment",
                                                 "arguments": '{"config_yaml": "meta: {}"}'}}

    role = SpecialistRole(
        name="test", tool_names=["get_template", "submit_experiment"],
        system_prompt="t", max_turns=2,
        parse_output=lambda c, tc: None,
        tool_preconditions={"submit_experiment": ("get_template", "REFUSED: fetch a template first")},
    )
    executed = []
    with patch.object(agent_specialist, "completion") as mock_completion, \
         patch.object(agent_specialist, "execute_tool",
                      side_effect=lambda n, a: executed.append(n) or '{"ok": true}') as mock_exec:
        mock_completion.return_value = _mock_llm_response(content="", tool_calls=[submit_tc])
        result = run_specialist(role, brief="go", model="test/model")

    # submit_experiment was requested twice (2 turns) but NEVER dispatched
    assert executed == []
    assert result.outcome == "max_turns"


def test_precondition_gate_opens_after_required_tool_succeeds():
    get_tc = MagicMock()
    get_tc.id = "call_g"
    get_tc.function.name = "get_template"
    get_tc.function.arguments = '{"name": "quickstart"}'
    get_tc.model_dump = lambda: {"id": "call_g", "type": "function",
                                 "function": {"name": "get_template",
                                              "arguments": '{"name": "quickstart"}'}}
    submit_tc = MagicMock()
    submit_tc.id = "call_s"
    submit_tc.function.name = "submit_experiment"
    submit_tc.function.arguments = '{"config_yaml": "meta: {}"}'
    submit_tc.model_dump = lambda: {"id": "call_s", "type": "function",
                                    "function": {"name": "submit_experiment",
                                                 "arguments": '{"config_yaml": "meta: {}"}'}}

    role = SpecialistRole(
        name="test", tool_names=["get_template", "submit_experiment"],
        system_prompt="t", max_turns=3,
        parse_output=lambda c, tc: None,
        tool_preconditions={"submit_experiment": ("get_template", "REFUSED")},
    )
    executed = []
    responses = [
        _mock_llm_response(content="", tool_calls=[get_tc]),
        _mock_llm_response(content="", tool_calls=[submit_tc]),
        _mock_llm_response(content="", tool_calls=[]),
    ]
    with patch.object(agent_specialist, "completion", side_effect=responses), \
         patch.object(agent_specialist, "execute_tool",
                      side_effect=lambda n, a: executed.append(n) or '{"ok": true}'):
        run_specialist(role, brief="go", model="test/model")

    assert executed == ["get_template", "submit_experiment"]


def test_repeated_failing_call_gets_escalating_coaching():
    """Same (tool, args) failing twice in a row must inject the STOP
    coaching message. llama3 repeated an identical failing call 9x."""
    bad_tc = MagicMock()
    bad_tc.id = "call_b"
    bad_tc.function.name = "list_categories"
    bad_tc.function.arguments = "{}"
    bad_tc.model_dump = lambda: {"id": "call_b", "type": "function",
                                 "function": {"name": "list_categories", "arguments": "{}"}}

    role = SpecialistRole(
        name="test", tool_names=["list_categories"],
        system_prompt="t", max_turns=3,
        parse_output=lambda c, tc: None,
    )
    captured_messages = []

    def fake_completion(model, messages, tools, tool_choice):
        captured_messages.clear()
        captured_messages.extend(messages)
        return _mock_llm_response(content="", tool_calls=[bad_tc])

    with patch.object(agent_specialist, "completion", side_effect=fake_completion), \
         patch.object(agent_specialist, "execute_tool",
                      return_value='{"error": "boom"}'):
        run_specialist(role, brief="go", model="test/model")

    # By the third turn, history must contain the escalated STOP coaching
    stop_msgs = [m for m in captured_messages
                 if m.get("role") == "user" and "STOP" in (m.get("content") or "")]
    assert stop_msgs, "expected escalating STOP coaching after repeated identical failures"


# ---------------------------------------------------------------------------
# Refusal state + contract-declared poll budget (from edge-case studies 3+4)
# ---------------------------------------------------------------------------

def test_parse_handoff_impossible():
    out = _parse_handoff("HANDOFF: impossible reason=MongoDB is not an available engine")
    assert out == {"impossible": "MongoDB is not an available engine"}
    # experiment_id form still wins when present
    assert _parse_handoff("HANDOFF: experiment_id=abcd1234") == {"experiment_id": "abcd1234"}


def test_orchestrator_refusal_is_terminal_honest_and_cheap():
    """config_builder's structured refusal ends the run: no poll, no
    analyzer, outcome='refused' (not a failure), reason surfaced."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.return_value = SpecialistResult(
            role="config_builder", outcome="ok",
            output={"impossible": "no MongoDB engine in the catalog"},
            sub_run_id="cb-run", turns_used=3,
        )
        result = Orchestrator(goal="benchmark MongoDB", model="test/model").run()

    assert result.outcome == "refused"
    assert result.experiment_id is None
    assert "no MongoDB engine" in result.analysis
    assert result.error is None            # refusal is not an error
    assert mock_poll.call_count == 0        # never polled
    assert mock_run_spec.call_count == 1    # analyzer never invoked


def test_poll_budget_is_contract_declarable():
    """Edge-4 defect: fixed 180s budget killed slow suites. The budget
    must flow Orchestrator(poll_budget_seconds=...) -> poll max_polls."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0007"},
                             sub_run_id="cb", turns_used=1),
            SpecialistResult(role="analyzer", outcome="ok",
                             output={"analysis": "FINAL ANSWER: x" * 20},
                             sub_run_id="an", turns_used=1),
        ]
        mock_poll.return_value = {"status": "complete", "polls": 1}
        Orchestrator(goal="g", model="m", poll_budget_seconds=1800).run()

    _, kwargs = mock_poll.call_args
    assert kwargs["max_polls"] == 600  # 1800s / 3s interval


# ---------------------------------------------------------------------------
# Suspended state + resume (edge-4 follow-through: no poll budget is "right"
# for open-ended workloads — a 16GB out-of-memory sort outlived a 30-min
# budget while executing legitimately; the capsule is the durable hand-off)
# ---------------------------------------------------------------------------

def test_poll_timeout_suspends_not_fails():
    """Timeout while the experiment is still executing -> outcome
    'suspended' (not an error), experiment_id preserved for resume,
    analyzer NOT invoked (its tokens are spent later, on resume)."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            _librarian_routes_to_build(),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0008"},
                             sub_run_id="cb", turns_used=2),
        ]
        mock_poll.return_value = {"status": "timeout", "polls": 600}
        result = Orchestrator(goal="g", model="m", poll_budget_seconds=1800).run()

    assert result.outcome == "suspended"
    assert result.experiment_id == "aabb0008"
    assert result.error is None                  # suspension is not an error
    assert mock_run_spec.call_count == 2         # analyzer never ran


def test_resume_completes_when_capsule_ready():
    """resume(exp_id) skips config_builder entirely: poll -> analyzer."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_poll.return_value = {"status": "complete", "polls": 1}
        mock_run_spec.return_value = SpecialistResult(
            role="analyzer", outcome="ok",
            output={"analysis": "FINAL ANSWER: spill confirmed"},
            sub_run_id="an", turns_used=3)
        with patch.object(agent_orchestrator.httpx, "get") as mock_get:
            mock_get.return_value.json.return_value = {"config": {}}
            result = Orchestrator(goal="g", model="m").resume("aabb0009")

    assert result.outcome == "complete"
    assert result.analysis == "FINAL ANSWER: spill confirmed"
    assert result.sub_run_ids["config_builder"] is None   # skipped on resume
    assert mock_run_spec.call_count == 1                  # analyzer only


def test_resume_resuspends_if_still_running():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_poll.return_value = {"status": "timeout", "polls": 60}
        result = Orchestrator(goal="g", model="m").resume("aabb000a")
    assert result.outcome == "suspended"
    assert result.experiment_id == "aabb000a"
    assert mock_run_spec.call_count == 0


def test_resume_surfaces_execution_failure():
    """A capsule that FAILED while suspended must come back as poll_failed
    with the failure detail, not as suspended."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_poll.return_value = {"status": "failed", "polls": 1,
                                  "detail": "[execute] out of disk"}
        result = Orchestrator(goal="g", model="m").resume("aabb000b")
    assert result.outcome == "poll_failed"
    assert "out of disk" in result.error
    assert mock_run_spec.call_count == 0


# ---------------------------------------------------------------------------
# Reference librarian — ask() mode + librarian-first routing in run().
# Structural fix for Finding 21: 0/5 unprompted library adoption showed
# schema-only exposure doesn't bind; a workflow STAGE does.
# ---------------------------------------------------------------------------

from sql_benchmarks.agent_orchestrator import LIBRARIAN, _parse_librarian


def test_librarian_tool_desk_is_read_only():
    """The reference desk can discover and READ everything, and can
    execute NOTHING — no submit, no templates, no build tools."""
    from sql_benchmarks.agent_tools import filter_tools
    names = {t["function"]["name"] for t in filter_tools(LIBRARIAN.tool_names)}
    assert "search_published_capsules" in names
    assert "list_lab_docs" in names and "get_lab_doc" in names
    assert "get_experiment_summary" in names
    assert "submit_experiment" not in names
    assert "get_template" not in names


def test_parse_librarian_three_closes():
    long_answer = "FINAL ANSWER: yes — capsules b8e2bfaf and 25b0e134 cover this. " + "x" * 100
    assert _parse_librarian(long_answer) == {"analysis": long_answer}
    assert _parse_librarian("HANDOFF: build reason=no capsule covers 100M-row joins") \
        == {"build": "no capsule covers 100M-row joins"}
    assert _parse_librarian("HANDOFF: impossible reason=no MongoDB engine") \
        == {"impossible": "no MongoDB engine"}
    assert _parse_librarian("just thinking out loud") is None


def test_ask_mode_answers_without_executing():
    """The user-delegation use case: 'are there published capsules for X?'
    Librarian answers; config_builder and poll never run."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.return_value = SpecialistResult(
            role="librarian", outcome="ok",
            output={"analysis": "FINAL ANSWER: yes, b8e2bfaf covers quack transport" + "x" * 80},
            sub_run_id="lib", turns_used=3)
        result = Orchestrator(goal="are there published capsules for quack?",
                              model="m").ask()
    assert result.outcome == "answered"
    assert "b8e2bfaf" in result.analysis
    assert mock_run_spec.call_count == 1
    assert mock_poll.call_count == 0


def test_ask_mode_routes_build_worthy_questions_without_building():
    """ask() never executes — a build-worthy question comes back as
    needs_experiment and the CALLER decides whether to spend."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec:
        mock_run_spec.return_value = SpecialistResult(
            role="librarian", outcome="ok",
            output={"build": "no capsule covers recursive CTEs at scale"},
            sub_run_id="lib", turns_used=4)
        result = Orchestrator(goal="how do recursive CTEs scale?", model="m").ask()
    assert result.outcome == "needs_experiment"
    assert "recursive CTEs" in result.analysis
    assert mock_run_spec.call_count == 1


def test_run_answers_from_corpus_and_skips_build():
    """Librarian-first in run(): corpus answer -> terminal, config_builder
    never invoked. The Finding 21 economics, structurally enforced."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.return_value = SpecialistResult(
            role="librarian", outcome="ok",
            output={"analysis": "FINAL ANSWER: published capsule answers this" + "x" * 80},
            sub_run_id="lib", turns_used=2)
        result = Orchestrator(goal="quack overhead?", model="m").run()
    assert result.outcome == "answered"
    assert mock_run_spec.call_count == 1  # librarian only — no config_builder
    assert mock_poll.call_count == 0


def test_run_proceeds_to_build_on_librarian_handoff():
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            SpecialistResult(role="librarian", outcome="ok",
                             output={"build": "nothing on sort spill at 100M"},
                             sub_run_id="lib", turns_used=2),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb000c"},
                             sub_run_id="cb", turns_used=5),
            SpecialistResult(role="analyzer", outcome="ok",
                             output={"analysis": "FINAL ANSWER: measured"},
                             sub_run_id="an", turns_used=3),
        ]
        mock_poll.return_value = {"status": "complete", "polls": 1}
        with patch.object(agent_orchestrator.httpx, "get") as mock_get:
            mock_get.return_value.json.return_value = {"config": {}}
            result = Orchestrator(goal="sort spill at 100M?", model="m").run()
    assert result.outcome == "complete"
    assert result.experiment_id == "aabb000c"
    assert result.sub_run_ids["librarian"] == "lib"


def test_run_proceeds_to_build_when_librarian_fails():
    """A broken reference desk must not block measurement."""
    with patch.object(agent_orchestrator, "run_specialist") as mock_run_spec, \
         patch.object(agent_orchestrator, "poll_until_terminal") as mock_poll:
        mock_run_spec.side_effect = [
            SpecialistResult(role="librarian", outcome="gave_up", output=None,
                             sub_run_id="lib", turns_used=12, error="stuck"),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"impossible": "whatever"},
                             sub_run_id="cb", turns_used=2),
        ]
        result = Orchestrator(goal="g", model="m").run()
    assert result.outcome == "refused"      # reached config_builder despite librarian failure
    assert mock_run_spec.call_count == 2
