"""Tests for the structured JSONL agent trace (sql_benchmarks/agent_trace.py).

The trace is what SBD-2 (llama3 workflow-capability failure) didn't have:
per-turn events we can post-hoc mine to answer "how exactly did the run
fail". These tests verify each event type serializes as one JSON line
with the expected fields.
"""
import json

from sql_benchmarks import agent_trace
from sql_benchmarks.agent_trace import AgentTrace


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_run_start_written_on_construction(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    t = AgentTrace(goal="test goal", model="gpt-4o",
                   agents_md_loaded=True, max_turns=25)
    events = _read(t.path)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "run_start"
    assert e["goal"] == "test goal"
    assert e["model"] == "gpt-4o"
    assert e["agents_md_loaded"] is True
    assert e["max_turns"] == 25
    assert "run_id" in e and "ts" in e


def test_run_id_stable_and_deterministic_from_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    # Same goal → same 8-hex suffix; different goal → different suffix.
    a = AgentTrace("goal A", "m", True, 25)
    b = AgentTrace("goal B", "m", True, 25)
    a_suffix = a.run_id.rsplit("_", 1)[-1]
    b_suffix = b.run_id.rsplit("_", 1)[-1]
    assert a_suffix != b_suffix
    assert len(a_suffix) == 8


def test_all_event_types_emit_expected_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    t = AgentTrace("g", "m", True, 25)

    t.turn_start(turn=1)
    t.model_response(turn=1, content="hello", tool_calls=[],
                     response=None, recovered_call_reason=None)
    t.tool_call(turn=1, tool_call_id="c1", name="list_suites", arguments={})
    t.tool_result(turn=1, tool_call_id="c1", name="list_suites",
                  result='{"ok": true}', error_reason=None)
    t.nudge(turn=1, reason="empty", attempt=1, max_attempts=3)
    t.final_answer(turn=5, content="FINAL ANSWER: X won")
    t.run_end(outcome="final_answer", turns_used=5)

    events = _read(t.path)
    kinds = [e["event"] for e in events]
    assert kinds == ["run_start", "turn_start", "model_response", "tool_call",
                     "tool_result", "nudge", "final_answer", "run_end"]

    mr = [e for e in events if e["event"] == "model_response"][0]
    assert mr["content"] == "hello"
    assert mr["content_len"] == 5
    assert mr["empty_content"] is False
    assert mr["tool_calls"] == []
    assert mr["usage"] is None

    tc = [e for e in events if e["event"] == "tool_call"][0]
    assert tc["name"] == "list_suites"
    assert tc["tool_call_id"] == "c1"

    tr = [e for e in events if e["event"] == "tool_result"][0]
    assert tr["result"] == '{"ok": true}'
    assert tr["result_len"] == 12
    assert tr["error_reason"] is None

    end = [e for e in events if e["event"] == "run_end"][0]
    assert end["outcome"] == "final_answer"
    assert end["turns_used"] == 5


def test_tool_calls_normalized_from_string_arguments(tmp_path, monkeypatch):
    """litellm returns tool_calls with `.function.arguments` as a JSON
    STRING. The trace should decode it so downstream consumers get a
    structured dict."""
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    t = AgentTrace("g", "m", True, 25)

    class FakeToolCall:
        class function:
            name = "submit_experiment"
            arguments = '{"config_yaml": "meta: {}"}'

    t.model_response(turn=1, content="", tool_calls=[FakeToolCall()],
                     response=None, recovered_call_reason=None)
    events = _read(t.path)
    mr = [e for e in events if e["event"] == "model_response"][0]
    assert mr["tool_calls"] == [{"name": "submit_experiment",
                                 "arguments": {"config_yaml": "meta: {}"}}]
    assert mr["empty_content"] is True


def test_empty_content_flagged(tmp_path, monkeypatch):
    """The exact signal that made SBD-2 opaque: model produced a response
    with no content and no tool calls. Trace must record this as
    `empty_content: True` so the failure category is machine-readable."""
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    t = AgentTrace("g", "m", True, 25)
    t.model_response(turn=1, content="   ", tool_calls=[],
                     response=None, recovered_call_reason=None)
    events = _read(t.path)
    mr = [e for e in events if e["event"] == "model_response"][0]
    assert mr["empty_content"] is True
    assert mr["content_len"] == 3  # whitespace preserved verbatim


def test_usage_extracted_from_pydantic_response(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    t = AgentTrace("g", "m", True, 25)

    class FakeUsage:
        def model_dump(self):
            return {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

    class FakeResponse:
        usage = FakeUsage()

    t.model_response(turn=1, content="ok", tool_calls=[],
                     response=FakeResponse(), recovered_call_reason=None)
    events = _read(t.path)
    mr = [e for e in events if e["event"] == "model_response"][0]
    assert mr["usage"] == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


def test_run_end_records_outcome_variants(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_trace, "AGENT_RUNS_DIR", str(tmp_path))
    for outcome in ("final_answer", "gave_up", "max_turns", "exception"):
        t = AgentTrace(f"g-{outcome}", "m", True, 25)
        t.run_end(outcome=outcome, turns_used=7,
                  error="boom" if outcome == "exception" else None)
        end = [e for e in _read(t.path) if e["event"] == "run_end"][0]
        assert end["outcome"] == outcome
        assert end["turns_used"] == 7
