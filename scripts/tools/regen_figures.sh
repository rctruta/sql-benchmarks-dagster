#!/usr/bin/env bash
# Regenerate the article figures from the SEALED capsules into scratch/figures/.
#
# Figures are DERIVED, gitignored artifacts. They don't travel through git, and
# they don't need to: run this in ANY checkout to reproduce every figure from the
# sealed capsule data — no copying PNGs between worktree and primary.
set -e
cd "$(git rev-parse --show-toplevel)"
PY=./venv/bin/python
[ -x "$PY" ] || PY=python3

"$PY" scripts/tools/plot_scaling.py b82b4eae b8e2bfaf 902d1277   # Acts 0, I, IV (duration vs rows)
"$PY" scripts/tools/plot_threads.py 25b0e134                      # Act II (effective server threads)

echo "Figures regenerated in scratch/figures/  (Act III / TPC-H figure: not built yet)"
