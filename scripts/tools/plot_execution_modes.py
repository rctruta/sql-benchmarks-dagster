"""
Generate the execution-modes figure from a result capsule.

Reads raw per-replication durations from the capsule's fragments (not the
CSV means), so the bands show the true replication spread.

Usage:
    python scripts/tools/plot_execution_modes.py <experiment_id> [output.png]

Requires matplotlib (optional tooling dependency: `uv pip install matplotlib`).
"""
import glob
import json
import os
import sys

import matplotlib.pyplot as plt

from _plotlib import RESULTS_DIR, style, bench_string


def load_fragments(exp_id):
    pattern = os.path.join(RESULTS_DIR, exp_id, "fragments", "*.json")
    series = {}  # engine -> [(rows, raw_durations_ms)]
    for path in glob.glob(pattern):
        with open(path) as f:
            data = json.load(f)
        engine = data["meta"]["engine"]
        rows = int(data["parameters"]["rows"])
        raw = data["metrics"].get("durations_raw") or []
        if not raw:
            continue  # DNF
        series.setdefault(engine, []).append((rows, [d * 1000 for d in raw]))
    for engine in series:
        series[engine].sort()
    return series


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exp_id = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("docs", "figures", f"execution_modes_{exp_id}.png")

    series = load_fragments(exp_id)
    if not series:
        sys.exit(f"No fragments with raw durations found for '{exp_id}'")

    meta_path = os.path.join(RESULTS_DIR, exp_id, f"metadata_{exp_id}.json")
    env = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            env = json.load(f).get("environment", {})

    fig, ax = plt.subplots(figsize=(8, 5))
    for engine, points in series.items():
        label, color, marker = style(engine)
        xs = [rows for rows, _ in points]
        med = [sorted(raw)[len(raw) // 2] for _, raw in points]
        lo = [min(raw) for _, raw in points]
        hi = [max(raw) for _, raw in points]
        ax.plot(xs, med, marker=marker, color=color, label=label, linewidth=2)
        ax.fill_between(xs, lo, hi, color=color, alpha=0.18)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Table rows (log scale)")
    ax.set_ylabel("Query duration, ms (log scale, median of replications)")
    bench = bench_string(env, engines=series.keys())
    ax.set_title(f"Query cost by engine — experiment {exp_id}\n"
                 f"cold cache, bands = replication min–max · {bench}", fontsize=10)
    ax.legend(frameon=False)
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=160)
    print(f"Figure written: {out}")


if __name__ == "__main__":
    main()
