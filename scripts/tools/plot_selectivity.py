"""
Generate the selectivity-sweep figure from the selectivity capsules.

Plots query time vs predicate selectivity at a fixed scale (default 10M rows),
overlaying five lanes: in-process DuckDB, Quack attach, Quack pushdown, and
PostgreSQL with and without a B-tree index on the filtered column. The two
Postgres lanes come from two capsules (indexed vs no-index); the three
columnar/Quack lanes are read from the indexed capsule.

Usage:
    python scripts/tools/plot_selectivity.py [indexed_id] [noindex_id] [partition] [out.png]
    # defaults: 461beee8 28f7aa1c large docs/figures/selectivity_461beee8.png

Requires matplotlib (optional tooling dependency: `uv pip install matplotlib`).
"""
import csv
import json
import os
import sys

import matplotlib.pyplot as plt

RESULTS_DIR = os.path.join("sql_benchmarks", "experiments", "results")

# selectivity token -> (label, x-position)
SEL = [("0_1", "0.1%"), ("1", "1%"), ("5", "5%"),
       ("10", "10%"), ("20", "20%"), ("filler", "scan")]


def _token(asset):
    for tok, _ in SEL:
        suffix = "q_filler" if tok == "filler" else f"q_{tok}_percent"
        if asset.endswith(suffix):
            return tok
    return None


def load(cid, partition):
    """engine -> {sel_token: (median_ms, min_ms, max_ms)}"""
    out = {}
    path = os.path.join(RESULTS_DIR, cid, f"{cid}.csv")
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["Partition"] != partition:
                continue
            tok = _token(r["Asset"])
            if tok is None:
                continue
            out.setdefault(r["Engine"], {})[tok] = (
                float(r["Duration"]) * 1000,
                float(r["Duration_Min"]) * 1000,
                float(r["Duration_Max"]) * 1000,
            )
    return out


def series(data, engine):
    xs, ys, lo, hi = [], [], [], []
    for i, (tok, _) in enumerate(SEL):
        if engine in data and tok in data[engine]:
            m, a, b = data[engine][tok]
            xs.append(i); ys.append(m); lo.append(m - a); hi.append(b - m)
    return xs, ys, lo, hi


def main():
    indexed = sys.argv[1] if len(sys.argv) > 1 else "461beee8"
    noindex = sys.argv[2] if len(sys.argv) > 2 else "28f7aa1c"
    partition = sys.argv[3] if len(sys.argv) > 3 else "large"
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
        "docs", "figures", f"selectivity_{indexed}.png")

    idx = load(indexed, partition)
    noi = load(noindex, partition)

    meta_path = os.path.join(RESULTS_DIR, indexed, f"metadata_{indexed}.json")
    env = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            env = json.load(f).get("environment", {})

    # lane -> (source data, engine key, label, color, marker, linestyle)
    lanes = [
        (idx, "duckdb",         "DuckDB in-process",        "#2f6f4f", "o", "-"),
        (idx, "quack_pushdown", "Quack pushdown",           "#3b6ea5", "^", "-"),
        (idx, "quack",          "Quack attach",             "#b3402a", "s", "-"),
        (idx, "postgres",       "PostgreSQL + index",       "#7a5ea8", "D", "-"),
        (noi, "postgres",       "PostgreSQL no index",      "#999999", "v", "--"),
    ]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for data, eng, label, color, marker, ls in lanes:
        xs, ys, lo, hi = series(data, eng)
        if not xs:
            continue
        ax.errorbar(xs, ys, yerr=[lo, hi], label=label, color=color,
                    marker=marker, linestyle=ls, capsize=3, linewidth=1.8,
                    markersize=6)

    ax.set_yscale("log")
    ax.set_xticks(range(len(SEL)))
    ax.set_xticklabels([lbl for _, lbl in SEL])
    ax.set_xlabel("predicate selectivity (fraction of rows matched)")
    ax.set_ylabel("query time (ms, log scale) — cold cache, 5 reps")
    rows = "10M" if partition == "large" else "1M"
    ax.set_title(f"Selectivity sweep @ {rows} rows: where does the index help — and hurt?")

    # Annotate the Postgres-index plan transitions (EXPLAIN-verified).
    if "postgres" in idx:
        ax.annotate("Index-Only Scan", xy=(0, idx["postgres"]["0_1"][0]),
                    xytext=(0.1, idx["postgres"]["0_1"][0] * 0.45),
                    fontsize=8, color="#7a5ea8")
        if "5" in idx["postgres"]:
            ax.annotate("Bitmap Heap Scan\n(index becomes a liability)",
                        xy=(2, idx["postgres"]["5"][0]),
                        xytext=(2.35, idx["postgres"]["5"][0] * 0.62),
                        fontsize=8, color="#7a5ea8",
                        arrowprops=dict(arrowstyle="->", color="#7a5ea8", lw=0.8))

    ax.grid(True, which="both", axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=9, loc="center right")

    sub = f"capsules {indexed} (indexed) + {noindex} (no index)"
    if env:
        cores = env.get("cpu_count_logical")
        bits = [env.get("os", ""), env.get("machine", "")]
        if cores:
            bits.append(f"{cores} cores")
        sub += "  ·  " + ", ".join(b for b in bits if b)
    fig.text(0.5, 0.005, sub, ha="center", fontsize=7.5, color="#666666")

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
