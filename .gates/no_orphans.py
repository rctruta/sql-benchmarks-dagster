#!/usr/bin/env python3
"""
no_orphans — refuse a module that only its own tests import.

  .gates/no_orphans.py              report
  .gates/no_orphans.py --check      exit 1 on anything not baselined
  .gates/no_orphans.py --baseline   accept today's findings

The cause: code exists, is tested, and is wired to nothing. A passing test then
certifies a feature that never runs, and the green tick is the reason nobody
looks again.

Three specimens of it, all from one repository:

  2026-06-15  utils/ddl.py's PostgresDDLGenerator produced PK, index and FK
              DDL from the YAML spec and had a passing unit test. Nothing in
              the live path imported it -- only the test instantiated it. The
              real ingestion ran DROP TABLE; CREATE TABLE (cols) and applied
              none of it, so `primary_key: true` and `indexes:` in every config
              were declared-but-unenforced, with a green test giving false
              confidence that indexes worked.

  earlier     a check_integrity() that claimed to detect code tampering but
              inspected a sentinel file existing nowhere except inside the test
              that planted it, tampered with its own plant, and asserted
              detection. The real mechanism sat tested-but-unwired.

  2026-06-24  a "semantic firewall" that read fragments from the wrong path,
              audited a stale run and could never raise -- decorative, and
              described in a public bio as a capability.

What it does: builds the import graph with ast, splits the files into tests and
live code, and refuses a module that live code never imports.

WHAT IT DELIBERATELY TREATS AS LIVE, because each is a real way to be reached
without an import statement, and a gate that cries wolf gets switched off:

  entry points     [project.scripts] in pyproject.toml
  dotted strings   a module named in any yaml/json/toml/ini -- plugin systems
                   resolve `plugins.data_sources.declarative_gen` at runtime,
                   and that reference is as real as an import
  __main__ blocks  a module runnable as a script
  packages         __init__.py, conftest.py, setup.py
  dynamic imports  a file using importlib or __import__ makes the graph
                   incomplete, so every module it could reach is spared and
                   the report says so

It cannot see every dynamic path, which is why it reports rather than asserts
completeness. A finding is "nothing I can see imports this", not "this is
dead".
"""
import ast
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _baseline

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = "no_orphans"

# A file is a test if any path segment or its name says so.
TEST_RE = re.compile(r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]*\.py$|_test\.py$")
SKIP_DIRS = {".git", ".gates", "node_modules", "venv", ".venv", "__pycache__",
             "dist", "build", "site-packages", ".pytest_cache", "scratch"}
ALWAYS_LIVE = {"__init__.py", "conftest.py", "setup.py", "__main__.py"}
DATA_EXTS = (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg")
ALLOW = [
    # "sql_benchmarks/plugins/experimental.py",   # an exemption belongs in a diff
]


def tracked():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"],
                             capture_output=True, text=True, timeout=30).stdout
        return [f for f in out.split("\0") if f]
    except Exception:
        return []


def module_name(rel):
    return rel[:-3].replace(os.sep, ".")


def imported_names(path, rel):
    """Absolute dotted module names this file imports.

    Relative imports have to be resolved against the importing file's own
    package or they are invisible. `from .duckdb_client import DuckDBClient`
    gives ast a module of "duckdb_client" with level=1, which matches nothing
    on its own -- so the first version of this gate reported sixteen orphans in
    a working repository, among them the core engine clients, every one of them
    imported relatively by a sibling. A gate with that false-positive rate gets
    baselined wholesale, which is the same as not having it.
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except (SyntaxError, ValueError):
        return set(), False

    pkg = rel.replace(os.sep, ".").rsplit(".", 1)[0]      # the file's package
    pkg_parts = pkg.split(".") if pkg else []

    def absolute(mod, level):
        if not level:
            return mod
        base = pkg_parts[:len(pkg_parts) - (level - 1)] if level > 1 else pkg_parts
        return ".".join([*base, mod]) if mod else ".".join(base)

    names, dynamic = set(), False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = absolute(node.module or "", node.level or 0)
            if mod:
                names.add(mod)
                for a in node.names:
                    names.add(f"{mod}.{a.name}")
        elif isinstance(node, ast.Name) and node.id == "__import__":
            dynamic = True
        elif isinstance(node, ast.Attribute) and node.attr in (
                "import_module", "spec_from_file_location", "load_module"):
            dynamic = True
    return names, dynamic


def has_main(path):
    try:
        return "__main__" in open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return False


def main():
    files = [f for f in tracked()
             if not any(p in SKIP_DIRS for p in f.split(os.sep))]
    py = [f for f in files if f.endswith(".py")]
    if not py:
        print(f"{GATE}: no tracked python files.")
        return

    tests = [f for f in py if TEST_RE.search(f)]
    live = [f for f in py if f not in set(tests)]

    live_imports, test_imports = set(), set()
    dynamic_anywhere = False
    for f in live:
        n, dyn = imported_names(os.path.join(ROOT, f), f)
        live_imports |= n
        dynamic_anywhere = dynamic_anywhere or dyn
    for f in tests:
        n, _ = imported_names(os.path.join(ROOT, f), f)
        test_imports |= n

    # Dotted references in data files: a plugin system resolving a module by
    # name at runtime reaches it as surely as an import statement does.
    data_blob = []
    for f in files:
        if f.endswith(DATA_EXTS):
            try:
                data_blob.append(open(os.path.join(ROOT, f),
                                      encoding="utf-8", errors="ignore").read())
            except Exception:
                pass
    data_text = "\n".join(data_blob)

    found = {}
    for f in live:
        base = os.path.basename(f)
        if base in ALWAYS_LIVE or f in ALLOW:
            continue
        mod = module_name(f)
        tail = mod.split(".")[-1]
        # reached by live code?
        if any(mod == i or i.startswith(mod + ".") or i.endswith("." + tail)
               for i in live_imports):
            continue
        if has_main(os.path.join(ROOT, f)):
            continue
        if mod in data_text or f in data_text:
            continue
        # reached by a test, and by nothing else -- that is the finding
        if any(mod == i or i.startswith(mod + ".") or i.endswith("." + tail)
               for i in test_imports):
            found[f"{f}\torphan"] = (
                f"{f}\n      imported by tests, by no live code, and named in no "
                f"config.\n      A passing test here certifies a feature that "
                f"never runs.")

    if "--baseline" in sys.argv:
        out = _baseline.save(ROOT, GATE, found, f"{len(found)} finding(s) at adoption")
        print(f"Baselined {len(found)} finding(s) -> {os.path.relpath(out, ROOT)}")
        return

    new, old = _baseline.split(ROOT, GATE, found)
    blocking = _baseline.report(
        GATE, new, old,
        "Wire it into the live path, delete it, or name it in ALLOW with a reason.\n"
        "To accept the current state instead: .gates/no_orphans.py --baseline")

    if dynamic_anywhere and (new or old):
        print("  note: this repository uses importlib or __import__ somewhere, so "
              "the\n        import graph is incomplete. A finding means "
              "\"nothing visible imports\n        this\", not \"this is dead\".")

    _baseline.record(ROOT, GATE, len(new), len(old), blocking)

    if "--check" in sys.argv and blocking:
        sys.exit(1)


main()
