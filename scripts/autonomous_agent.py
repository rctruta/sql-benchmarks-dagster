#!/usr/bin/env python3
"""
Autonomous Benchmark Agent

An AI agent that acts as a Data Engineer. It uses the `sqlbenchdag` REST API
to investigate database performance hypotheses autonomously.

Patched 2026-07-03: fixes silent-exit bugs, hallucinated-tool handling,
error feedback loops, iteration ceilings. See collab doc specimen #30 (lab)
for the pattern this run was surfacing.
"""
import argparse
import json
import os
import time

import httpx
from litellm import completion
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Default to the local REST API
API_BASE = os.getenv("SB_API_BASE", "http://localhost:8000")
console = Console()

# Hard ceiling on total LLM turns — prevents infinite loops if the model
# gets stuck (e.g. polling forever, resubmitting broken YAML).
MAX_TURNS = 25
# If the model returns nothing actionable this many times in a row, give up.
MAX_EMPTY_RESPONSES = 3

# Define the tools exactly as they map to the REST API endpoints
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_suites",
            "description": "List all benchmark test suites with their SQL content per engine. Use this to understand what queries are available to test.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_experiment",
            "description": "Submit a new benchmark experiment as a YAML string. Returns an experiment_id. You MUST use valid YAML matching the required schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "config_yaml": {
                        "type": "string",
                        "description": "YAML string defining the experiment (dataset scale, engines to test, partitions)."
                    }
                },
                "required": ["config_yaml"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_status",
            "description": "Check the status of a submitted experiment using its experiment_id. Keep checking until status is 'complete'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string"}
                },
                "required": ["experiment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_engines",
            "description": "Get a ranked cross-engine performance comparison for a completed experiment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string"}
                },
                "required": ["experiment_id"]
            }
        }
    }
]

# Set of legal tool names, used to reject hallucinated tool calls before we
# dispatch them into the API.
KNOWN_TOOLS = {t["function"]["name"] for t in TOOLS}


