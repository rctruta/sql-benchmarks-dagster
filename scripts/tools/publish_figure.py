#!/usr/bin/env python3
"""Promote a figure from the working set (scratch/figures/, gitignored) to the
SHAREABLE set (docs/figures/, tracked) and stage it — so sharing a figure needs
no `git add -f` and no remembering paths.

Policy this enforces: docs/figures/ holds only figures that a tool can
regenerate from a sealed capsule. So before promoting, there must be a
generating tool (plot_scaling.py, plot_transport.py, ...) that reproduces it —
no orphan one-offs in the public repo.

Usage:
    python scripts/tools/publish_figure.py transport_af6ba593      # name, with or
    python scripts/tools/publish_figure.py transport_af6ba593.png  # without .png

After it runs, the figure is staged; commit it and link to it at:
    https://github.com/rctruta/sql-benchmarks-dagster/blob/main/docs/figures/<name>.png
"""
import os
import shutil
import subprocess
import sys

from _plotlib import REPO_ROOT

SCRATCH = os.path.join(REPO_ROOT, "scratch", "figures")
PUBLISHED = os.path.join(REPO_ROOT, "docs", "figures")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    name = sys.argv[1]
    if not name.endswith(".png"):
        name += ".png"

    src = os.path.join(SCRATCH, name)
    if not os.path.exists(src):
        sys.exit(f"not found: {src}\n(generate it first, e.g. "
                 f"`python scripts/tools/plot_transport.py <capsule_id>`)")

    os.makedirs(PUBLISHED, exist_ok=True)
    dst = os.path.join(PUBLISHED, name)
    shutil.copy2(src, dst)
    subprocess.run(["git", "add", dst], cwd=REPO_ROOT, check=True)

    rel = os.path.relpath(dst, REPO_ROOT)
    print(f"published + staged: {rel}")
    print("commit it, then share this link:")
    print(f"  https://github.com/rctruta/sql-benchmarks-dagster/blob/main/{rel}")


if __name__ == "__main__":
    main()
