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
import sys
import time

import httpx
from litellm import completion
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Add repo root to sys.path so `sql_benchmarks.agent_trace` imports when the
# script is run without `pip install -e .`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sql_benchmarks.agent_trace import AgentTrace

# Load .env from repo root (script sits in scripts/, so go up one) then cwd.
# Silent no-op if the files don't exist. Explicit key check happens later —
# a missing .env doesn't crash the script; a missing key for the chosen
# model does, with a clear error.
try:
    from dotenv import load_dotenv
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    load_dotenv()  # current working dir
except ImportError:
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("[warning] python-dotenv not installed; .env files will NOT be auto-loaded. "
          "Install with: pip install python-dotenv", file=sys.stderr)

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
            "name": "list_categories",
            "description": "List the taxonomy of experiment categories (scaling, cross-engine, analytical, join, selectivity, null-handling, transport, memory, columnar, security, recursion, transactional). SMALL payload — CALL THIS FIRST to figure out which slice of the suite space matches the goal, then call `list_suites(category=<name>)` to see only the suites tagged with that category.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_suites",
            "description": "List benchmark test suites. Default response is SMALL: name, engines, benchmark_names, categories per suite (no SQL). ALWAYS start with `list_categories` and pass `category` here to narrow — an unfiltered call returns every suite in the catalog. Set `include_sql=true` ONLY if you specifically need the raw SQL text (adds many KB per suite). Prefer `get_template` for adapting a working config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter to suites tagged with this category (from list_categories)."},
                    "include_sql": {"type": "boolean", "description": "Include raw SQL per engine. Default false — expensive."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "List curated experiment templates. Each is a human-authored, VALID config demonstrating a working (dataset shape + suite + engines) combination. STRONGLY RECOMMENDED before constructing YAML from scratch — the templates show you what dataset each suite expects.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_template",
            "description": "Fetch the full YAML text of a named template (from `list_templates`). Adapt this text (change engines, scale, matrix values) and submit via `submit_experiment`. Preferred over constructing YAML from scratch — the template already matches its suite's SQL schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Template name (stem without .yaml) — the `name` field from `list_templates` output."
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_experiment",
            "description": "Submit a new benchmark experiment as a YAML string. Returns an experiment_id. You MUST use valid YAML matching the required schema. RECOMMENDED workflow: `get_template` first, adapt the returned YAML, then submit — this ensures the dataset shape matches the suite's SQL contract.",
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
            "description": "Get a ranked cross-engine performance comparison for a completed experiment. AGGREGATES across all partitions — good for 'who won overall' questions, but flattens scaling curves. For matrix-sweep or scaling analysis, use `compare_engines_by_partition` instead.",
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
            "name": "compare_engines_by_partition",
            "description": "Get per-PARTITION cross-engine rankings for a completed experiment — one ranking per partition key. USE THIS for scaling analysis (e.g., 'how does DuckDB scale from 100 to 1M rows?') and matrix-sweep experiments where the aggregate hides the shape. Returns a dict keyed by partition name.",
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
            "name": "get_experiment_result",
            "description": "Fetch the full raw experiment result: sealed config + summary + all per-partition, per-engine fragments (each with mean, median, p95, and raw per-replication durations). USE THIS when you need to reason from raw measurements — anything beyond 'who won'. Larger response than compare_engines; prefer compare_engines for simple ranking questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string"}
                },
                "required": ["experiment_id"]
            }
        }
    },
    # --- Granular projections (small returns) -------------------------------
    # Prefer these over `get_experiment_result` when the question is
    # specific and the context budget is tight. Each returns a small,
    # focused payload with a `provenance` block naming the fragments
    # consumed. See sql_benchmarks/api/logic/projections.py.
    {
        "type": "function",
        "function": {
            "name": "get_experiment_summary",
            "description": "PREFER THIS as the FIRST read of a completed experiment: a compact digest with config identity, means per (partition, engine), scaling ratios per engine, and a prose `narrative`. Machine-readable AND readable. Small payload — safe under tight context budgets. Use `get_experiment_result` only if you need the raw fragments.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_means_by_partition",
            "description": "Mean duration per (partition, engine). Cheap, focused projection when the question is 'who was faster on partition X'. Smaller than `compare_engines_by_partition` — no rankings, no speedups, just means + sample counts.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_scaling_factor",
            "description": "Per-engine adjacent + overall scaling ratios across partitions. Use for 'how does X scale from small to large?' questions — this returns the RATIOS directly (mean_last/mean_first, adjacent ratios), sparing you the in-context arithmetic. Partitions ordered alphabetically; check `partitions_order` in the response — if the semantic order differs (small→medium→large vs alpha's 'large,medium,small'), reinterpret.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_replication_stability",
            "description": "Per (partition, engine): std, coefficient of variation, min, max across the raw per-replication durations. Use when the question is 'how noisy is this measurement' or 'can I trust these numbers'. If sample_count=1 and std=0, that fragment predates raw-durations capture — stability not measurable from what was stored.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"]
            }
        }
    }
]

