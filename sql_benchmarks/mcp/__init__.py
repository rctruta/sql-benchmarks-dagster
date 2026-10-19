"""MCP server exposing the benchmark lab as agent tools.

Lives inside the package (not at repo root) so it ships in the wheel: the
official MCP registry resolves a `pypi` package and runs its entry point, so
a server outside the distribution cannot be published there.
"""
