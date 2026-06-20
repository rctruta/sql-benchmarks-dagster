#!/usr/bin/env python3
"""
X-factor table: each engine's median duration vs a baseline engine, per scale.

The engineer's view — "how many times slower than the floor, at MY data size" —
complementing the log-log scaling exponent (the asymptotic shape). Reads the
capsule's sealed fragments only, so it can't drift from the numbers.

Usage:  python scripts/tools/xfactor.py <experiment_id> [--baseline duckdb]
Prints a Markdown table to stdout.
"""
import argparse
import glob
import json
import os
import statistics
import sys

from _plotlib import RESULTS_DIR


def medians(capsule: str) -> dict:
    s: dict = {}
    for p in glob.glob(os.path.join(capsule, "fragments", "*.json")):
        with open(p) as f:
            d = json.load(f)
        par, m = d.get("parameters", {}), d.get("metrics", {})
        if "rows" not in par:
            continue
        raw = m.get("durations_raw") or (
            [m["duration_seconds"]] if m.get("duration_seconds") is not None else [])
        if raw:
            s.setdefault(d["meta"]["engine"], {}).setdefault(int(par["rows"]), []).extend(raw)
    return {e: {n: statistics.median(v) for n, v in by.items()} for e, by in s.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_id")
    ap.add_argument("--baseline", default="duckdb")
    args = ap.parse_args()

    s = medians(os.path.join(RESULTS_DIR, args.exp_id))
    if args.baseline not in s:
        sys.exit(f"baseline '{args.baseline}' not among capsule engines: {sorted(s)}")
    others = sorted(e for e in s if e != args.baseline)
    scales = sorted({n for e in s for n in s[e]})

    cols = ["Rows", f"{args.baseline} (s)"] + [f"{e} (s)" for e in others] + [f"{e} X" for e in others]
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join(["---"] * len(cols)) + "|")
    for n in scales:
        base = s[args.baseline].get(n)
        cells = [f"{n:,}", f"{base:.4f}" if base else "—"]
        for e in others:
            v = s[e].get(n)
            cells.append(f"{v:.4f}" if v else "DNF")
        for e in others:
            v = s[e].get(n)
            cells.append(f"{v / base:.2f}x" if (v and base) else "—")
        print("| " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
