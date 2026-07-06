#!/usr/bin/env python3
"""Grade agent final answers against the capsule's ground truth.

Closes the process-vs-truth gap: behavioral markers (analyze_agent_traces)
measure HOW the agent worked; this grades WHETHER the numbers it published
are true. A run can have perfect markers and a wrong conclusion — specimen
#9's lesson — so correctness is graded deterministically against the
sealed fragments, never against the agent's self-report.

Per graded run:
  coverage    — fraction of ground-truth per-(partition,engine) means the
                answer states (unit-aware, within tolerance).
  accuracy    — of the duration claims made, fraction that match SOME
                derivable statistic (mean/std/min/max per partition-engine).
  unmatched   — duration claims matching NO derivable statistic: candidate
                fabrications, listed verbatim.
  ratio_check — of the "N x" scaling claims, fraction matching a derivable
                ratio (any pairwise partition-mean ratio, either direction,
                or a row-count ratio from the config).
  verdict     — PASS   coverage == 1, no unmatched claims
                PARTIAL coverage == 1, some unmatched claims
                FAIL    any ground-truth mean misstated or absent

Tolerances: durations 2% relative; ratios 5% relative (agents round).

Usage:
  python scripts/tools/grade_analyses.py [trace-glob ...]
Stdlib only.
"""
import glob as globlib
import json
import os
import re
import sys
from collections import defaultdict
from statistics import mean

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_GLOB = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "agent_runs", "*.jsonl")
RESULTS_DIR = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")

# Unit may be wrapped in LaTeX (`$5.83\text{ ms}$` — gemini-3.5-flash writes
# math notation) — allow an optional `\text{` between number and unit.
DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:\\text\{)?\s*(ms|milliseconds|s\b|seconds)", re.IGNORECASE)
# Ratio may be `12.2x`, `12.2×`, or LaTeX `12.2\times`.
RATIO_RE = re.compile(r"[~≈]?(\d+(?:\.\d+)?)\s*(?:[x×]\b|\\times)")
EXP_ID_RE = re.compile(r"^[0-9a-f]{8}$")

DUR_TOL = 0.02   # 2% relative on durations
RATIO_TOL = 0.05  # 5% relative on ratios


def load_ground_truth(exp_id: str):
    """Derivable statistics from the sealed capsule. Returns
    (means, all_stats, ratios) where means maps (partition, engine) -> mean
    in ms, all_stats is a flat list of every derivable ms quantity, and
    ratios is the set of derivable scaling factors."""
    frag_dir = os.path.join(RESULTS_DIR, exp_id, "fragments")
    if not os.path.isdir(frag_dir):
        return None
    means, all_stats = {}, []
    for fn in os.listdir(frag_dir):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(frag_dir, fn)) as f:
            frag = json.load(f)
        part = frag["meta"]["partition"]
        eng = frag["meta"]["engine"]
        # Key by ASSET too: suites like selectivity run several benchmarks
        # per partition (q_0_1_percent, q_10_percent, …). Pooling them into
        # one per-partition mean produced a number no honest answer would
        # cite — the first grade of the edge-1 corpus flagged two false
        # FAILs exactly this way.
        asset = frag["meta"].get("asset", "")
        raw = frag["metrics"].get("durations_raw") or [frag["metrics"]["duration_seconds"]]
        raw_ms = [v * 1000 for v in raw]
        m = mean(raw_ms)
        means[(asset, part, eng)] = m
        # Every statistic an honest answer might cite for this fragment.
        all_stats.extend(raw_ms)
        all_stats.append(m)
        all_stats.extend([min(raw_ms), max(raw_ms)])
        if len(raw_ms) >= 2:
            s = (sum((v - m) ** 2 for v in raw_ms) / (len(raw_ms) - 1)) ** 0.5
            all_stats.extend([s, m - s, m + s])
            all_stats.append(100 * s / m if m else 0)  # CV in %

    # Derivable scaling ratios: any pairwise mean ratio (either direction)…
    ratios = set()
    vals = list(means.values())
    for a in vals:
        for b in vals:
            if a and b and a != b:
                ratios.add(b / a)
    # …plus row-count ratios from the archived config (agents cite "10x rows").
    cfg = os.path.join(RESULTS_DIR, exp_id, "experiment_config.yaml")
    row_counts = []
    if os.path.exists(cfg):
        with open(cfg) as f:
            for line in f:
                mrow = re.match(r"\s+\w+:\s*([\d_]+)\s*$", line)
                if mrow:
                    try:
                        row_counts.append(int(mrow.group(1).replace("_", "")))
                    except ValueError:
                        pass
    for a in row_counts:
        for b in row_counts:
            if a and b and a != b:
                ratios.add(b / a)
    return means, all_stats, ratios


