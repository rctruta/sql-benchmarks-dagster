#!/usr/bin/env python3
"""
Locate the scale 'kink' in a capsule: the row-count interval where an engine's
per-decade slowdown spikes. That spike is the mathematical flare — it points
EXPLAIN ANALYZE at the exact interval where the engine changes strategy (a sort/
hash spilling to disk, an index scan flipping to seq/bitmap, a parallelism wall).

Two corrections over a naive tmax/tmin reading:
  * per-decade normalization — scale points are not evenly spaced (1K->100K is
    TWO decades), so each interval's multiplier is taken as ratio**(1/decades);
    a raw ratio would flag a false kink on the wide interval.
  * noise awareness — each interval also reports the replication spread at its
    endpoints, so a spike can be judged against measurement noise, not trusted
    blindly. With few scale points a kink LOCATES where to look; EXPLAIN confirms.

Reads sealed fragments only. Computes nothing that feeds the Experiment ID, so
it never changes an ID or a seal.

Usage:  python scripts/tools/find_kink.py <experiment_id> [<id> ...]
"""
import glob
import json
import math
import os
import statistics
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")


def raw_points(capsule: str) -> dict:
    """engine -> {rows: [raw durations]} from fragments with a numeric rows axis."""
    series: dict = {}
    for path in glob.glob(os.path.join(capsule, "fragments", "*.json")):
        with open(path) as f:
            data = json.load(f)
        params = data.get("parameters", {})
        if "rows" not in params:
            continue
        metrics = data.get("metrics", {})
        raw = metrics.get("durations_raw") or (
            [metrics["duration_seconds"]] if metrics.get("duration_seconds") is not None else []
        )
        if not raw:
            continue
        eng = data["meta"]["engine"]
        series.setdefault(eng, {}).setdefault(int(params["rows"]), []).extend(raw)
    return series


def ladder(points: dict):
    """points: {rows: [raw]} -> (median_by_n, [(n1, n2, per_decade_mult, noise)])."""
    ns = sorted(points)
    med = {n: statistics.median(points[n]) for n in ns}
    rungs = []
    for n1, n2 in zip(ns, ns[1:]):
        decades = math.log10(n2 / n1)
        mult = (med[n2] / med[n1]) ** (1 / decades) if decades and med[n1] else float("nan")
        spread = max(
            (max(points[n1]) - min(points[n1])) / med[n1] if med[n1] else 0.0,
            (max(points[n2]) - min(points[n2])) / med[n2] if med[n2] else 0.0,
        )
        rungs.append((n1, n2, mult, spread))
    return med, rungs


def report(exp_id: str) -> None:
    capsule = os.path.join(RESULTS, exp_id)
    if not os.path.isdir(capsule):
        print(f"{exp_id}: MISSING\n")
        return
    series = raw_points(capsule)
    if not series:
        print(f"{exp_id}: no row-scaled fragments (needs a numeric 'rows' axis)\n")
        return
    print(f"=== {exp_id} ===")
    for eng, pts in sorted(series.items()):
        if len(pts) < 3:
            print(f"  {eng}: {len(pts)} scale point(s) — need >=3 (>=2 intervals) to locate a kink")
            continue
        med, rungs = ladder(pts)
        mults = [m for *_, m, _ in rungs]
        typical = statistics.median(mults)
        kink = max(rungs, key=lambda r: r[2])
        print(f"  {eng}:")
        print(f"    {'interval':>20} {'per-decade':>11} {'noise(±%)':>10}")
        for n1, n2, mult, spread in rungs:
            mark = "  <-- KINK" if (n1, n2) == (kink[0], kink[1]) else ""
            print(f"    {n1:>8,}->{n2:<9,} {mult:>10.2f}x {spread*100:>9.0f}%{mark}")
        spike = kink[2] / typical if typical else float("nan")
        verdict = (
            f"    spike {spike:.1f}x over typical"
            + ("  — within endpoint noise, treat as soft" if kink[2] - 1 <= kink[3] else "")
        )
        print(verdict)
        print(f"    -> EXPLAIN ANALYZE {eng} at rows={kink[0]:,} vs {kink[1]:,}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for exp_id in sys.argv[1:]:
        report(exp_id)
