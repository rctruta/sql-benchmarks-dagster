#!/usr/bin/env python3
"""Transport-cost figure for a postgres_transport capsule, built ONLY from the
capsule's sealed fragments — regenerable, can't drift. Replaces the one-off
matplotlib script that produced the original ADBC story figure.

Two panels:
  LEFT  — ADBC (Arrow) speedup over psycopg2 (row fetch), by payload, vs rows.
          A parity line at 1.0; below = the row path wins, above = Arrow wins.
  RIGHT — ADBC / connectorx ratio (both Arrow), by payload, vs rows.
          Below 1.0 = ADBC faster.

Labels are deliberately HONEST: the jsonb gap is attributed to psycopg2's eager
dict deserialization, NOT to "Arrow handles nested data better" (the payload is
shallow, depth-2). Do not relabel it as a structural-nesting result.

Usage:  python scripts/tools/plot_transport.py <experiment_id>
Output: scratch/figures/transport_<id>.png  (gitignored working copy;
        promote with scripts/tools/publish_figure.py to share it)
"""
import glob
import json
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from _plotlib import REPO_ROOT, RESULTS_DIR

OUT = os.path.join(REPO_ROOT, "scratch", "figures")

# payload key (from the SQL file name) -> (legend label, color)
PAYLOADS = {
    "primitives": ("primitives", "#777777"),
    "with_array": ("+ int[]", "#2ca02c"),
    "with_jsonb": ("+ jsonb", "#ff7f0e"),
    "nested": ("jsonb + int[]", "#d62728"),
}


def collect(capsule: str) -> dict:
    """data[payload][client][rows] = mean duration (seconds)."""
    data: dict = {}
    for p in glob.glob(os.path.join(capsule, "fragments", "*.json")):
        with open(p) as f:
            d = json.load(f)
        meta, par, m = d["meta"], d.get("parameters", {}), d.get("metrics", {})
        client = par.get("postgres_transport.client")
        rows = par.get("rows")
        dur = m.get("duration_seconds")
        if client is None or rows is None or dur is None:   # skip DNF / non-transport
            continue
        payload = meta["asset"].split("postgres_transport_benchmark_")[-1]
        data.setdefault(payload, {}).setdefault(client, {})[int(rows)] = dur
    return data


def _ratio_series(per_client, num, den):
    """rows -> num/den where both clients measured that row count."""
    a, b = per_client.get(num, {}), per_client.get(den, {})
    rows = sorted(set(a) & set(b))
    return rows, [a[r] / b[r] for r in rows]


def plot(exp_id: str) -> None:
    capsule = os.path.join(RESULTS_DIR, exp_id)
    data = collect(capsule)
    if not data:
        print(f"{exp_id}: no postgres_transport fragments — skipped")
        return
    os.makedirs(OUT, exist_ok=True)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5))

    for payload, (label, color) in PAYLOADS.items():
        per_client = data.get(payload)
        if not per_client:
            continue
        # LEFT: psycopg2 / adbc  (>1 => Arrow faster than the row path)
        rows, spd = _ratio_series(per_client, "psycopg", "adbc")
        if rows:
            axL.plot(rows, spd, marker="o", color=color, label=label)
        # RIGHT: adbc / connectorx  (<1 => ADBC faster)
        rows, rat = _ratio_series(per_client, "adbc", "connectorx")
        if rows:
            axR.plot(rows, rat, marker="o", color=color, label=label)

    for ax in (axL, axR):
        ax.set_xscale("log")
        ax.set_xlabel("rows pulled (log)")
        ax.grid(True, which="both", ls=":", alpha=0.4)
        ax.legend(title="payload", fontsize=8)

    axL.axhline(1.0, color="k", ls="--", lw=1, alpha=0.6)
    axL.set_ylabel("ADBC speedup over psycopg2  (psycopg2 / ADBC)")
    axL.set_title("Arrow (ADBC) vs row fetch (psycopg2)\n"
                  "primitives cross over ~1M; jsonb gap is psycopg2 dict-deserialization, not nesting")

    axR.axhline(1.0, color="k", ls="--", lw=1, alpha=0.6)
    axR.set_ylabel("ADBC / connectorx  (<1 = ADBC faster)")
    axR.set_title("ADBC vs connectorx (both Arrow, read-only)\n"
                  "close on flat/array; ADBC ahead on jsonb")

    fig.suptitle(f"Postgres result-transport cost — capsule {exp_id} "
                 "(cold-cache, exploratory, single machine)", fontsize=11)
    out = os.path.join(OUT, f"transport_{exp_id}.png")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    plot(sys.argv[1])