# Set of legal tool names, used to reject hallucinated tool calls before we
# dispatch them into the API.
KNOWN_TOOLS = {t["function"]["name"] for t in TOOLS}


# --- API key + protocol-doc loading -----------------------------------------

# Mapping of model-string prefix to the environment variable litellm expects.
# `ollama/*` and `local/*` need no key. Anything not matched is left to
# litellm to sort out (which may still crash with an unhelpful error — but
# that's outside this script's scope).
_KEY_BY_PREFIX = {
    "gpt-": "OPENAI_API_KEY",
    "openai/": "OPENAI_API_KEY",
    "chatgpt-": "OPENAI_API_KEY",
    "o1-": "OPENAI_API_KEY",
    "o3-": "OPENAI_API_KEY",
    "gemini/": "GEMINI_API_KEY",  # litellm accepts GOOGLE_API_KEY too; we check both
    "claude-": "ANTHROPIC_API_KEY",
    "anthropic/": "ANTHROPIC_API_KEY",
    "command-": "COHERE_API_KEY",
    "cohere/": "COHERE_API_KEY",
    "mistral/": "MISTRAL_API_KEY",  # different from ollama/mistral
}


def check_api_key(model: str) -> None:
    """Verify the appropriate API key is set for the requested model. Exits
    with a clear message if not — beats letting litellm produce a cryptic
    stack trace 30 seconds later.

    Local models (`ollama/*`, `local/*`) need no key; skipped."""
    if model.startswith(("ollama/", "local/")):
        return
    for prefix, env_var in _KEY_BY_PREFIX.items():
        if model.startswith(prefix):
            if os.getenv(env_var):
                return
            # gemini also accepts GOOGLE_API_KEY
            if env_var == "GEMINI_API_KEY" and os.getenv("GOOGLE_API_KEY"):
                return
            raise SystemExit(
                f"[error] Model '{model}' requires environment variable {env_var}, "
                f"which is not set. Set it in your shell or in a .env file at "
                f"{os.path.join(_REPO_ROOT, '.env')} and try again."
            )
    # Unrecognized prefix — warn but don't block; litellm may handle it.
    print(f"[warning] Model '{model}' has no known key requirement in this script. "
          f"If litellm errors below, verify the appropriate credential env var is set.",
          file=sys.stderr)


def load_agents_md() -> str:
    """Read repo-root AGENTS.md if it exists. Returns its contents or None.
    Standalone Python scripts do NOT auto-load AGENTS.md the way harnesses like
    Claude Code or Cursor do — this function is the explicit substitute."""
    path = os.path.join(_REPO_ROOT, "AGENTS.md")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return None


def load_skills() -> str:
    """Concatenate every `.md` file in `skills/` into one string. Skills are
    precise procedures for specific operations (build a scaling experiment,
    read results with the right tool). AGENTS.md is the high-level protocol;
    skills are the tactical playbook. Returns "" if the dir is missing or
    empty."""
    skills_dir = os.path.join(_REPO_ROOT, "skills")
    if not os.path.isdir(skills_dir):
        return ""
    parts = []
    for fn in sorted(os.listdir(skills_dir)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(skills_dir, fn), encoding="utf-8") as f:
            parts.append(f.read())
    return "\n\n---\n\n".join(parts)


