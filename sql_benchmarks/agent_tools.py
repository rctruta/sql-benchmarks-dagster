"""Shared tool inventory + REST dispatch used by both the monolithic
`autonomous_agent.py` and the specialist sub-agents in
`agent_orchestrator.py`. Single source of truth so tool descriptions
and dispatch stay in sync.

The `TOOLS` list is the OpenAI/litellm function-calling schema. Sub-
agents pass FILTERED subsets of this list to the model (progressive
disclosure — see scratch/reducing_agent_search_scope.md)."""
import json
import os

import httpx


API_BASE = os.getenv("SB_API_BASE", "http://localhost:8000")
_client = None


def _get_client() -> httpx.Client:
    global _client
    if _client is not None:
        return _client

    if "localhost" in API_BASE or "127.0.0.1" in API_BASE:
        try:
            from sql_benchmarks.api.app import create_app
            app = create_app()
            
            from fastapi.testclient import TestClient
            _client = TestClient(app)
            return _client
        except Exception:
            pass

    _client = httpx.Client(base_url=API_BASE)
    return _client


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
                    "category": {"type": "string"},
                    "include_sql": {"type": "boolean"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_published_capsules",
            "description": "Search the lab's PUBLISHED experiment corpus — sealed, git-tracked capsules with verified results. Returns id, suite, engines, categories, and description per capsule; optional category filter. A published capsule's results can be read directly with get_experiment_summary and the other projections, without running anything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_lab_docs",
            "description": "List the lab's published documents (README, FAQ, methodology docs, and the generated experiment catalog) — names, titles, sizes. Small payload.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_lab_doc",
            "description": "Fetch one published document's text by name (from list_lab_docs). Size-capped; truncation is stated.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "List curated experiment templates. Each is a human-authored, VALID config demonstrating a working (dataset shape + suite + engines) combination.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_template",
            "description": "Fetch the full YAML text of a named template. Adapt it and submit via `submit_experiment`.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_experiment",
            "description": "Submit a new benchmark experiment as a YAML string. Returns an experiment_id.",
            "parameters": {
                "type": "object",
                "properties": {"config_yaml": {"type": "string"}},
                "required": ["config_yaml"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_status",
            "description": "Poll the status of a submitted experiment.",
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
            "name": "compare_engines",
            "description": "Ranked cross-engine performance comparison (aggregate).",
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
            "name": "compare_engines_by_partition",
            "description": "Per-partition cross-engine rankings + speedups.",
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
            "name": "get_experiment_result",
            "description": "Full raw fragments — use only when projections don't answer.",
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
            "name": "get_experiment_summary",
            "description": "PREFER THIS as the FIRST read of a completed experiment: means + scaling + narrative in a small payload.",
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
            "description": "Mean + sample count per (partition, engine).",
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
            "description": "Adjacent + overall scaling ratios per engine.",
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
            "name": "get_means_by_benchmark",
            "description": "Mean/std per (benchmark, partition, engine) — the DISAGGREGATED view. Use when the benchmarks within a suite are themselves the objects of comparison (e.g. different NULL-handling approaches, different selectivity levels); the pooled projections average across them.",
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
            "description": "Std, CV, min, max per (partition, engine).",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"]
            }
        }
    }
]


KNOWN_TOOLS = {t["function"]["name"] for t in TOOLS}


def filter_tools(names: list[str]) -> list[dict]:
    """Return the subset of TOOLS whose function.name is in `names`.
    Sub-agents call this to build their scoped tool inventory."""
    allowed = set(names)
    return [t for t in TOOLS if t["function"]["name"] in allowed]


def execute_tool(name: str, args: dict) -> str:
    """Dispatches the tool call to the REST API. Same code path as
    autonomous_agent.py used to have; extracted here so specialists
    reuse it without importing from a script."""
    client = _get_client()
    try:
        if name == "list_lab_docs":
            res = client.get("/v1/catalog/docs", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_lab_doc":
            res = client.get(f"/v1/catalog/docs/{args['name']}", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "search_published_capsules":
            params = {}
            if args.get("category"):
                params["category"] = args["category"]
            res = client.get("/v1/catalog/published", params=params, timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "list_categories":
            res = client.get("/v1/catalog/categories", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "list_suites":
            params = {}
            if args.get("category"):
                params["category"] = args["category"]
            if args.get("include_sql"):
                params["include_sql"] = "true"
            res = client.get("/v1/catalog/suites", params=params, timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "list_templates":
            res = client.get("/v1/catalog/templates", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_template":
            res = client.get(f"/v1/catalog/templates/{args['name']}", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "submit_experiment":
            res = client.post("/v1/experiments",
                              json={"config_yaml": args["config_yaml"]}, timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_experiment_status":
            res = client.get(f"/v1/experiments/{args['experiment_id']}/status", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "compare_engines":
            res = client.get(f"/v1/results/{args['experiment_id']}/compare", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "compare_engines_by_partition":
            res = client.get(f"/v1/results/{args['experiment_id']}/compare/by-partition", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_experiment_result":
            res = client.get(f"/v1/results/{args['experiment_id']}", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_experiment_summary":
            res = client.get(f"/v1/results/{args['experiment_id']}/projections/summary", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_means_by_partition":
            res = client.get(f"/v1/results/{args['experiment_id']}/projections/means", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_scaling_factor":
            res = client.get(f"/v1/results/{args['experiment_id']}/projections/scaling", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_means_by_benchmark":
            res = client.get(f"/v1/results/{args['experiment_id']}/projections/benchmarks", timeout=30)
            return json.dumps(res.json(), indent=2)
        elif name == "get_replication_stability":
            res = client.get(f"/v1/results/{args['experiment_id']}/projections/stability", timeout=30)
            return json.dumps(res.json(), indent=2)
        else:
            return json.dumps({"error": f"Tool '{name}' is not registered. Known: {sorted(KNOWN_TOOLS)}"})
    except httpx.ConnectError as e:
        return json.dumps({"error": f"Cannot reach API at {API_BASE}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Tool call failed: {type(e).__name__}: {e}"})

