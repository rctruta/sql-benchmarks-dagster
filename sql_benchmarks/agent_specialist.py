"""One reusable specialist loop.

A specialist is a scoped LLM agent: given a `role` (name + tool subset +
system prompt) and an `input` (natural-language brief), it runs a bounded
tool-use loop and returns a structured `SpecialistResult`.

Every specialist gets its own `AgentTrace` (own `run_id`) so the multi-
agent tree can be walked from the orchestrator's trace via the
`delegate` events that name each sub-run.

Design principle: `Specialist` knows nothing about the state machine.
The orchestrator (`agent_orchestrator.py`) composes specialists into a
workflow. This keeps specialists trivially testable in isolation.
"""
from dataclasses import dataclass, field
import json
from typing import Callable, Optional

from litellm import completion

from .agent_tools import execute_tool, filter_tools
from .agent_trace import AgentTrace


MAX_EMPTY_RESPONSES = 3


@dataclass
class SpecialistRole:
    """Static definition of what a specialist does. One instance per role
    (one for config_builder, one for analyzer, etc.).

    `parse_output` is called after each model turn on the assistant text;
    if it returns a non-None dict, the specialist stops and returns that
    dict wrapped in a SpecialistResult. If it returns None, the loop
    continues (more tool calls / more turns)."""
    name: str
    tool_names: list[str]
    system_prompt: str
    max_turns: int = 20
    parse_output: Optional[Callable[[str, list], Optional[dict]]] = None


@dataclass
class SpecialistResult:
    role: str
    outcome: str  # "ok" | "gave_up" | "max_turns" | "exception"
    output: Optional[dict]
    sub_run_id: Optional[str]  # the specialist's own AgentTrace run_id
    turns_used: int
    error: Optional[str] = None


def _parse_tool_arguments(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


def run_specialist(role: SpecialistRole, brief: str, model: str) -> SpecialistResult:
    """Run one specialist to completion. Returns a structured result.

    `brief` is the user-message this specialist sees. `model` is the
    litellm model identifier. The specialist's tool inventory is the
    subset of TOOLS named in `role.tool_names`."""
    tools = filter_tools(role.tool_names)
    trace = AgentTrace(
        goal=f"[specialist:{role.name}] {brief}",
        model=model,
        agents_md_loaded=False,
        max_turns=role.max_turns,
    )

    messages = [
        {"role": "system", "content": role.system_prompt},
        {"role": "user", "content": brief},
    ]
    empty_in_a_row = 0
    last_content = ""

    for turn in range(1, role.max_turns + 1):
        trace.turn_start(turn)
        try:
            response = completion(model=model, messages=messages, tools=tools, tool_choice="auto")
        except Exception as e:
            trace.run_end("exception", turn, error=str(e))
            return SpecialistResult(
                role=role.name, outcome="exception", output=None,
                sub_run_id=trace.run_id, turns_used=turn, error=str(e),
            )

        msg = response.choices[0].message
        content = msg.content or ""
        tool_calls = msg.tool_calls or []
        last_content = content
        trace.model_response(turn=turn, content=content, tool_calls=tool_calls, response=response)

        # Append assistant turn to history
        if tool_calls:
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [t.model_dump() for t in tool_calls],
            })
        else:
            messages.append({"role": "assistant", "content": content})

        # Give parse_output a chance to detect a structured completion
        if role.parse_output is not None:
            parsed = role.parse_output(content, tool_calls)
            if parsed is not None:
                trace.final_answer(turn=turn, content=content)
                trace.run_end("final_answer", turn)
                return SpecialistResult(
                    role=role.name, outcome="ok", output=parsed,
                    sub_run_id=trace.run_id, turns_used=turn,
                )

        # No tool calls path — nudge or give up
        if not tool_calls:
            empty_in_a_row += 1
            if empty_in_a_row >= MAX_EMPTY_RESPONSES:
                trace.run_end("gave_up", turn)
                return SpecialistResult(
                    role=role.name, outcome="gave_up", output=None,
                    sub_run_id=trace.run_id, turns_used=turn,
                    error=f"specialist produced {empty_in_a_row} non-actionable responses in a row",
                )
            trace.nudge(turn=turn, reason="no_tool_call", attempt=empty_in_a_row,
                        max_attempts=MAX_EMPTY_RESPONSES)
            messages.append({
                "role": "user",
                "content": (
                    "You didn't call a tool. If you're done, produce your structured "
                    "output as instructed in the system prompt. Otherwise call the next tool."
                ),
            })
            continue

        # Dispatch tool calls
        empty_in_a_row = 0
        for tc in tool_calls:
            args = _parse_tool_arguments(tc.function.arguments)
            trace.tool_call(turn=turn, tool_call_id=tc.id, name=tc.function.name, arguments=args)
            result_str = execute_tool(tc.function.name, args)
            trace.tool_result(turn=turn, tool_call_id=tc.id, name=tc.function.name,
                              result=result_str, error_reason=None)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": result_str,
            })

    # Max turns without a parseable final output
    trace.run_end("max_turns", role.max_turns)
    return SpecialistResult(
        role=role.name, outcome="max_turns", output=None,
        sub_run_id=trace.run_id, turns_used=role.max_turns,
        error=f"reached max_turns={role.max_turns} without a parseable final output",
    )
