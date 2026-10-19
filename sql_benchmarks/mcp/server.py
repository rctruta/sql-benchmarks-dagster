"""
SQL Benchmarks MCP Server.

Exposes the benchmark API as tools for AI agents (Claude, etc.) via the
Model Context Protocol. Requires the REST API to be running.

Usage:
    sqlbench-mcp                      # stdio (default) — client spawns this
    sqlbench-mcp --transport http     # Streamable HTTP on :8765

TRANSPORTS
    stdio            The client launches this as a subprocess and talks over
                     stdin/stdout. Local only, no network surface, no auth to
                     get wrong. Correct default for a single user on one
                     machine, and what `.mcp.json` uses.

    streamable-http  Each message is an HTTP POST to one endpoint; replies are
                     JSON or a request-scoped SSE stream. Needed for remote or
                     hosted use, or several clients at once. Note this exposes
                     a network port with NO authentication — do not bind it to
                     a public interface as-is.

    (SSE is no longer a separate transport in the current spec; it is a
    response mode inside Streamable HTTP.)

ARCHITECTURE NOTE
    Every tool here proxies the REST API at $SB_API_BASE. That means TWO
    processes must run: the API, and this server. The API is the source of
    truth for results; this is a thin agent-facing façade over it.

Environment variables:
    SB_API_BASE     Base URL of a RUNNING REST API. Optional. When unset, the
                    read tools mount the API in-process and no server is
                    needed. Set it only when the API runs elsewhere, or to
                    submit experiments (see below).
    SB_MCP_PORT     Port for --transport http (default: 8765)
"""
import os

import httpx
from fastmcp import FastMCP

# Optional and deliberately NOT defaulted to localhost:8000. Nine of the ten
# tools below are backed by ResultReader / CatalogReader, which are pure
# filesystem readers over RESULTS_DIR, CONFIG_ARCHIVE_DIR and SQL_DIR. Sending
# those over HTTP to the same machine was overhead inherited from the API, and
# it meant a freshly installed server could not answer anything until the user
# also started a second process. Now the app is mounted in-process by default.
API_BASE = os.getenv("SB_API_BASE")

mcp = FastMCP(
    "sql-benchmarks",
    instructions=(
        "SQL Benchmarks Lab: ground-truth database performance data. "
        "Use these tools to answer questions like 'which engine is fastest for aggregations on 10M rows?' "
        "without running any queries yourself. Results are pre-computed with cold-cache isolation."
    ),
)

_ASGI_CLIENT = None


def _client() -> httpx.AsyncClient:
    """HTTP client for the lab API.

    Two modes, and the default is the one that needs no setup:

      in-process (default)  The FastAPI app is mounted via ASGITransport. Same
                            routing, same validation, same handlers -- there is
                            no second code path to drift -- but no socket, no
                            port, and no server to start.
      remote (SB_API_BASE)  A real HTTP client, for when the API runs
                            elsewhere.
    """
    global _ASGI_CLIENT
    if API_BASE:
        return httpx.AsyncClient(base_url=API_BASE, timeout=30)
    if _ASGI_CLIENT is None:
        from sql_benchmarks.api.app import create_app
        _ASGI_CLIENT = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()),
            base_url="http://sqlbench.local",
            timeout=30,
        )
    return _ASGI_CLIENT


async def _get(path: str, params: dict | None = None) -> dict:
    client = _client()
    resp = await client.get(path, params=params or {})
    return resp.json()


@mcp.tool()
async def list_engines() -> dict:
    """
    List all available database engines (postgres, duckdb, actian) and the
    benchmark test suites each engine has SQL for.
    """
    return await _get(f"/v1/catalog/engines")


@mcp.tool()
async def list_suites(category: str, include_sql: bool = False) -> dict:
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
    return await _get(f"/v1/catalog/suites", params)


@mcp.tool()
async def list_results(suite: str = None, engine: str = None) -> dict:
    """
    List completed benchmark experiments.

    Args:
        suite: Optional filter by test suite name (e.g. "analytical_wall").
        engine: Optional filter by engine name (e.g. "duckdb").
    """
    params = {k: v for k, v in {"suite": suite, "engine": engine}.items() if v}
    return await _get(f"/v1/results", params)


