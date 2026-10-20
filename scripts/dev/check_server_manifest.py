#!/usr/bin/env python3
"""
check_server_manifest — server.json must agree with pyproject.toml and the README.

    python3 scripts/dev/check_server_manifest.py            report
    python3 scripts/dev/check_server_manifest.py --check    exit 1 on any finding
    python3 scripts/dev/check_server_manifest.py --fix      sync versions from pyproject

WHY THIS EXISTS, measured 2026-10-20.

Three separate drifts, all silent, all in the artifacts that define the public
MCP registry listing:

  1. server.json declared version 0.1.2 while pyproject.toml said 0.1.3. The
     registry had been describing an older release for as long as 0.1.3 had
     existed.

  2. server.json and the README's `mcp-name:` token were only ever committed to
     a LOCAL, unpushed branch (chore/commit-identity-gate). origin/main had
     neither. The file that defines the listing existed on one laptop.

  3. Because main lacked the token, the 0.1.3 release built from main shipped a
     README without it. Checked against PyPI: 0.1.2's description contains
     `mcp-name:`, 0.1.3's does not. The README comment carrying it says "Do not
     remove" and it was removed by absence rather than by an edit -- nobody
     deleted it, main simply never had it.

The registry will not catch any of this. Its PyPI validator (read at
internal/validators/registries/pypi.go) requires packages[].version to be
present and to EXIST on PyPI -- a 404 is rejected -- but it decodes only the
description from PyPI's response, so it never compares the declared version to
pyproject, to the server-level version, or to PyPI's latest. 0.1.2 exists, so a
stale manifest validates cleanly and publishes happily.

The standard practice this follows is the ordinary one: one source of truth for
the version, and a check that everything restating it still agrees. pyproject
is the source. The registry requires the version to be written into server.json
too, so it cannot be derived away -- which leaves asserting the agreement, and
that is what this does. `--fix` rewrites server.json from pyproject so the sync
is never a hand edit.

Constraints below are read from the published schema
(https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json),
not guessed: name maxLength 200 and pattern ^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$,
description maxLength 100, version maxLength 255 with version ranges rejected,
packages[].version must be a specific version and must not be "latest".
Description length is here because it has already bitten once: commit f4b0b80,
"server.json: description must be <= 100 chars for the registry".
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "server.json"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

# From the schema named in the manifest's own $schema field.
NAME_MAX, NAME_RE = 200, re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
DESCRIPTION_MAX = 100
VERSION_MAX = 255
RANGE_CHARS = ("^", "~", ">", "<", "*", "x")     # the schema rejects ranges
TOKEN_RE = re.compile(r"mcp-name:\s*(\S+)")


def pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    # [project] version, not a dependency's. Take the first top-level one.
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("check_server_manifest: no version in pyproject.toml")
    return m.group(1)


def findings():
    out = []
    if not MANIFEST.is_file():
        return [f"{MANIFEST.name} is missing. The MCP registry listing is "
                f"defined by this file; without it in version control the "
                f"listing cannot be reproduced."]
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{MANIFEST.name} is not valid JSON: {exc}"]

    want = pyproject_version()

    name = man.get("name", "")
    if not NAME_RE.match(name):
        out.append(f"name {name!r} does not match the schema pattern "
                   f"{NAME_RE.pattern}")
    if len(name) > NAME_MAX:
        out.append(f"name is {len(name)} chars; the schema allows {NAME_MAX}")

    desc = man.get("description", "")
    if not desc:
        out.append("description is required by the schema and is empty")
    elif len(desc) > DESCRIPTION_MAX:
        out.append(f"description is {len(desc)} chars; the registry rejects "
                   f"over {DESCRIPTION_MAX}")

    def check_version(label, value):
        if not value:
            out.append(f"{label} is empty; the registry's PyPI validator "
                       f"rejects a missing version")
            return
        if value == "latest":
            out.append(f'{label} is "latest", which the schema forbids')
        if any(c in value for c in RANGE_CHARS):
            out.append(f"{label} {value!r} looks like a range; the schema "
                       f"rejects ranges")
        if len(value) > VERSION_MAX:
            out.append(f"{label} is {len(value)} chars; max is {VERSION_MAX}")
        if value != want:
            out.append(f"{label} is {value!r} but pyproject.toml says "
                       f"{want!r}. The registry does not compare these, so "
                       f"the listing would describe the wrong release.")

    check_version("version", man.get("version", ""))
    packages = man.get("packages") or []
    if not packages:
        out.append("packages[] is empty, so the registry has nothing to install")
    for i, pkg in enumerate(packages):
        check_version(f"packages[{i}].version", pkg.get("version", ""))

    # The registry's identity check: the server name must appear in the README
    # that ships to PyPI, or publishing is rejected.
    readme = README.read_text(encoding="utf-8") if README.is_file() else ""
    token = TOKEN_RE.search(readme)
    if not token:
        out.append(f"README.md has no 'mcp-name:' token. The registry matches "
                   f"it against the server name to confirm the publisher, so "
                   f"a release without it is rejected. Add: "
                   f"<!-- mcp-name: {name} -->")
    elif token.group(1) != name:
        out.append(f"README.md declares mcp-name {token.group(1)!r} but "
                   f"server.json is named {name!r}")
    return out


def fix() -> int:
    want = pyproject_version()
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = []
    if man.get("version") != want:
        changed.append(f"version {man.get('version')} -> {want}")
        man["version"] = want
    for i, pkg in enumerate(man.get("packages") or []):
        if pkg.get("version") != want:
            changed.append(f"packages[{i}].version {pkg.get('version')} -> {want}")
            pkg["version"] = want
    if not changed:
        print("check_server_manifest: versions already agree with pyproject.")
        return 0
    MANIFEST.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    for c in changed:
        print(f"  {c}")
    print(f"check_server_manifest: rewrote {MANIFEST.name} from pyproject.")
    print("  The README token is NOT fixed automatically: it names the "
          "publisher,\n  and that is a claim about identity, not a version to "
          "sync.")
    return 0


def main() -> int:
    if "--fix" in sys.argv:
        return fix()
    found = findings()
    if not found:
        print(f"check_server_manifest: clean "
              f"(server.json, pyproject.toml and README.md all agree at "
              f"{pyproject_version()}).")
        return 0
    print("\nSERVER MANIFEST:\n")
    for f in found:
        print(f"  {f}")
    print("\nTo sync the versions from pyproject: "
          "python3 scripts/dev/check_server_manifest.py --fix\n")
    return 1 if "--check" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
