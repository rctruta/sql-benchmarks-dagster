#!/usr/bin/env python3
"""
Article numbers pack — one command that runs every analysis tool over a set of
sealed capsules and emits a single Markdown report (tables + scaling fits) plus
all figures, straight from the capsules.

This is Phase 1 of docs/ARTICLE_WORKFLOW.md: lock every number BEFORE writing a
word of prose, so the writing never has to re-derive or fact-check a figure.
Numbers come from the tools, never hand-typed — so they cannot drift from the
sealed capsule (the exact failure that cost a rewrite on the Quack article).

Usage:
    python scripts/tools/article_pack.py <ID> [<ID> ...] [--baseline duckdb]
    python scripts/tools/article_pack.py b8e2bfaf 902d1277 > scratch/pack.md

Output:
    - Markdown report to stdout (redirect to a file to keep it).
    - Figures written by plot_scaling / plot_threads into scratch/figures/.
"""
import argparse
import os
import subprocess
import sys

from _plotlib import REPO_ROOT

TOOLS = os.path.join(REPO_ROOT, "scripts", "tools")


def run(tool: str, *args: str) -> str:
    """Run a tool script with the same interpreter, from the repo root."""
    proc = subprocess.run(
        [sys.executable, os.path.join(TOOLS, tool), *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return (proc.stdout + proc.stderr).strip()


def section(title: str, body: str) -> None:
    print(f"\n### {title}\n")
    print(body if body.strip() else "_(no output)_")


def pack(exp_id: str, baseline: str) -> None:
    print(f"\n## Capsule `{exp_id}`\n")

    # X-factor table — row-scaled capsules only (mean, matching the CSV).
    out = run("xfactor.py", exp_id, "--baseline", baseline)
    if "|" in out:
        section(f"X-factor — mean duration vs `{baseline}`, per scale", out)
    else:
        section("X-factor", f"_not a row-scaled capsule — X-factor N/A_\n\n```\n{out}\n```")

    # Scaling exponents — sealed median fit (matches scaling.json / published table).
    out = run("analyze_scaling.py", exp_id)
    section("Scaling exponents (α — sealed fit)", f"```\n{out}\n```")

    # Figures — only report the ones that actually got written.
    fig_lines = []
    for tool in ("plot_scaling.py", "plot_threads.py"):
        for line in run(tool, exp_id).splitlines():
            if "wrote" in line.lower():
                fig_lines.append(line.strip())
    section(
        "Figures",
        "\n".join(f"- {l}" for l in fig_lines)
        if fig_lines
        else "_none — capsule's axis matches neither the scaling nor the thread figure_",
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Emit the article numbers pack (tables + scaling + figures) for one or more capsules."
    )
    ap.add_argument("exp_ids", nargs="+", help="capsule Experiment IDs")
    ap.add_argument("--baseline", default="duckdb", help="baseline engine for the X-factor table")
    args = ap.parse_args()

    ids = ", ".join(f"`{i}`" for i in args.exp_ids)
    print(f"# Article numbers pack\n\nCapsules: {ids}  ·  baseline: `{args.baseline}`")
    print("\n_Every number below is generated from the sealed capsules — do not hand-edit._")
    for exp_id in args.exp_ids:
        pack(exp_id, args.baseline)


if __name__ == "__main__":
    main()
