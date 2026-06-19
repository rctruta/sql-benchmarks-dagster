#!/usr/bin/env python3
"""
Verify that every capsule reference in the committed docs resolves to a real,
git-tracked, sealed capsule. Catches the recurring error class: a doc citing a
capsule ID that doesn't exist (fabricated or typo) or isn't committed (broken
link) — e.g. the fabricated `3e2fe152` IDs an early article draft carried.

Scans: README.md, AGENTS.md, and docs/**/*.md.
Reference forms recognized (the house conventions for citing a capsule):
  - path:    .../experiments/results/<8hex>/
  - inline:  `<8hex>`   (backtick-quoted ID)

Stdlib only — safe to run from a bare `python3` in a git pre-commit hook.

Usage:  python scripts/tools/verify_doc_claims.py [--check]
        --check : exit 1 if any reference is unresolved (for the hook / CI)
"""
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_REL = "sql_benchmarks/experiments/results"
TOP_DOCS = ["README.md", "AGENTS.md"]
PATH_RE = re.compile(r"results/([0-9a-f]{8})(?:/|\b)")
TICK_RE = re.compile(r"`([0-9a-f]{8})`")

# 8-hex tokens that are NOT capsule IDs (e.g. a short commit SHA cited in prose).
# Add here if the verifier ever false-positives on a legitimate non-capsule hex.
IGNORE = {
    "48c92f31",  # illustrative example ID in README's Naming table — not a real capsule
}


def tracked_capsule_ids() -> set:
    out = subprocess.run(
        ["git", "ls-files", RESULTS_REL + "/"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    ids = set()
    for line in out.stdout.splitlines():
        parts = line.split("/")
        if len(parts) > 4:  # .../results/<ID>/<file>
            ids.add(parts[3])
    return ids


def sealed(exp_id: str) -> bool:
    return os.path.exists(os.path.join(REPO_ROOT, RESULTS_REL, exp_id, "integrity.seal"))


def doc_files() -> list:
    files = [os.path.join(REPO_ROOT, d) for d in TOP_DOCS
             if os.path.exists(os.path.join(REPO_ROOT, d))]
    for root, _, fs in os.walk(os.path.join(REPO_ROOT, "docs")):
        files += [os.path.join(root, f) for f in fs if f.endswith(".md")]
    return files


def main() -> None:
    check = "--check" in sys.argv[1:]
    tracked = tracked_capsule_ids()
    errors, ok = [], 0
    for path in doc_files():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        refs = (set(PATH_RE.findall(text)) | set(TICK_RE.findall(text))) - IGNORE
        rel = os.path.relpath(path, REPO_ROOT)
        for rid in sorted(refs):
            if rid not in tracked:
                errors.append(f"{rel}: `{rid}` — referenced but NOT a git-tracked capsule "
                              "(fabricated, typo, or uncommitted)")
            elif not sealed(rid):
                errors.append(f"{rel}: `{rid}` — tracked but has no integrity.seal")
            else:
                ok += 1
    if errors:
        print("DOC CLAIM CHECK — unresolved capsule references:")
        for e in errors:
            print("  ✗ " + e)
    print(f"{ok} reference(s) resolve to sealed, tracked capsules; {len(errors)} problem(s).")
    if check and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
