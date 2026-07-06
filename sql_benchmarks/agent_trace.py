"""Structured JSONL logging for autonomous_agent.py runs.

Every meaningful event during a run is emitted as one JSON line in
`sql_benchmarks/experiments/agent_runs/<run_id>.jsonl`.

Motivation: SBD-2 (llama3 workflow-capability failure) gave us
"gave up at turn 23" with no visibility into *how*. Structured
per-turn events let downstream analysis answer questions like:

  - Which turn was the last one with a tool call?
  - What was the model producing during non-actionable turns?
  - How many tokens did a failed 23-turn run consume vs a successful
    11-turn run?
  - Which projection did the model ask for at each analysis turn?
    (once the granular result-reader lands)

This trace is designed to be sealable (Fork B). Every event includes
its run_id, a UTC timestamp, and the exact content produced or
consumed by the model — the tuple `(measurement capsule, agent trace,
model identifier)` is what a future analysis-capsule seals.

Not thread-safe. autonomous_agent runs one loop per process.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_RUNS_DIR = os.path.join(_REPO_ROOT, "sql_benchmarks", "experiments", "agent_runs")


def _new_run_id(goal: str) -> str:
    """`<UTC-ISO-compact>_<goal-hash-8>` — sortable + identifiable."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    goal_h = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:8]
    return f"{ts}_{goal_h}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tool_calls(tool_calls) -> list:
    """Normalize litellm's tool-call objects (or already-normalized dicts) to
    a plain list of `{name, arguments}` with `arguments` decoded from JSON
    where possible. Keeps the trace consumable without litellm imports."""
    out = []
    for tc in tool_calls or []:
        if hasattr(tc, "function"):
            name = tc.function.name
            args = tc.function.arguments
        elif isinstance(tc, dict):
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            args = fn.get("arguments") or tc.get("arguments")
        else:
            name, args = None, None
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass  # leave as string if not valid JSON
        out.append({"name": name, "arguments": args})
    return out


def _usage_from_response(response) -> dict | None:
    """Extract token-usage dict from a litellm completion response, if any."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


class AgentTrace:
    """One agent run = one JSONL file. Each method emits one event line."""

    def __init__(self, goal: str, model: str, agents_md_loaded: bool, max_turns: int):
        os.makedirs(AGENT_RUNS_DIR, exist_ok=True)
        self.run_id = _new_run_id(goal)
        self.path = os.path.join(AGENT_RUNS_DIR, f"{self.run_id}.jsonl")
        self._emit("run_start", {
            "goal": goal,
            "model": model,
            "agents_md_loaded": agents_md_loaded,
            "max_turns": max_turns,
        })

    def _emit(self, event: str, data: dict) -> None:
        record = {"ts": _iso_now(), "run_id": self.run_id, "event": event, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def turn_start(self, turn: int) -> None:
        self._emit("turn_start", {"turn": turn})

    def model_response(self, turn: int, content: str, tool_calls,
                       response=None, recovered_call_reason: str | None = None) -> None:
        self._emit("model_response", {
            "turn": turn,
            "content": content or "",
            "content_len": len(content or ""),
            "tool_calls": _normalize_tool_calls(tool_calls),
            "empty_content": not (content or "").strip(),
            "recovered_call_reason": recovered_call_reason,
            "usage": _usage_from_response(response) if response is not None else None,
        })

    def tool_call(self, turn: int, tool_call_id: str, name: str, arguments: Any) -> None:
        self._emit("tool_call", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "arguments": arguments,
        })

    def tool_result(self, turn: int, tool_call_id: str, name: str,
                    result: str, error_reason: str | None = None) -> None:
        self._emit("tool_result", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "result": result or "",
            "result_len": len(result or ""),
            "error_reason": error_reason,
        })

    def nudge(self, turn: int, reason: str, attempt: int, max_attempts: int) -> None:
        self._emit("nudge", {
            "turn": turn,
            "reason": reason,
            "attempt": attempt,
            "max_attempts": max_attempts,
        })

    def final_answer(self, turn: int, content: str) -> None:
        self._emit("final_answer", {"turn": turn, "content": content or ""})

    def run_end(self, outcome: str, turns_used: int, error: str | None = None) -> None:
        """`outcome` is one of: `final_answer`, `gave_up`, `max_turns`, `exception`."""
        self._emit("run_end", {
            "outcome": outcome,
            "turns_used": turns_used,
            "error": error,
        })

    def prompt_provenance(self, components: dict, ablation_flags: dict | None = None) -> None:
        """The meta-meta-trace: WHAT SHAPED this run. `components` maps each
        prompt component name (agents_md, skills, tool_workflow, role_prompt,
        tools_schema, …) to its content string; hashed here so traces can be
        grouped/diffed by prompt composition without storing full text.
        Level 1 of the trace = what the agent did; level 2 = what it
        consumed/produced; level 3 (this event) = what influenced it.
        Attribution studies (ablate skills/AGENTS.md, correlate with
        behavioral markers) GROUP BY these hashes."""
        hashed = {}
        for name, content in components.items():
            if content is None:
                hashed[name] = None  # component absent this run (ablated or missing)
            else:
                data = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
                hashed[name] = {
                    "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(),
                    "bytes": len(data.encode("utf-8")),
                }
        self._emit("prompt_provenance", {
            "components": hashed,
            "ablation_flags": ablation_flags or {},
        })

    def delegate(self, stage: str, sub_run_id: str | None,
                 input_summary: str, outcome: str,
                 output_summary: str | None = None) -> None:
        """Orchestrator-only event: 'the orchestrator delegated `stage` to a
        specialist, which produced sub_run_id (if it involved an LLM),
        with the given outcome'. Ties the multi-agent tree together —
        readers walk from an orchestrator trace to each specialist's
        trace by run_id. Pure-Python stages (no LLM) leave sub_run_id
        as None."""
        self._emit("delegate", {
            "stage": stage,
            "sub_run_id": sub_run_id,
            "input_summary": input_summary,
            "outcome": outcome,
            "output_summary": output_summary,
        })
