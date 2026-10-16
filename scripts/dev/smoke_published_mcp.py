#!/usr/bin/env python3
"""Prove the PUBLISHED MCP server works on a cold install, with no infrastructure.

    python3 scripts/dev/smoke_published_mcp.py

This does not test this checkout. It installs `sqlbenchdag` from PyPI with
`uvx` and speaks MCP to it over stdio, which is exactly what a stranger's
machine does and the only path anyone outside this repository can use.

Why it exists. There are two MCP servers here and they are separate code with
separate requirements: `mcp_server.py` at the repository root is an httpx
client and needs the REST API running, while `sql_benchmarks.mcp.server` --
the `sqlbench-mcp` console script the wheel declares -- reads the committed
capsules directly and needs nothing. AGENTS.md documented only the first, so
the published entry point was both undocumented here and already being
advertised elsewhere as standalone. Nothing checked that it was.

This job tests an artifact on PyPI rather than the commit that triggered it, so
it can go red without anybody changing code -- a bad release, a yanked version,
a dependency that stopped resolving. That is the point: it answers "can a
stranger install this today", which no test of this working tree can answer.
It therefore runs on a schedule and on demand, never on push.
"""
import json
import os
import shutil
import subprocess
import sys
import time

PACKAGE = "sqlbenchdag"
SCRIPT = "sqlbench-mcp"
PROTOCOL = "2024-11-05"
DEADLINE = float(os.environ.get("SMOKE_DEADLINE", "240"))

REQUESTS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
]


def die(msg, proc=None, stderr_path=None):
    print(f"\nFAIL: {msg}", file=sys.stderr)
    if stderr_path and os.path.exists(stderr_path):
        tail = open(stderr_path, errors="ignore").read()[-2500:]
        print(f"\n--- server stderr (tail) ---\n{tail}", file=sys.stderr)
    if proc and proc.poll() is None:
        proc.kill()
    sys.exit(1)


def main():
    if not shutil.which("uvx"):
        die("uvx is not on PATH; install uv first (astral.sh/uv)")

    err = open("/tmp/smoke_mcp_stderr.log", "w")
    proc = subprocess.Popen(
        ["uvx", "--quiet", "--refresh", "--from", PACKAGE, SCRIPT],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
    )

    try:
        for r in REQUESTS:
            proc.stdin.write(json.dumps(r) + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        die("the server exited before accepting the handshake", proc,
            "/tmp/smoke_mcp_stderr.log")

    # --refresh forces a real download, so first byte can take a while.
    replies, start = {}, time.monotonic()
    while len(replies) < 2 and time.monotonic() - start < DEADLINE:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue                      # banners and logs are not our business
        if isinstance(msg.get("id"), int):
            replies[msg["id"]] = msg

    proc.kill()
    err.close()
    log = "/tmp/smoke_mcp_stderr.log"

    if 1 not in replies:
        die(f"no initialize response within {DEADLINE:.0f}s", proc, log)
    init = replies[1]
    if "error" in init:
        die(f"initialize returned an error: {init['error']}", proc, log)

    res = init.get("result", {})
    info = res.get("serverInfo", {})
    if not info.get("name"):
        die(f"initialize carried no serverInfo.name: {res}", proc, log)
    if not res.get("protocolVersion"):
        die(f"initialize carried no protocolVersion: {res}", proc, log)

    if 2 not in replies:
        die(f"handshake succeeded but tools/list never answered within "
            f"{DEADLINE:.0f}s -- a server that cannot list its tools is not "
            f"usable by an agent", proc, log)
    tools = replies[2].get("result", {}).get("tools", [])
    if not tools:
        die("tools/list returned an empty list", proc, log)

    for t in tools:
        if not t.get("name"):
            die(f"a tool has no name: {t}", proc, log)
        if not t.get("description"):
            die(f"tool {t['name']!r} has no description -- an agent choosing "
                f"between tools has nothing to choose on", proc, log)

    print(f"cold install of {PACKAGE} answered MCP with no REST API running")
    print(f"  server:   {info.get('name')} {info.get('version', '')}".rstrip())
    print(f"  protocol: {res.get('protocolVersion')}")
    print(f"  tools:    {len(tools)}")
    for t in sorted(tools, key=lambda x: x["name"]):
        print(f"    - {t['name']}")
    return 0


sys.exit(main())
