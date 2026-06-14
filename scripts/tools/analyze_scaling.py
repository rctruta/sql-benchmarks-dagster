"""
Scaling-law analysis for a results capsule (CLI).

Thin wrapper over sql_benchmarks.utils.scaling — the same code the reporting
asset uses to write scaling.json into every capsule. Reads the sealed capsule,
so the exponents are reproducible: anyone can rerun this against a published
capsule and get the same numbers.

Usage:
    python scripts/tools/analyze_scaling.py <experiment_id>
"""
import os
import sys

# Allow running as a plain script from the repo root (python scripts/tools/...)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sql_benchmarks.constants import RESULTS_DIR
from sql_benchmarks.utils.scaling import analyze_capsule


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exp_id = sys.argv[1]
    report = analyze_capsule(RESULTS_DIR, exp_id)
    if not report:
        sys.exit(f"No row-scaled fragments with timings found for '{exp_id}'.")

    print(f"Scaling analysis — capsule {exp_id}")
    print(f"{'engine':<16} {'alpha':>7} {'R^2':>6} {'growth':>9}  regime")
    print("-" * 56)
    for engine in sorted(report):
        r = report[engine]
        print(f"{engine:<16} {r['alpha']:>7.3f} {r['r2']:>6.3f} {r['growth']:>8.1f}x  {r['regime']}")


if __name__ == "__main__":
    main()