def execute_tool(name: str, args: dict) -> str:
    """Dispatches the tool call to the REST API."""
    try:
        if name == "list_categories":
            res = httpx.get(f"{API_BASE}/v1/catalog/categories", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "list_suites":
            params = {}
            if args.get("category"):
                params["category"] = args["category"]
            if args.get("include_sql"):
                params["include_sql"] = "true"
            res = httpx.get(f"{API_BASE}/v1/catalog/suites", params=params, timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "list_templates":
            res = httpx.get(f"{API_BASE}/v1/catalog/templates", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_template":
            res = httpx.get(f"{API_BASE}/v1/catalog/templates/{args['name']}", timeout=30)
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

        elif name == "compare_engines_by_partition":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/compare/by-partition", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_experiment_result":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_experiment_summary":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/projections/summary", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_means_by_partition":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/projections/means", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_scaling_factor":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/projections/scaling", timeout=30)
            return json.dumps(res.json(), indent=2)

        elif name == "get_replication_stability":
            res = httpx.get(f"{API_BASE}/v1/results/{args['experiment_id']}/projections/stability", timeout=30)
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


def build_system_prompt(include_agents_md: bool = True,
                        include_skills: bool = True) -> tuple:
    """Compose the system prompt from AGENTS.md (the authoritative protocol
    doc) plus this script's tool-specific workflow. If AGENTS.md is missing,
    fall back to a minimal built-in workflow with a schema example.

    `include_agents_md` / `include_skills` are ABLATION FLAGS for the
    attribution study (scratch/reducing_agent_search_scope.md): which
    guidance layer actually drives behavior? Returns `(prompt, components)`
    where `components` maps each layer's name to its content (or None if
    absent/ablated) — fed to AgentTrace.prompt_provenance."""
    agents_md = load_agents_md() if include_agents_md else None

    tool_workflow = (
        "## This Agent's Tools & Workflow\n\n"
        "You are an autonomous Data Engineering AI. Answer the user's performance question "
        "by using ONLY the REST-API-backed tools below.\n\n"
        f"Registered tools (never invent names outside this set): {sorted(KNOWN_TOOLS)}\n\n"
        "Loop:\n"
        "0. `list_categories` — small taxonomy lookup. START HERE. Match the goal to one or more categories, then narrow.\n"
        "1. `list_suites(category=<name>)` — see suites tagged with that category (names + engines + benchmark names, NO SQL by default). "
        "The user's goal may name a suite that doesn't exist; if so, pick the closest match "
        "from what `list_suites` returns and note the substitution in your final answer. "
        "Only pass `include_sql=true` if you truly need to reason about the SQL itself.\n"
        "2. `list_templates` — see human-authored, VALID example configs. Each demonstrates a "
        "working (dataset shape + suite + engines) combination. This is your best defense against "
        "'shooting in the dark': every SQL suite expects specific tables and columns, and the templates "
        "show you exactly what shape works.\n"
        "3. `get_template <name>` — fetch the full YAML text of a matching template. STRONGLY PREFER "
        "adapting an existing template over writing YAML from scratch. The template already matches its "
        "suite's SQL contract; you would have to reverse-engineer that contract from the SQL otherwise.\n"
        "4. `submit_experiment` — submit the adapted YAML. If it returns a schema error, read the error, "
        "fix the specific field named, and retry. If a run comes back `failed`, read the `detail` — it "
        "carries the actual executor error (e.g., a DB message like 'Catalog Error: Table with name c "
        "does not exist' means your dataset is missing that table). Do NOT stop on the first error.\n"
        "5. `get_experiment_status` — poll until status is `complete` or `failed`. Pauses are handled automatically.\n"
        "6. Read the result. PICK THE RIGHT SHAPE for the question:\n"
        "   - `get_experiment_summary` — ALWAYS THE FIRST READ. Compact digest: means + scaling + narrative in a small payload. Safe under tight context budgets.\n"
        "   - `get_means_by_partition` — mean + sample count per (partition, engine). Cheap when the question is per-partition speed.\n"
        "   - `get_scaling_factor` — adjacent + overall scaling ratios PER ENGINE. Returns ratios directly; spares in-context arithmetic. Check `partitions_order` if semantic ordering matters.\n"
        "   - `get_replication_stability` — std, CV, min, max per (partition, engine). Use for 'how noisy is this measurement'.\n"
        "   - `compare_engines` — aggregate ranking across all partitions. For 'who won overall'; flattens scaling curves.\n"
        "   - `compare_engines_by_partition` — per-partition rankings + speedups.\n"
        "   - `get_experiment_result` — full raw fragments. Use only when projections above don't answer.\n"
        "   See `skills/read_experiment_results.md` for the full decision table.\n"
        "7. Produce a final Markdown analysis with `FINAL ANSWER:` at the top, naming the winning "
        "engine (or per-scale answer), the numbers that support it, and any caveats.\n\n"
        "If you have all the data and are ready to conclude, produce the final analysis. "
        "Do NOT return an empty message.\n"
    )

    skills = load_skills() if include_skills else ""
    skills_block = (
        "\n\n---\n\n# Skills (precise procedures for specific operations)\n\n"
        + skills
        if skills
        else ""
    )

    components = {
        "agents_md": agents_md,
        "tool_workflow": tool_workflow,
        "skills": skills or None,
        "tools_schema": TOOLS,
    }

    if agents_md:
        prompt = (
            "# Protocol Document (loaded from AGENTS.md at repo root)\n\n"
            + agents_md
            + "\n\n---\n\n"
            + tool_workflow
            + skills_block
        )
        return prompt, components

    # Fallback: minimal built-in when AGENTS.md is missing. Preserves the
    # concrete YAML example so this script still works standalone.
    prompt = (
        tool_workflow
        + "\n\n## Schema Example (AGENTS.md not found; embedded fallback)\n\n"
        "```yaml\n"
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
        "  engines: [duckdb, postgres]\n"
        "  replication: 1\n"
        "  matrix:\n"
        "    rows: [test_scale]\n"
        "```\n"
        + skills_block
    )
    return prompt, components


def run_agent(goal: str, model: str = "gpt-4o",
              include_agents_md: bool = True, include_skills: bool = True,
              study_stamp: dict | None = None):
    """`study_stamp` ({study_id, cell, rep}) is set when this run belongs
    to a contract-driven study (scripts/run_study.py) — recorded in the
    trace's provenance so the trace is traceable to the exact study
    contract that produced it."""
    console.print(Panel(f"[bold cyan]GOAL:[/bold cyan] {goal}", title="🤖 Agent Initialized"))

    system_prompt, prompt_components = build_system_prompt(
        include_agents_md=include_agents_md, include_skills=include_skills)
    agents_md_loaded = prompt_components["agents_md"] is not None
    console.print(f"[dim]System prompt: AGENTS.md {'loaded' if agents_md_loaded else 'ABSENT (missing or ablated)'} "
                  f"| skills {'loaded' if prompt_components['skills'] else 'ABSENT'} "
                  f"| Model: {model}[/dim]")

    trace = AgentTrace(
        goal=goal, model=model,
        agents_md_loaded=agents_md_loaded, max_turns=MAX_TURNS,
    )
    trace.prompt_provenance(
        components=prompt_components,
        ablation_flags={
            "architecture": "monolith",
            "include_agents_md": include_agents_md,
            "include_skills": include_skills,
            **(study_stamp or {}),
        },
    )
    console.print(f"[dim]Agent trace: {trace.path}[/dim]")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal}
    ]

    empty_responses_in_a_row = 0

    for turn in range(1, MAX_TURNS + 1):
        console.print(f"[dim]Thinking... (turn {turn}/{MAX_TURNS})[/dim]")
        trace.turn_start(turn)

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

        trace.model_response(
            turn=turn, content=content, tool_calls=msg.tool_calls or [],
            response=response, recovered_call_reason=recovery_reason,
        )

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
                trace.final_answer(turn=turn, content=content)
                trace.run_end(outcome="final_answer", turns_used=turn)
                break

            if empty_responses_in_a_row >= MAX_EMPTY_RESPONSES:
                console.print(
                    f"[bold red]✗ Agent gave up after {MAX_EMPTY_RESPONSES} non-actionable responses in a row.[/bold red]"
                )
                trace.run_end(outcome="gave_up", turns_used=turn)
                break

            console.print(f"[yellow]Nudging model (attempt {empty_responses_in_a_row}/{MAX_EMPTY_RESPONSES})…[/yellow]")
            trace.nudge(turn=turn,
                        reason=("recovery" if recovery_reason
                                else "empty" if not content.strip()
                                else "no_tool_call_no_final"),
                        attempt=empty_responses_in_a_row,
                        max_attempts=MAX_EMPTY_RESPONSES)
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

            trace.tool_call(turn=turn, tool_call_id=tool_call.id, name=name, arguments=args)
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
            trace.tool_result(turn=turn, tool_call_id=tool_call.id, name=name,
                              result=result_str, error_reason=error_reason)

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
        trace.run_end(outcome="max_turns", turns_used=MAX_TURNS)


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
    parser.add_argument(
        "--no-agents-md", action="store_true",
        help="ABLATION: omit AGENTS.md from the system prompt (attribution study)."
    )
    parser.add_argument(
        "--no-skills", action="store_true",
        help="ABLATION: omit the skills block from the system prompt (attribution study)."
    )
    args = parser.parse_args()
    # Fail fast if the required API key for the chosen model is missing.
    check_api_key(args.model)
    run_agent(args.goal, model=args.model,
              include_agents_md=not args.no_agents_md,
              include_skills=not args.no_skills)