def _close(claim, truth, tol):
    return truth and abs(claim - truth) / abs(truth) <= tol


def extract_answer_and_exp(path: str):
    """Final-answer text + the experiment_id the run worked with."""
    answer = None
    exp_ids = []
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        if e["event"] == "final_answer":
            answer = e.get("content") or answer
        elif e["event"] == "tool_call":
            arg = (e.get("arguments") or {})
            eid = arg.get("experiment_id") if isinstance(arg, dict) else None
            if eid and EXP_ID_RE.match(str(eid)):
                exp_ids.append(eid)
    exp_id = max(set(exp_ids), key=exp_ids.count) if exp_ids else None
    return answer, exp_id


def grade(path: str):
    answer, exp_id = extract_answer_and_exp(path)
    if not answer or not exp_id:
        return None
    gt = load_ground_truth(exp_id)
    if gt is None:
        return {"run": os.path.basename(path), "exp_id": exp_id,
                "verdict": "NO-CAPSULE", "detail": "capsule not on disk"}
    means, all_stats, ratios = gt

    # Duration claims, normalized to ms
    claims = []
    for num, unit in DURATION_RE.findall(answer):
        v = float(num)
        claims.append(v * 1000 if unit.lower().startswith("s") else v)

    covered = {k: any(_close(c, m, DUR_TOL) for c in claims) for k, m in means.items()}
    matched = [c for c in claims if any(_close(c, s, DUR_TOL) for s in all_stats)]
    unmatched = [c for c in claims if c not in matched]

    ratio_claims = [float(x) for x in RATIO_RE.findall(answer)]
    ratio_ok = [r for r in ratio_claims if any(_close(r, t, RATIO_TOL) for t in ratios)]

    coverage = sum(covered.values()) / len(covered) if covered else 0.0
    # Verdicts are grounded in CLAIM ACCURACY, not exhaustive coverage —
    # goals legitimately target a subset of a suite's benchmarks (edge-1
    # selectivity asks about 2 of 6 queries), so demanding every fragment
    # be cited would flag honest answers. Rules:
    #   PASS    every duration claim matches a derivable statistic, and at
    #           least one ground-truth mean is cited (numbers trace to THIS
    #           capsule).
    #   PARTIAL some claims match nothing derivable — flagged verbatim for
    #           human review (extrapolations and misstatements both land
    #           here; a mechanical grader flags, it doesn't convict).
    #   FAIL    no cited number corresponds to the capsule at all.
    coverage_any = any(covered.values())
    if claims and coverage_any and not unmatched:
        verdict = "PASS"
    elif coverage_any and unmatched:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return {
        "run": os.path.basename(path).removesuffix(".jsonl"),
        "exp_id": exp_id, "verdict": verdict,
        "coverage": round(coverage, 3),
        "duration_claims": len(claims), "matched": len(matched),
        "unmatched_claims_ms": [round(u, 3) for u in unmatched],
        "ratio_claims": len(ratio_claims), "ratio_matched": len(ratio_ok),
        "missing_means": [f"{a}/{p}/{e}" for (a, p, e), ok in covered.items() if not ok],
    }


def main():
    patterns = sys.argv[1:] or [RUNS_GLOB]
    paths = sorted(p for pat in patterns for p in globlib.glob(pat))
    graded = [g for g in (grade(p) for p in paths) if g]
    if not graded:
        print("no gradeable runs (need final_answer + experiment_id + capsule on disk)")
        return
    by_verdict = defaultdict(int)
    for g in graded:
        by_verdict[g["verdict"]] += 1
        flag = "" if g["verdict"] == "PASS" else "  <-- " + (
            f"unmatched={g['unmatched_claims_ms']}" if g["verdict"] == "PARTIAL"
            else f"missing={g.get('missing_means')} unmatched={g.get('unmatched_claims_ms')}")
        print(f"{g['run']}  exp={g['exp_id']}  {g['verdict']:<9} "
              f"cov={g.get('coverage', '-')} claims={g.get('duration_claims', '-')} "
              f"ratios={g.get('ratio_matched', '-')}/{g.get('ratio_claims', '-')}{flag}")
    total = len(graded)
    print(f"\n{total} graded: " + ", ".join(f"{k}={v}" for k, v in sorted(by_verdict.items())))


if __name__ == "__main__":
    main()
