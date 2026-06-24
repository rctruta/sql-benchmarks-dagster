#!/usr/bin/env python
"""Dependency drift guard — catch packages that are USED but not DECLARED.

This is how the ADBC drivers slipped through: installed ad-hoc into the env,
relied on by the code, never added to requirements.txt / pyproject.toml — so the
sealed transport capsules were not reproducible by anyone who installed only the
declared deps. This tool makes that failure loud.

Two detectors, because static import scanning alone is not enough here:

  1. IMPORT DRIFT — every top-level package imported under sql_benchmarks/ (and
     tests/scripts) must map to a DECLARED distribution. Catches the common case
     (e.g. `import adbc_driver_quack`, `import duckdb`).

  2. RUNTIME-PLUGIN DRIFT — drivers loaded by STRING at runtime are invisible to
     import scanning (polars `engine="adbc"` pulls in adbc-driver-postgresql +
     the manager; `engine="connectorx"` pulls in connectorx). An explicit trigger
     map enforces those too — this is the exact gap that bit us.

Resolution is robust to which environment runs the tool: an installed package is
mapped import-name -> distribution via importlib.metadata; a package that isn't
installed in the current env is accepted if it's declared under its import name,
otherwise reported as missing.

Usage:
    python scripts/dev/check_deps.py            # report drift; exit 1 if any
    python scripts/dev/check_deps.py --fix       # append missing deps (pinned to
                                                 # installed version) to requirements.txt

Declared set = UNION of requirements.txt + pyproject [project.dependencies] +
all optional-dependency groups, so a dep declared in either file is accepted.
"""
import argparse
import ast
import os
import re
import sys
import tomllib
from importlib import metadata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN_DIRS = ["sql_benchmarks", "sql_benchmarks_tests", "scripts"]
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")
PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")

# First-party top-level package names to ignore (local sibling modules under the
# scanned trees are detected dynamically by _local_modules()).
FIRST_PARTY = {"sql_benchmarks", "sql_benchmarks_tests"}

# Runtime-loaded plugins that no `import` statement reveals: if the trigger text
# appears anywhere in the source, the listed distributions must be declared.
RUNTIME_PLUGIN_TRIGGERS = {
    'engine="adbc"': ["adbc-driver-postgresql", "adbc-driver-manager"],
    "engine='adbc'": ["adbc-driver-postgresql", "adbc-driver-manager"],
    'engine="connectorx"': ["connectorx"],
    "engine='connectorx'": ["connectorx"],
}


def _norm(name: str) -> str:
    """PEP 503 normalization so adbc_driver-X and adbc-driver-x compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower().strip()


def _py_files():
    for d in SCAN_DIRS:
        for dirpath, _, files in os.walk(os.path.join(REPO_ROOT, d)):
            if "__pycache__" in dirpath:
                continue
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _local_modules() -> set:
    """Top-level names importable as local modules/packages within the scanned
    trees (e.g. scripts/tools/_plotlib.py -> '_plotlib') — never PyPI deps."""
    local = set(FIRST_PARTY)
    for d in SCAN_DIRS:
        root = os.path.join(REPO_ROOT, d)
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            p = os.path.join(root, entry)
            if entry.endswith(".py"):
                local.add(entry[:-3])
            elif os.path.isdir(p) and os.path.exists(os.path.join(p, "__init__.py")):
                local.add(entry)
        # also one level down (scripts/tools/_plotlib.py)
        for sub in os.listdir(root):
            subp = os.path.join(root, sub)
            if os.path.isdir(subp):
                for entry in os.listdir(subp):
                    if entry.endswith(".py"):
                        local.add(entry[:-3])
    return local


def _imported_top_levels() -> set:
    names = set()
    for path in _py_files():
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _source_text() -> str:
    chunks = []
    for path in _py_files():
        try:
            chunks.append(open(path, encoding="utf-8").read())
        except OSError:
            pass
    return "\n".join(chunks)


def _declared_names() -> set:
    declared = set()
    if os.path.exists(REQUIREMENTS):
        for line in open(REQUIREMENTS):
            line = line.strip()
            if line and not line.startswith("#"):
                declared.add(_norm(re.split(r"[<>=!~;\[ ]", line, 1)[0]))
    if os.path.exists(PYPROJECT):
        with open(PYPROJECT, "rb") as f:
            data = tomllib.load(f)
        proj = data.get("project", {})
        groups = [proj.get("dependencies", [])]
        groups += list(proj.get("optional-dependencies", {}).values())
        for group in groups:
            for spec in group:
                declared.add(_norm(re.split(r"[<>=!~;\[ ]", spec, 1)[0]))
    return declared


def find_missing():
    """Return (missing_import, missing_runtime): name -> installed version (or None)."""
    declared = _declared_names()
    local = _local_modules()
    top2dist = metadata.packages_distributions()
    stdlib = getattr(sys, "stdlib_module_names", set())

    def version(dist):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return None

    missing_import = {}
    for top in _imported_top_levels():
        if top in local or top in stdlib:
            continue
        dists = top2dist.get(top)
        if dists:                                  # installed: map to real distro(s)
            for dist in dists:
                if _norm(dist) not in declared:
                    missing_import[_norm(dist)] = version(dist)
        elif _norm(top) not in declared:           # not installed AND not declared by name
            missing_import[_norm(top)] = None

    text = _source_text()
    missing_runtime = {}
    for trigger, required in RUNTIME_PLUGIN_TRIGGERS.items():
        if trigger in text:
            for dist in required:
                if _norm(dist) not in declared:
                    missing_runtime[_norm(dist)] = version(dist)

    return missing_import, missing_runtime


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true",
                    help="append missing deps (pinned to installed version) to requirements.txt")
    args = ap.parse_args()

    missing_import, missing_runtime = find_missing()
    missing = {**missing_import, **missing_runtime}

    if not missing:
        print("Dependency check: every imported + runtime-loaded package is declared. ✓")
        return

    print("DEPENDENCY DRIFT — used but NOT declared in requirements.txt / pyproject.toml:")
    for name in sorted(missing_import):
        print(f"  ✗ {name}  (imported; installed {missing_import[name] or 'NOT INSTALLED'})")
    for name in sorted(missing_runtime):
        print(f"  ✗ {name}  (runtime-loaded plugin; installed {missing_runtime[name] or 'NOT INSTALLED'})")

    if args.fix:
        lines = [f"{n}=={missing[n]}" for n in sorted(missing) if missing[n]]
        skipped = [n for n in sorted(missing) if not missing[n]]
        for n in skipped:
            print(f"  ! skipping {n}: not installed in this env, cannot pin a version")
        if lines:
            with open(REQUIREMENTS, "a") as f:
                f.write("\n# auto-added by check_deps.py --fix "
                        "(mirror these into pyproject.toml [project.dependencies])\n")
                f.write("\n".join(lines) + "\n")
            print(f"\nAppended {len(lines)} dep(s) to requirements.txt. "
                  "Mirror them into pyproject.toml, then re-run `uv lock`.")
        return

    print("\nRun with --fix to append them to requirements.txt (pinned to the "
          "installed version), then mirror into pyproject.toml.")
    sys.exit(1)


if __name__ == "__main__":
    main()
