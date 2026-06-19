#!/usr/bin/env python3
"""
Act II figure: the Quack pushdown server runs queries with FEWER effective
threads than an in-process DuckDB connection. We sweep in-process `duckdb.threads`
(1,2,4,8) and overlay pushdown (which ignores that knob — it runs in the server's
own execution context) as a horizontal reference. Where the pushdown line meets
the in-process curve is the server's *effective* thread count.

Reads only the capsule's sealed fragments. Output: scratch/figures/threads_<id>.png

Usage:  python scripts/tools/plot_threads.py [<experiment_id>]   (default 25b0e134)
"""
import glob
import json
import math
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")
OUT = os.path.join(REPO_ROOT, "scratch", "figures")


def load(exp_id):
    s = {}
    for p in glob.glob(os.path.join(RESULTS, exp_id, "fragments", "*.json")):
        d = json.load(open(p))
        par, m = d.get("parameters", {}), d.get("metrics", {})
        raw = m.get("durations_raw") or (
            [m["duration_seconds"]] if m.get("duration_seconds") is not None else [])
        if not raw:
            continue
        th = par.get("threads") or par.get("duckdb.threads")
        s.setdefault((d["meta"]["engine"], par.get("rows")), {}).setdefault(int(th), []).extend(raw)
    return s


def effective_threads(threads, durs, target):
    """log-log interpolate the in-process curve to find threads where dur==target."""
    xs = [math.log2(t) for t in threads]
    ys = [math.log10(d) for d in durs]
    ty = math.log10(target)
    for i in range(len(xs) - 1):
        if (ys[i] - ty) * (ys[i + 1] - ty) <= 0 and ys[i] != ys[i + 1]:
            f = (ty - ys[i]) / (ys[i + 1] - ys[i])
            return 2 ** (xs[i] + f * (xs[i + 1] - xs[i]))
    return None


def main(exp_id="25b0e134"):
    s = load(exp_id)
    os.makedirs(OUT, exist_ok=True)
    rows_vals = sorted({r for (_, r) in s}, key=lambda x: int(x))
    plt.figure(figsize=(7.5, 5))
    colors = plt.cm.viridis([0.2, 0.7])
    for c, rows in zip(colors, rows_vals):
        dd = s.get(("duckdb", rows), {})
        pd = s.get(("quack_pushdown", rows), {})
        if not dd or not pd:
            continue
        threads = sorted(dd)
        durs = [statistics.median(dd[t]) * 1000 for t in threads]
        push = statistics.median([v for vals in pd.values() for v in vals]) * 1000
        label_n = f"{int(rows):,} rows"
        plt.plot(threads, durs, marker="o", color=c, label=f"in-process DuckDB — {label_n}")
        plt.axhline(push, ls="--", color=c, alpha=0.8)
        eff = effective_threads(threads, durs, push)
        if eff:
            plt.annotate(f"pushdown ≈ {eff:.1f} threads", xy=(eff, push), xytext=(eff, push * 1.35),
                         color=c, fontsize=9, ha="center",
                         arrowprops=dict(arrowstyle="->", color=c, alpha=0.7))
        plt.text(8.1, push, f"pushdown {label_n}", va="center", fontsize=8, color=c)
    plt.xscale("log", base=2)
    plt.yscale("log")
    plt.xticks([1, 2, 4, 8], ["1", "2", "4", "8"])
    plt.xlabel("in-process DuckDB threads (of 8 cores)")
    plt.ylabel("Median duration, ms (log scale)")
    plt.title(f"Act II — the pushdown server runs at ~2–4 effective threads, not 8\n"
              f"(dashed = pushdown, which ignores the thread knob; capsule {exp_id})")
    plt.legend(loc="upper right", fontsize=8)
    plt.grid(True, which="both", ls=":", alpha=0.4)
    out = os.path.join(OUT, f"threads_{exp_id}.png")
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "25b0e134")
