"""
Scaling-law analysis: fit each engine's duration to a power law t = a · N^alpha.

The exponent alpha is an engine's complexity class for the workload: ~0 is
flat, 0.5 is O(sqrt N), 1 is linear. Two engines sharing an alpha but separated
by a constant factor are the same algorithm at different fixed cost; a larger
alpha is a fundamentally worse scaling regime.

Single source of truth for both the CLI (scripts/tools/analyze_scaling.py) and
the reporting asset, which writes scaling.json into every capsule that has a
row-scaled matrix.
"""
import glob
import json
import math
import os
import statistics
from typing import Dict, Optional


def power_law(points: Dict[int, float]):
    """Least-squares fit log10(t) ~ alpha*log10(N) + log10(a). Returns (alpha, r2)."""
    xs = [math.log10(n) for n in points]
    ys = [math.log10(points[n]) for n in points]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 1.0
    alpha = sum((xs[i] - mx) * (ys[i] - my) for i in range(k)) / sxx
    b = my - alpha * mx
    ss_res = sum((ys[i] - (alpha * xs[i] + b)) ** 2 for i in range(k))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return alpha, r2


def regime(alpha: float) -> str:
    if alpha < 0.15: return "near-constant"
    if alpha < 0.45: return "sublinear"
    if alpha < 0.65: return "~O(sqrt N)"
    if alpha < 1.25: return "~linear"
    return "superlinear"


def _points_from_fragments(results_dir: str, exp_id: str) -> Dict[str, Dict[int, float]]:
    """engine -> {rows: median_duration_seconds}, read from the capsule's raw fragments."""
    series: Dict[str, Dict[int, list]] = {}
    for path in glob.glob(os.path.join(results_dir, exp_id, "fragments", "*.json")):
        with open(path) as f:
            data = json.load(f)
        params = data.get("parameters", {})
        if "rows" not in params:
            continue  # needs a numeric row axis (TPC-H uses scale_factor, skip)
        metrics = data.get("metrics", {})
        raw = metrics.get("durations_raw") or (
            [metrics["duration_seconds"]] if metrics.get("duration_seconds") is not None else []
        )
        if not raw:
            continue  # DNF
        engine = data["meta"]["engine"]
        series.setdefault(engine, {}).setdefault(int(params["rows"]), []).extend(raw)
    return {e: {n: statistics.median(v) for n, v in by_rows.items()} for e, by_rows in series.items()}


def analyze_capsule(results_dir: str, exp_id: str) -> Optional[dict]:
    """
    Returns a scaling report for a capsule, or None if it has no row-scaled
    timings (e.g. a single-scale or scale_factor-only experiment).

    {engine: {alpha, r2, growth, n_points, regime, points: {rows: seconds}}}
    """
    series = _points_from_fragments(results_dir, exp_id)
    report = {}
    for engine, pts in series.items():
        if len(pts) < 2:
            continue  # a power law needs at least two scale points
        alpha, r2 = power_law(pts)
        lo, hi = min(pts), max(pts)
        report[engine] = {
            "alpha": round(alpha, 4),
            "r2": round(r2, 4),
            "growth": round(pts[hi] / pts[lo], 3),
            "n_points": len(pts),
            "regime": regime(alpha),
            "points": pts,
        }
    return report or None
