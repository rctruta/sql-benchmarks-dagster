#!/usr/bin/env python3
"""
Log-log scaling figure (median duration vs row count) for a row-scaled capsule,
built ONLY from the capsule's sealed fragments — so the picture is regenerable
and can't drift from the numbers. Error bars show the replication spread where
there is more than one rep; single-shot points (the Act 0 scout) draw without.

Usage:  python scripts/tools/plot_scaling.py <experiment_id> [<id> ...]
Output: scratch/figures/scaling_<id>.png  (gitignored; for the article)
"""
import glob
import json
import math
import os
import re
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")
OUT = os.path.join(REPO_ROOT, "scratch", "figures")


def series(capsule: str) -> dict:
    s: dict = {}
    for p in glob.glob(os.path.join(capsule, "fragments", "*.json")):
        with open(p) as f:
            d = json.load(f)
        par, m = d.get("parameters", {}), d.get("metrics", {})
        if "rows" not in par:
            continue
        raw = m.get("durations_raw") or (
            [m["duration_seconds"]] if m.get("duration_seconds") is not None else []
        )
        if raw:
            s.setdefault(d["meta"]["engine"], {}).setdefault(int(par["rows"]), []).extend(raw)
    return s


def alpha(points: dict) -> float:
    """log-log least-squares slope (power-law exponent)."""
    xs = [math.log10(n) for n in points]
    ys = [math.log10(statistics.median(points[n])) for n in points]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(k)) / sxx if sxx else 0.0


def plot(exp_id: str) -> None:
    capsule = os.path.join(RESULTS, exp_id)
    s = series(capsule)
    if not s:
        print(f"{exp_id}: no row-scaled fragments — skipped")
        return
    os.makedirs(OUT, exist_ok=True)
    raw_kept = max((len(v) for eng in s.values() for v in eng.values()), default=1)
    # The capsule may have run more reps than it RETAINED (pre-migration capsules
    # stored only the aggregate). Read the declared replication so the label is honest.
    cfg = os.path.join(capsule, "experiment_config.yaml")
    declared = raw_kept
    if os.path.exists(cfg):
        m = re.search(r"replication:\s*(\d+)", open(cfg).read())
        if m:
            declared = int(m.group(1))
    plt.figure(figsize=(7, 5))
    for eng in sorted(s):
        pts = s[eng]
        ns = sorted(pts)
        med = [statistics.median(pts[n]) * 1000 for n in ns]
        a = alpha(pts)
        lo = [(statistics.median(pts[n]) - min(pts[n])) * 1000 for n in ns]
        hi = [(max(pts[n]) - statistics.median(pts[n])) * 1000 for n in ns]
        if any(l > 0 or h > 0 for l, h in zip(lo, hi)):
            plt.errorbar(ns, med, yerr=[lo, hi], marker="o", capsize=3, label=f"{eng}  (α≈{a:.2f})")
        else:
            plt.plot(ns, med, marker="o", label=f"{eng}  (α≈{a:.2f})")
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("Rows (log scale)")
    plt.ylabel("Median duration, ms (log scale)")
    if raw_kept > 1:
        reps = f"median of {raw_kept} cold reps"
    elif declared > 1:
        reps = f"{declared} cold reps, aggregate retained (no per-rep raw)"
    else:
        reps = "single-shot (n=1)"
    plt.title(f"Scaling: duration vs rows — {exp_id}\n({reps}; power laws plot as straight lines)")
    plt.legend()
    plt.grid(True, which="both", ls=":", alpha=0.4)
    out = os.path.join(OUT, f"scaling_{exp_id}.png")
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for exp_id in sys.argv[1:]:
        plot(exp_id)
