#!/usr/bin/env python3
"""
check_compiles — every tracked Python file must at least parse.

    .gates/check_compiles.py            report
    .gates/check_compiles.py --check    exit 1 on any syntax error

The cheapest gate there is, and it was missing. On 2026-10-20 a commit in this
repository introduced a SyntaxError -- an inline comment placed inside a
function's parentheses -- and every installed gate passed it: no_local_paths,
no_private_marker, scratch_external, no_orphans and check_voice all read the
file as text and none of them ask Python whether it is valid Python.

A repository with no tests has nothing else standing between a broken file and
a commit. This does not check behaviour; it checks that the file is parseable,
which is the floor.

A PARSE RESULT IS RELATIVE TO THE INTERPRETER RUNNING IT, which this did not
say at first and should have. Run against rctruta.github.io with Python 3.11
it reported tools/build_nav.py as a SyntaxError; that file uses a backslash
inside an f-string expression, which PEP 701 made legal in 3.12, and the site
builds on 3.14. The file was fine and the gate was wrong to imply otherwise.
So the version is always printed, and a finding says plainly that it may be a
version mismatch rather than a defect -- compared against requires-python when
the project declares one.
"""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__",
             "dist", "build", "site-packages", ".pytest_cache", "scratch"}


def tracked():
    try:
        p = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return [f for f in p.stdout.split("\0") if f] if p.returncode == 0 else None


def requires_python():
    """The project's declared minimum, if it has one."""
    for name in ("pyproject.toml", "setup.cfg"):
        p = os.path.join(ROOT, name)
        if not os.path.isfile(p):
            continue
        m = re.search(r'requires[-_]python\s*=\s*"([^"]+)"',
                      open(p, encoding="utf-8", errors="ignore").read())
        if m:
            return m.group(1)
    return None


def main():
    files = tracked()
    if files is None:
        print("check_compiles: git could not be consulted.", file=sys.stderr)
        return 1
    bad = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        if any(d in SKIP_DIRS for d in rel.split(os.sep)):
            continue
        path = os.path.join(ROOT, rel)
        try:
            ast.parse(open(path, encoding="utf-8", errors="ignore").read(), filename=rel)
        except SyntaxError as exc:
            bad.append(f"{rel}:{exc.lineno}  {exc.msg}")
    running = ".".join(str(v) for v in sys.version_info[:3])
    if not bad:
        n = sum(1 for f in files if f.endswith(".py"))
        print(f"check_compiles: clean ({n} tracked python file(s) parse "
              f"under python {running}).")
        return 0
    print(f"\nCHECK COMPILES  (parsed with python {running}):\n")
    for b in bad:
        print(f"  {b}")
    req = requires_python()
    print("\nA file that does not parse cannot run. Fix it before committing.")
    print(f"\nBut check the interpreter first: this parsed with python "
          f"{running}, and syntax\nis version-dependent -- a backslash inside "
          f"an f-string expression, for one, is\nlegal from 3.12 and an error "
          f"before it.")
    if req:
        print(f"This project declares requires-python {req}. Run this gate "
              f"with an\ninterpreter that satisfies it before treating a "
              f"finding as a defect.")
    else:
        print("This project declares no requires-python, so there is nothing "
              "to compare\nthe running interpreter against.")
    print()
    return 1 if "--check" in sys.argv else 0


sys.exit(main())
