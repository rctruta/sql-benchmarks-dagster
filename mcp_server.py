"""
SQL Benchmarks MCP Server.

Exposes the benchmark API as tools for AI agents (Claude, etc.) via the
Model Context Protocol. Requires the REST API to be running.

Usage:
    python mcp_server.py

Environment variables:
    SB_API_BASE     Base URL of the REST API (default: http://localhost:8000)
"""
import os

import httpx
from fastmcp import FastMCP

API_BASE = os.getenv("SB_API_BASE", "http://localhost:8000")
mcp = FastMCP(
    "sql-benchmarks",
    instructions=(
        "SQL Benchmarks Lab: ground-truth database performance data. "
        "Use these tools to answer questions like 'which engine is fastest for aggregations on 10M rows?' "
        "without running any queries yourself. Results are pre-computed with cold-cache isolation."
    ),
)


@mcp.tool()
def list_engines() -> dict:
    """
    List all available database engines (postgres, duckdb, actian) and the
    benchmark test suites each engine has SQL for.
    """
    return httpx.get(f"{API_BASE}/v1/catalog/engines").json()


@mcp.tool()
def list_suites(category: str, include_sql: bool = False) -> dict:
    """
    List benchmark test suites for a specific category.
    Suites include: analytical_wall, group_by, joins, null_logic, null_sentinel,
    recursion, selectivity, tpch, acid_test.
    
    Args:
        category: Required filter by category (e.g. "scaling"). Use list_categories to find valid options.
        include_sql: If true, include the raw SQL per engine (can be large).
    """
    params = {"category": category}
    if include_sql: params["include_sql"] = "true"
    return httpx.get(f"{API_BASE}/v1/catalog/suites", params=params).json()


@mcp.tool()
def list_results(suite: str = None, engine: str = None) -> dict:
    """
    List completed benchmark experiments.

    Args:
        suite: Optional filter by test suite name (e.g. "analytical_wall").
        engine: Optional filter by engine name (e.g. "duckdb").
    """
    params = {k: v for k, v in {"suite": suite, "engine": engine}.items() if v}
    return httpx.get(f"{API_BASE}/v1/results", params=params).json()


@mcp.tool()
def analyze_experiment(experiment_id: str, intent: str, partition: str = None) -> dict:
    """
    Analyze a completed experiment. Choose the right intent for your question.
    
    Intents:
    - "summary": Compact digest (means + scaling + narrative). Start here.
    - "means": Mean duration per partition/engine.
    - "scaling": Pairwise scaling factors across partitions.
    - "stability": Std dev, min, max, CV for reliability questions.
    - "compare": Ranked cross-engine comparison. (Can filter by `partition`).
    - "compare_by_partition": Ranked comparison broken down per partition.
    - "raw": The full raw JSON payload (use ONLY if projections aren't enough).
    
    Args:
        experiment_id: 8-character experiment ID.
        intent: The type of analysis to perform.
        partition: Optional partition key. Only used if intent is "compare".
    """
    if intent == "summary":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/projections/summary").json()
    elif intent == "means":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/projections/means").json()
    elif intent == "scaling":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/projections/scaling").json()
    elif intent == "stability":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/projections/stability").json()
    elif intent == "compare":
        params = {"partition": partition} if partition else {}
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/compare", params=params).json()
    elif intent == "compare_by_partition":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/compare/by-partition").json()
    elif intent == "raw":
        return httpx.get(f"{API_BASE}/v1/results/{experiment_id}").json()
    else:
        return {"error": f"Unknown intent: {intent}"}


@mcp.tool()
def recommend_engine(suite: str = None, scale: str = None) -> dict:
    """
    Get an engine recommendation based on pre-computed benchmark data.
    Returns the fastest engine for the given workload with confidence level and reasoning.

    Args:
        suite: Test suite name representing the workload type
               (e.g. "analytical_wall", "joins", "selectivity").
        scale: Partition key substring to filter by data scale
               (e.g. "large", "medium", "1000000").
    """
    params = {k: v for k, v in {"suite": suite, "scale": scale}.items() if v}
    return httpx.get(f"{API_BASE}/v1/recommend", params=params).json()


@mcp.tool()
def submit_experiment(config_yaml: str) -> dict:
    """
    Submit a new benchmark experiment. The experiment will run asynchronously.
    Use get_experiment_status() to poll for completion, then get_result() to
    retrieve data.

    If this exact experiment has been run before (same config + SQL + code),
    it returns status "duplicate" and you can immediately call get_result().

    CRITICAL: For dataset.tables.*.rows, you MUST use a string alias that maps 
    to definitions.rows, NOT a literal integer. Literal integers will be rejected.

    Args:
        config_yaml: YAML string defining the experiment (dataset, engines, matrix).
    """
    return httpx.post(
        f"{API_BASE}/v1/experiments",
        json={"config_yaml": config_yaml},
        timeout=30,
    ).json()


@mcp.tool()
def get_experiment_status(experiment_id: str) -> dict:
    """
    Check the status of a submitted experiment.
    Status values: "queued", "running", "complete", "not_found".

    Args:
        experiment_id: 8-character experiment ID returned by submit_experiment().
    """
    return httpx.get(f"{API_BASE}/v1/experiments/{experiment_id}/status").json()


@mcp.tool()
def list_categories() -> dict:
    """
    List the category taxonomy to narrow down test suites.
    Small payload — call this FIRST to narrow the suite search.
    """
    return httpx.get(f"{API_BASE}/v1/catalog/categories").json()


@mcp.tool()
def list_templates() -> dict:
    """
    List curated experiment templates. Each is a valid, human-authored
    config you can get_template(name) and adapt.
    """
    return httpx.get(f"{API_BASE}/v1/catalog/templates").json()


@mcp.tool()
def get_template(name: str) -> dict:
    """
    Return the raw YAML content of a template by name.
    
    Args:
        name: Name of the template from list_templates().
    """
    return httpx.get(f"{API_BASE}/v1/catalog/templates/{name}").json()





if __name__ == "__main__":
    mcp.run()
