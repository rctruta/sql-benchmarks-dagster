"""
Scaling-law analysis for a results capsule.

Fits each engine's duration to a power law  t = a · N^alpha  (least squares on
log-log), straight from the capsule's raw replication fragments. The exponent
alpha is the engine's *complexity class*: ~0 is flat, 0.5 is O(sqrt N), 1 is
linear. Two engines with the same alpha separated by a constant factor are the
same algorithm at different fixed cost; a larger alpha is a fundamentally worse
scaling regime.

Usage:
    python scripts/tools/analyze_scaling.py <experiment_id>

Reads the sealed capsule, so the numbers are reproducible: anyone can rerun
this against a published capsule and get the same exponents.
"""
import glob
import json
import math
import os
import statistics
import sys

RESULTS_DIR = os.path.join("sql_benchmarks", "experiments", "results")


def load_points(exp_id):
    """engine -> {rows: median_duration_seconds}, from raw fragments."""
    series = {}
    for path in glob.glob(os.path.join(RESULTS_DIR, exp_id, "fragments", "*.json")):
        with open(path) as f:
            data = json.load(f)
        params = data.get("parameters", {})
        if "rows" not in params:
            continue  # scaling needs a numeric row axis (e.g. TPC-H uses scale_factor)
        rows = int(params["rows"])
        metrics = data.get("metrics", {})
        raw = metrics.get("durations_raw") or (
            [metrics["duration_seconds"]] if metrics.get("duration_seconds") is not None else []
        )
        if not raw:
            continue  # DNF
        engine = data["meta"]["engine"]
        series.setdefault(engine, {}).setdefault(rows, []).extend(raw)
    return {e: {n: statistics.median(v) for n, v in by_rows.items()} for e, by_rows in series.items()}


def power_law(points):
    """Least-squares fit of log10(t) ~ alpha*log10(N) + log10(a). Returns (alpha, r2)."""
    xs = [math.log10(n) for n in points]
    ys = [math.log10(points[n]) for n in points]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    sxx = sum((x - mx) ** 2 for x in xs)
    alpha = sum((xs[i] - mx) * (ys[i] - my) for i in range(k)) / sxx
    b = my - alpha * mx
    ss_res = sum((ys[i] - (alpha * xs[i] + b)) ** 2 for i in range(k))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return alpha, r2


def label(alpha):
    if alpha < 0.15: return "near-constant"
    if alpha < 0.45: return "sublinear"
    if alpha < 0.65: return "~O(√N)"
    if alpha < 1.25: return "~linear"
    return "superlinear"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exp_id = sys.argv[1]
    series = load_points(exp_id)
    if not series:
        sys.exit(f"No row-scaled fragments with timings found for '{exp_id}'.")

    print(f"Scaling analysis — capsule {exp_id}")
    print(f"{'engine':<16} {'alpha':>7} {'R^2':>6} {'growth':>9}  regime")
    print("-" * 56)
    for engine in sorted(series):
        pts = series[engine]
        if len(pts) < 2:
            print(f"{engine:<16} {'n/a':>7}  (only {len(pts)} scale point)")
            continue
        alpha, r2 = power_law(pts)
        lo, hi = min(pts), max(pts)
        growth = pts[hi] / pts[lo]
        print(f"{engine:<16} {alpha:>7.3f} {r2:>6.3f} {growth:>8.1f}x  {label(alpha)}")


if __name__ == "__main__":
    main()