@mcp.tool()
async def analyze_experiment(experiment_id: str, intent: str, partition: str = None) -> dict:
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
        return await _get(f"/v1/results/{experiment_id}/projections/summary")
    elif intent == "means":
        return await _get(f"/v1/results/{experiment_id}/projections/means")
    elif intent == "scaling":
        return await _get(f"/v1/results/{experiment_id}/projections/scaling")
    elif intent == "stability":
        return await _get(f"/v1/results/{experiment_id}/projections/stability")
    elif intent == "compare":
        params = {"partition": partition} if partition else {}
        return await _get(f"/v1/results/{experiment_id}/compare", params)
    elif intent == "compare_by_partition":
        return await _get(f"/v1/results/{experiment_id}/compare/by-partition")
    elif intent == "raw":
        return await _get(f"/v1/results/{experiment_id}")
    else:
        return {"error": f"Unknown intent: {intent}"}


@mcp.tool()
async def recommend_engine(suite: str = None, scale: str = None) -> dict:
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
    return await _get(f"/v1/recommend", params)


@mcp.tool()
async def submit_experiment(config_yaml: str) -> dict:
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
    # The ONLY tool that genuinely requires a running server, and the reason
    # is not stylistic. Submitting hands the work to ExperimentCoordinator via
    # FastAPI BackgroundTasks, which needs a process that outlives the request.
    # Mounted in-process, the background task would run inside THIS request --
    # blocking until the whole experiment finished, long past any MCP client
    # timeout, and dying with the MCP server if it stopped. Refusing is
    # honest; pretending to submit and losing the run is not.
    if not API_BASE:
        return {
            "error": "submit_experiment requires a running REST API.",
            "why": (
                "Submitting starts a long-lived background job. The read tools "
                "mount the API in-process, but a background task there would "
                "block this request for the entire run and be lost if this "
                "server stopped."
            ),
            "fix": (
                "Start the API (uvicorn sql_benchmarks.api.app:create_app "
                "--factory --port 8000), then set SB_API_BASE=http://localhost:8000 "
                "and restart this MCP server."
            ),
        }
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as c:
        resp = await c.post("/v1/experiments", json={"config_yaml": config_yaml})
        return resp.json()


@mcp.tool()
async def get_experiment_status(experiment_id: str) -> dict:
    """
    Check the status of a submitted experiment.
    Status values: "queued", "running", "complete", "not_found".

    Args:
        experiment_id: 8-character experiment ID returned by submit_experiment().
    """
    return await _get(f"/v1/experiments/{experiment_id}/status")


@mcp.tool()
async def list_categories() -> dict:
    """
    List the category taxonomy to narrow down test suites.
    Small payload — call this FIRST to narrow the suite search.
    """
    return await _get(f"/v1/catalog/categories")


@mcp.tool()
async def list_templates() -> dict:
    """
    List curated experiment templates. Each is a valid, human-authored
    config you can get_template(name) and adapt.
    """
    return await _get(f"/v1/catalog/templates")


@mcp.tool()
async def get_template(name: str) -> dict:
    """
    Return the raw YAML content of a template by name.
    
    Args:
        name: Name of the template from list_templates().
    """
    return await _get(f"/v1/catalog/templates/{name}")





def main() -> None:
    """Console entry point (`sqlbench-mcp`).

    Registered in pyproject so the installed package is directly runnable —
    which is what the MCP registry's pypi package type resolves to.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="sqlbench-mcp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                    help="stdio (default, local subprocess) or http (network)")
    ap.add_argument("--port", type=int,
                    default=int(os.getenv("SB_MCP_PORT", "8765")))
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address for --transport http. Defaults to "
                         "loopback: this server has no authentication, so "
                         "binding it to 0.0.0.0 exposes the lab to the network.")
    a = ap.parse_args()

    if a.transport == "http":
        mcp.run(transport="http", host=a.host, port=a.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
