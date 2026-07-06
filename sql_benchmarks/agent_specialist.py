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
    continues (more tool calls / more turns).

    `tool_preconditions` maps a tool name to `(required_prior_tool,
    coaching_message)`. The loop MECHANICALLY refuses to dispatch the
    tool until the required prior tool has been called successfully at
    least once this run — the model gets the coaching message as the
    tool result instead. Live-fire lesson (llama3, 2026-07-05): prompt
    exhortation ("adapt a template, don't write YAML from scratch") does
    not bind on weak models; a procedural gate does."""
    name: str
    tool_names: list[str]
    system_prompt: str
    max_turns: int = 20
    parse_output: Optional[Callable[[str, list], Optional[dict]]] = None
    tool_preconditions: dict = field(default_factory=dict)


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


class _RecoveredCall:
    """Duck-typed stand-in for a litellm tool-call object, produced when we
    recover a tool call from raw text output (common with small local
    models that emit the JSON as text instead of a native tool call)."""
    _counter = 0

    def __init__(self, name: str, args: dict):
        _RecoveredCall._counter += 1
        self.id = f"recovered_{_RecoveredCall._counter}"

        class _Fn:
            pass
        self.function = _Fn()
        self.function.name = name
        self.function.arguments = json.dumps(args)

    def model_dump(self):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


# Key variants weak models use for the tool name when emitting JSON-as-text.
# llama3 live-fire 2026-07-05 used "function_name"; the monolith's recovery
# only knew "name"/"function.name" and missed it.
_NAME_KEYS = ("name", "function_name", "tool", "tool_name")


def try_recover_tool_call_from_text(text: str, allowed_tools: set):
    """Best-effort extraction of a tool call from raw model text. Returns
    `(call, reject_reason)` — exactly one is non-None, or both None if the
    text isn't call-shaped at all. Handles fenced ```json blocks and the
    name-key variants in `_NAME_KEYS`. Rejects (with a reason, for
    coaching) names outside `allowed_tools`."""
    if not text:
        return None, None
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            block = parts[1]
            if block.startswith("json\n"):
                block = block[len("json\n"):]
            raw = block.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return None, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None

    name = None
    for key in _NAME_KEYS:
        if isinstance(parsed.get(key), str):
            name = parsed[key]
            break
    if name is None and isinstance(parsed.get("function"), dict):
        name = parsed["function"].get("name")
    if not name:
        return None, None

    args = parsed.get("arguments") or parsed.get("function", {}).get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    if name not in allowed_tools:
        return None, f"model called unknown tool '{name}' (allowed: {sorted(allowed_tools)})"
    return _RecoveredCall(name, args), None


def _extract_error(result_str: str) -> Optional[str]:
    """Detect an error in a tool result. Tool results are JSON; errors
    carry an `error` key (execute_tool's shape) or a `detail` key with
    4xx semantics (FastAPI's shape)."""
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        if data.get("error"):
            return str(data["error"])
        # FastAPI validation errors surface as `detail`
        if data.get("detail") and not data.get("experiment_id"):
            return str(data["detail"])
    return None


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
    # Meta-meta-trace: record exactly what shaped this specialist —
    # specialists carry NO agents_md and NO skills by design (the minimal
    # guidance condition in attribution studies).
    trace.prompt_provenance(
        components={
            "agents_md": None,
            "skills": None,
            "role_prompt": role.system_prompt,
            "tools_schema": tools,
            "brief": brief,
        },
        ablation_flags={"architecture": "specialist", "role": role.name},
    )

    messages = [
        {"role": "system", "content": role.system_prompt},
        {"role": "user", "content": brief},
    ]
    empty_in_a_row = 0
    last_content = ""
    failing_call_counts: dict = {}  # (name+args signature) -> consecutive failure count
    succeeded_tools: set = set()  # tools that returned non-error at least once

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

        # Raw-text recovery: small local models emit the tool call as JSON
        # text instead of a native tool call (llama3 live-fire 2026-07-05,
        # turns 5/6/11). Recover it before counting the turn as empty.
        recovery_reason = None
        if not tool_calls:
            recovered, recovery_reason = try_recover_tool_call_from_text(
                content, allowed_tools={t["function"]["name"] for t in tools})
            if recovered is not None:
                tool_calls = [recovered]

        trace.model_response(turn=turn, content=content, tool_calls=tool_calls,
                             response=response, recovered_call_reason=recovery_reason)

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
            if recovery_reason:
                nudge_msg = (
                    f"Your message tried to call a tool that does not exist ({recovery_reason}). "
                    "Retry with one of your registered tools, as a NATIVE tool call "
                    "(not JSON text)."
                )
            else:
                nudge_msg = (
                    "You didn't call a tool. If you're done, produce your structured "
                    "output as instructed in the system prompt. Otherwise call the next tool."
                )
            messages.append({"role": "user", "content": nudge_msg})
            continue

        # Dispatch tool calls
        empty_in_a_row = 0
        for tc in tool_calls:
            args = _parse_tool_arguments(tc.function.arguments)
            trace.tool_call(turn=turn, tool_call_id=tc.id, name=tc.function.name, arguments=args)

            # Mechanical workflow gate (see SpecialistRole.tool_preconditions).
            precondition = role.tool_preconditions.get(tc.function.name)
            if precondition:
                required_tool, gate_message = precondition
                if required_tool not in succeeded_tools:
                    result_str = json.dumps({"error": gate_message})
                    trace.tool_result(turn=turn, tool_call_id=tc.id, name=tc.function.name,
                                      result=result_str, error_reason=gate_message)
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "name": tc.function.name, "content": result_str,
                    })
                    messages.append({"role": "user", "content": gate_message})
                    continue

            result_str = execute_tool(tc.function.name, args)
            error_reason = _extract_error(result_str)
            if not error_reason:
                succeeded_tools.add(tc.function.name)
            trace.tool_result(turn=turn, tool_call_id=tc.id, name=tc.function.name,
                              result=result_str, error_reason=error_reason)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": result_str,
            })

            # Error coaching — the monolithic loop had this; weak models
            # (llama3, live-fire 2026-07-05) repeat an identical failing
            # call indefinitely without it. Two layers:
            #   1. Any tool error → corrective user message naming the error
            #      and (for unknown tools) the legal tool list.
            #   2. Same (name, args) failing repeatedly → escalating breaker
            #      message; the trace records each repeat as a nudge.
            if error_reason:
                call_sig = f"{tc.function.name}:{json.dumps(args, sort_keys=True, default=str)}"
                repeat_count = failing_call_counts.get(call_sig, 0) + 1
                failing_call_counts[call_sig] = repeat_count
                if repeat_count >= 2:
                    trace.nudge(turn=turn, reason="repeated_failing_call",
                                attempt=repeat_count, max_attempts=0)
                    coaching = (
                        f"STOP. You have now made this exact call {repeat_count} times and it "
                        f"failed identically every time: `{tc.function.name}` with the same "
                        f"arguments. Repeating it again will produce the same error. "
                        f"Read the error: {error_reason}\n"
                        f"Your available tools are: {sorted(t['function']['name'] for t in tools)}. "
                        "Change your approach: pick a DIFFERENT tool or DIFFERENT arguments."
                    )
                else:
                    coaching = (
                        f"The `{tc.function.name}` call returned an error: {error_reason}\n"
                        f"Your available tools are: {sorted(t['function']['name'] for t in tools)}. "
                        "Fix the specific problem named in the error and retry."
                    )
                messages.append({"role": "user", "content": coaching})

    # Max turns without a parseable final output
    trace.run_end("max_turns", role.max_turns)
    return SpecialistResult(
        role=role.name, outcome="max_turns", output=None,
        sub_run_id=trace.run_id, turns_used=role.max_turns,
        error=f"reached max_turns={role.max_turns} without a parseable final output",
    )
