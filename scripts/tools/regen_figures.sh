#!/usr/bin/env bash
# Regenerate the article figures from the SEALED capsules into scratch/figures/.
#
# Figures are DERIVED artifacts. The working set lives in scratch/figures/
# (gitignored) — run this in ANY checkout to reproduce every figure from the
# sealed capsule data. To SHARE a specific figure (a stable repo URL, no
# git add -f, no paths to remember) promote it to docs/figures/ (tracked) with
#   scripts/tools/publish_figure.py <name>
# Anything in docs/figures/ MUST be reproducible by one of the tools below.
set -e
cd "$(git rev-parse --show-toplevel)"
PY=./venv/bin/python
[ -x "$PY" ] || PY=python3

"$PY" scripts/tools/plot_scaling.py b82b4eae b8e2bfaf 902d1277   # Acts 0, I, IV (duration vs rows)
"$PY" scripts/tools/plot_threads.py 25b0e134                      # Act II (effective server threads)
"$PY" scripts/tools/plot_transport.py af6ba593                    # transport cost (ADBC/connectorx/psycopg2)

echo "Figures regenerated in scratch/figures/  (Act III / TPC-H figure: not built yet)"
echo "To share one: scripts/tools/publish_figure.py <name>  (promotes to docs/figures/, tracked)"
