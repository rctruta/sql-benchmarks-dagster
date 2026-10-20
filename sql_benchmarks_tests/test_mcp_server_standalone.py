"""The MCP server must be useful with nothing else running.

Written after noticing every tool proxied http://localhost:8000, so a freshly
installed server could not answer a single question until the user also started
a REST API. Nine of the ten tools are backed by pure filesystem readers, so the
network hop was overhead inherited from the API layer.
"""
import asyncio

import pytest

from sql_benchmarks.mcp import server


def _call(tool, *a, **kw):
    """FastMCP wraps tools; reach the underlying coroutine either way."""
    fn = getattr(tool, "fn", tool)
    return asyncio.run(fn(*a, **kw))


def test_read_tools_work_with_no_api_running():
    """The whole point: no server, no port, still answers."""
    assert server.API_BASE is None, "test assumes SB_API_BASE is unset"
    out = _call(server.list_categories)
    assert "categories" in out and out["categories"], out


def test_engines_come_from_the_filesystem():
    out = _call(server.list_engines)
    names = {e["name"] for e in out["engines"]}
    assert "duckdb" in names, names


def test_submit_refuses_rather_than_silently_losing_the_run():
    """In-process, a BackgroundTask would block for the entire experiment and
    die with this server. Refusing is honest; pretending to submit is not."""
    out = _call(server.submit_experiment, "meta:\n  name: x\n")
    assert "error" in out
    assert "requires a running REST API" in out["error"]
    assert "fix" in out and "SB_API_BASE" in out["fix"], "must say how to fix it"


def test_api_base_is_not_defaulted_to_localhost():
    """A default of http://localhost:8000 is what made the server look broken
    on a clean install -- it silently pointed at a port nobody was serving."""
    import inspect
    src = inspect.getsource(server)
    assert 'os.getenv("SB_API_BASE")' in src
    assert 'os.getenv("SB_API_BASE", "http://localhost:8000")' not in src