def execute_tool(name: str, args: dict) -> str:
    """Dispatches the tool call to the REST API."""
    try:
        if name == "list_suites":
            res = httpx.get(f"{API_BASE}/v1/catalog/suites", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "submit_experiment":
            res = httpx.post(
                f"{API_BASE}/v1/experiments",
                json={"config_yaml": args["config_yaml"]},
                timeout=30
            )
            return json.dumps(res.json(), indent=2)

        elif name == "get_experiment_status":
            res = httpx.get(f"{API_BASE}/v1/experiments/{args['experiment_id']}/status", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "compare_engines":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/compare", timeout=30)
            return json.dumps(res.json(), indent=2)

        else:
            return json.dumps({"error": f"Tool '{name}' is not registered. Known tools: {sorted(KNOWN_TOOLS)}"})
    except httpx.ConnectError as e:
        return json.dumps({"error": f"Cannot reach the API at {API_BASE}. Is the sqlbenchdag server running? Details: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Tool call failed: {type(e).__name__}: {e}"})


class FakeFunction:
    """Stand-in for the litellm/openai tool function shape when we recover
    a tool call from raw text output (common with small local models)."""
    def __init__(self, n, a):
        self.name = n
        self.arguments = json.dumps(a)


class FakeToolCall:
    """Stand-in for the litellm/openai tool_call object."""
    def __init__(self, n, a):
        self.id = f"call_fake_{int(time.time() * 1000)}"
        self.function = FakeFunction(n, a)

    def model_dump(self):
        # Fixes latent bug: real tool_calls have .model_dump(); FakeToolCall
        # previously did not, so any fallback-recovered call would crash on
        # message serialization.
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


def try_recover_tool_call_from_text(text: str):
    """Best-effort extraction of a tool call embedded in a model's raw text
    output. Returns a FakeToolCall or None. Handles:

    - fenced ```json ... ``` blocks
    - top-level JSON object {"type": "function", "name": ..., "arguments": ...}
    - top-level JSON with function-nested schema {"function": {"name":..., "arguments":...}}
    - name-only shapes like {"name": "X"} (defaults arguments to {})

    Explicitly REJECTS calls to unknown tool names (hallucinated tools) —
    caller should route these through the retry loop with a coaching message
    instead of silently exiting.
    """
    if not text:
        return None, None
    raw_text = text.strip()

    # Strip markdown code fence if present
    if raw_text.startswith("```"):
        # Handle both ```json and bare ``` opening fences
        parts = raw_text.split("```")
        # parts[0] is empty (before first fence); parts[1] is the content of the first block
        if len(parts) >= 2:
            block = parts[1]
            # Drop a leading language hint (e.g. "json\n{...}")
            if block.startswith("json\n"):
                block = block[len("json\n"):]
            elif block.startswith("\n"):
                block = block[1:]
            raw_text = block.strip()

    if not (raw_text.startswith("{") and raw_text.endswith("}")):
        return None, None

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, None

    # Locate name and arguments regardless of shape
    name = parsed.get("name") or parsed.get("function", {}).get("name")
    args = parsed.get("arguments") or parsed.get("function", {}).get("arguments") or {}

    if not name:
        return None, None

    # If model produced a JSON string for arguments, try to decode
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    if not isinstance(args, dict):
        args = {}

    if name not in KNOWN_TOOLS:
        # Hallucinated tool name — return a "reject" reason so the caller
        # can coach the model instead of silently exiting.
        return None, f"model called unknown tool '{name}' (known tools: {sorted(KNOWN_TOOLS)})"

    return FakeToolCall(name, args), None


def parse_tool_result_for_error(result_str: str):
    """Return an error message if the tool result indicates a failure, else None."""
    try:
        parsed = json.loads(result_str)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        # Errors surface as {"detail": "..."} (FastAPI) or {"error": "..."} (our wrappers)
        if "error" in parsed:
            return str(parsed["error"])
        if "detail" in parsed:
            return str(parsed["detail"])
    return None


def run_agent(goal: str, model: str = "gpt-4o"):
    console.print(Panel(f"[bold cyan]GOAL:[/bold cyan] {goal}", title="🤖 Agent Initialized"))

    messages = [
        {"role": "system", "content": (
            "You are an autonomous Data Engineering AI. Your job is to answer performance questions "
            "by using the sqlbenchdag REST API tools. \n"
            "Workflow:\n"
            "1. List suites to see available queries.\n"
            "2. Write a YAML config and submit it using submit_experiment. \n\n"
            "CRITICAL SCHEMA REQUIREMENT: Your YAML MUST match this structure exactly:\n"
            "dataset:\n"
            "  source: sql_benchmarks.plugins.data_sources.declarative_gen\n"
            "  tables:\n"
            "    test_data:\n"
            "      rows: rows\n"
            "      columns:\n"
            "        - name: id\n"
            "          provider: sequence\n"
            "definitions:\n"
            "  rows:\n"
            "    test_scale: 100000\n"
            "execution:\n"
            "  test_suite: analytical_wall\n"
            "  engines:\n"
            "    - duckdb\n"
            "    - postgres\n"
            "  replication: 1\n"
            "  matrix:\n"
            "    rows:\n"
            "      - test_scale\n\n"
            "3. If you get an API error (like SCHEMA ERROR), DO NOT STOP. Read the error, fix the YAML, and call submit_experiment again.\n"
            "4. Poll the status every 5 seconds until 'complete'.\n"
            "5. Compare engines and output a final Markdown analysis.\n"
            f"6. Only call these tools: {sorted(KNOWN_TOOLS)}. Never invent tool names."
        )},
        {"role": "user", "content": goal}
    ]

    empty_responses_in_a_row = 0

    for turn in range(1, MAX_TURNS + 1):
        console.print(f"[dim]Thinking... (turn {turn}/{MAX_TURNS})[/dim]")

        response = completion(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )

        msg = response.choices[0].message
        # Coerce None -> "" so downstream code and API don't choke.
        content = msg.content or ""

        if content:
            console.print(Panel(Markdown(content), title="🧠 Internal Monologue", border_style="blue"))

        # If no native tool_calls, try to recover one from text
        recovered_call = None
        recovery_reason = None
        if not msg.tool_calls:
            recovered_call, recovery_reason = try_recover_tool_call_from_text(content)
            if recovered_call is not None:
                msg.tool_calls = [recovered_call]
                console.print(f"[dim italic]Recovered raw-text tool call: {recovered_call.function.name}[/dim italic]")

        # Assistant turn goes into history — with tool_calls if we have any,
        # otherwise plain content.
        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [t.model_dump() for t in msg.tool_calls],
            })
        else:
            messages.append({"role": "assistant", "content": content})

        # Handle the "no tool calls" path with explicit retry instead of silent exit
        if not msg.tool_calls:
            empty_responses_in_a_row += 1

            # Build a coaching message
            if recovery_reason:
                nudge = (
                    f"Your previous message tried to call a tool that does not exist ({recovery_reason}). "
                    f"You may only call one of: {sorted(KNOWN_TOOLS)}. "
                    "Retry with one of the registered tools."
                )
            elif not content.strip():
                nudge = (
                    "You returned an empty response. If the last tool call failed, read the error and fix your call. "
                    "If you have finished, produce a final Markdown analysis with your conclusion. "
                    "Do not send an empty message."
                )
            else:
                nudge = (
                    "You produced commentary but did not call a tool and did not produce a final analysis. "
                    "Either call the next tool (with valid arguments matching the schema) OR, if you have all the data you need, "
                    "produce a final Markdown analysis with 'FINAL ANSWER:' at the top."
                )

            # If the assistant explicitly wrote "FINAL ANSWER" or produced substantial content, treat as done
            done_signal = (
                "final answer" in content.lower()
                or (len(content.strip()) > 200 and empty_responses_in_a_row == 1)
            )
            if done_signal:
                console.print("[bold green]✅ Agent produced final analysis.[/bold green]")
                break

            if empty_responses_in_a_row >= MAX_EMPTY_RESPONSES:
                console.print(
                    f"[bold red]✗ Agent gave up after {MAX_EMPTY_RESPONSES} non-actionable responses in a row.[/bold red]"
                )
                break

            console.print(f"[yellow]Nudging model (attempt {empty_responses_in_a_row}/{MAX_EMPTY_RESPONSES})…[/yellow]")
            messages.append({"role": "user", "content": nudge})
            continue

        # We have tool calls — dispatch them
        empty_responses_in_a_row = 0

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
            except json.JSONDecodeError:
                args = {}

            console.print(f"[bold yellow]🛠️  Executing Tool:[/bold yellow] {name}")
            if name == "submit_experiment" and "config_yaml" in args:
                console.print(f"[dim]{args['config_yaml']}[/dim]")

            result_str = execute_tool(name, args)

            # If polling status, do the dramatic pause and continue
            if name == "get_experiment_status":
                try:
                    status = json.loads(result_str).get("status")
                except json.JSONDecodeError:
                    status = "unknown"
                console.print(f"   [italic]Status:[/italic] {status}")
                if status in ["queued", "running"]:
                    time.sleep(3)
            else:
                # Truncate for display, not for the LLM
                preview = result_str[:200] + "…" if len(result_str) > 200 else result_str
                console.print(f"[dim]Result: {preview}[/dim]")

            # If the tool returned an error, add explicit coaching after the tool result
            error_reason = parse_tool_result_for_error(result_str)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": result_str,
            })

            if error_reason:
                messages.append({
                    "role": "user",
                    "content": (
                        f"The `{name}` tool returned an error: {error_reason}\n"
                        "Read the error carefully. Adjust your call to fix the specific field or condition that failed, "
                        "then retry. Do not stop or produce a final answer until you have a successful result."
                    ),
                })
    else:
        # for/else: ran to MAX_TURNS without breaking
        console.print(f"[bold red]✗ Reached MAX_TURNS ({MAX_TURNS}) without completing. Stopping.[/bold red]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Benchmark Agent")
    parser.add_argument(
        "--model", type=str, default="ollama/llama3",
        help="The litellm model string to use (e.g., gpt-4o, ollama/llama3, ollama/mistral)"
    )
    parser.add_argument(
        "--goal", type=str,
        default=(
            "I need to know if DuckDB is faster than PostgreSQL for analytical aggregation queries. "
            "Create a benchmark using the 'analytical_wall' suite on a dataset scale of 100000 rows. "
            "Wait for the results and tell me who won."
        ),
        help="The natural-language goal to hand the agent."
    )
    args = parser.parse_args()
    run_agent(args.goal, model=args.model)
