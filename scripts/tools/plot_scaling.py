#!/usr/bin/env python3
"""
Log-log scaling figure (median duration vs row count) for a row-scaled capsule,
built ONLY from the capsule's sealed fragments — regenerable, can't drift.
Error bars show the replication spread where more than one rep was retained.

Usage:  python scripts/tools/plot_scaling.py <experiment_id> [<id> ...]
Output: scratch/figures/scaling_<id>.png  (gitignored; for the article)
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

from _plotlib import REPO_ROOT, RESULTS_DIR, style

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
    capsule = os.path.join(RESULTS_DIR, exp_id)
    s = series(capsule)
    if not s:
        print(f"{exp_id}: no row-scaled fragments — skipped")
        return
    os.makedirs(OUT, exist_ok=True)
    plt.figure(figsize=(7, 5))
    for eng in sorted(s):
        pts = s[eng]
        ns = sorted(pts)
        med = [statistics.median(pts[n]) * 1000 for n in ns]
        a = alpha(pts)
        label, color, marker = style(eng)
        lo = [(statistics.median(pts[n]) - min(pts[n])) * 1000 for n in ns]
        hi = [(max(pts[n]) - statistics.median(pts[n])) * 1000 for n in ns]
        if any(l > 0 or h > 0 for l, h in zip(lo, hi)):
            plt.errorbar(ns, med, yerr=[lo, hi], marker=marker, color=color,
                         capsize=3, label=f"{label}  (α≈{a:.2f})")
        else:
            plt.plot(ns, med, marker=marker, color=color, label=f"{label}  (α≈{a:.2f})")
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("Rows (log scale)")
    plt.ylabel("Median duration, ms (log scale)")
    plt.title(f"Scaling: duration vs rows — {exp_id}")
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
