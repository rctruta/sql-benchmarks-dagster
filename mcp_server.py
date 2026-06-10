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
def list_suites() -> dict:
    """
    List all benchmark test suites with their SQL content per engine.
    Suites include: analytical_wall, group_by, joins, null_logic, null_sentinel,
    recursion, selectivity, tpch, acid_test.
    """
    return httpx.get(f"{API_BASE}/v1/catalog/suites").json()


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
def get_result(experiment_id: str) -> dict:
    """
    Get full benchmark results for a specific experiment ID, including all
    fragment timings, parameters, and config.

    Args:
        experiment_id: 8-character experiment ID (e.g. "abc12345").
    """
    return httpx.get(f"{API_BASE}/v1/results/{experiment_id}").json()


@mcp.tool()
def compare_engines(experiment_id: str, partition: str = None) -> dict:
    """
    Get a ranked cross-engine performance comparison for an experiment.
    Returns engines sorted fastest to slowest with mean/median/p95 durations.

    Args:
        experiment_id: 8-character experiment ID.
        partition: Optional partition key to filter to a specific scenario
                   (e.g. "large_ssd"). Omit to aggregate across all partitions.
    """
    params = {"partition": partition} if partition else {}
    return httpx.get(f"{API_BASE}/v1/results/{experiment_id}/compare", params=params).json()


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


if __name__ == "__main__":
    mcp.run()
