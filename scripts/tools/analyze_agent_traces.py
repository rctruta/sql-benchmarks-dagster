#!/usr/bin/env python3
"""Extract behavioral markers from agent-run JSONL traces and group them
by prompt composition (the `prompt_provenance` event) — the analysis half
of the attribution instrument.

Markers per run:
  outcome            run_end outcome
  turns              turns used
  tokens             prompt+completion total
  first_tool         first tool called
  category_filtered  did any list_suites call pass `category`?
  unfiltered_suites  did any list_suites call omit `category`? (anti-marker)
  template_first     was get_template called before the first submit_experiment?
  projections_used   which of the four granular projections were called
  raw_result_used    did it call get_experiment_result? (anti-marker)

Usage:
  python scripts/tools/analyze_agent_traces.py [glob ...]
Defaults to all traces under sql_benchmarks/experiments/agent_runs/.
Stdlib only.
"""
import glob as globlib
import json
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_GLOB = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "agent_runs", "*.jsonl")
PROJECTIONS = {"get_experiment_summary", "get_means_by_partition",
               "get_scaling_factor", "get_replication_stability"}


def extract_markers(path: str) -> dict:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    markers = {
        "run_id": os.path.basename(path).removesuffix(".jsonl"),
        "model": None, "flags": {}, "composition": None,
        "outcome": None, "turns": 0, "tokens": 0,
        "first_tool": None, "category_filtered": False,
        "unfiltered_suites": False, "template_first": None,
        "projections_used": [], "raw_result_used": False,
    }
    seen_get_template = False
    seen_submit = False
    projections = []

    for e in events:
        ev = e["event"]
        if ev == "run_start":
            markers["model"] = e.get("model")
        elif ev == "prompt_provenance":
            markers["flags"] = e.get("ablation_flags") or {}
            comps = e.get("components") or {}
            # Composition fingerprint: sorted "name:sha8|name:None" string
            parts = []
            for name in sorted(comps):
                v = comps[name]
                parts.append(f"{name}:{v['sha256'][:8] if v else 'ABSENT'}")
            markers["composition"] = "|".join(parts)
        elif ev == "model_response":
            u = e.get("usage") or {}
            markers["tokens"] += (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        elif ev == "tool_call":
            name = e.get("name")
            if markers["first_tool"] is None:
                markers["first_tool"] = name
            if name == "list_suites":
                args = e.get("arguments") or {}
                if isinstance(args, dict) and args.get("category"):
                    markers["category_filtered"] = True
                else:
                    markers["unfiltered_suites"] = True
            elif name == "get_template":
                seen_get_template = True
            elif name == "submit_experiment":
                if not seen_submit:
                    markers["template_first"] = seen_get_template
                seen_submit = True
            elif name in PROJECTIONS:
                projections.append(name)
            elif name == "get_experiment_result":
                markers["raw_result_used"] = True
        elif ev == "run_end":
            markers["outcome"] = e.get("outcome")
            markers["turns"] = e.get("turns_used") or 0

    markers["projections_used"] = sorted(set(projections))
    return markers


def condition_label(flags: dict) -> str:
    """Short label from ablation flags for grouping."""
    if not flags:
        return "pre-provenance"
    if flags.get("architecture") == "specialist":
        return f"specialist:{flags.get('role')}"
    a = flags.get("include_agents_md")
    s = flags.get("include_skills")
    if a is None and s is None:
        return "monolith"
    return f"monolith(agents_md={'Y' if a else 'N'},skills={'Y' if s else 'N'})"


def main():
    patterns = sys.argv[1:] or [DEFAULT_GLOB]
    paths = sorted(p for pat in patterns for p in globlib.glob(pat))
    if not paths:
        print(f"no traces matched: {patterns}")
        sys.exit(1)

    rows = [extract_markers(p) for p in paths]
    by_condition = defaultdict(list)
    for r in rows:
        by_condition[condition_label(r["flags"])].append(r)

    for cond in sorted(by_condition):
        group = by_condition[cond]
        print(f"\n=== {cond}  (n={len(group)}) ===")
        for r in group:
            proj = ",".join(p.replace("get_", "").replace("_by_partition", "")
                            .replace("experiment_", "") for p in r["projections_used"]) or "-"
            print(f"  {r['run_id']}  outcome={r['outcome'] or 'NO-RUN-END':<13} turns={r['turns']:>2} "
                  f"tokens={r['tokens']:>7}  first={r['first_tool'] or '-':<16} "
                  f"catfilter={'Y' if r['category_filtered'] else 'n'} "
                  f"tmpl_first={'Y' if r['template_first'] else ('n' if r['template_first'] is False else '-')} "
                  f"proj=[{proj}] raw={'Y' if r['raw_result_used'] else 'n'}")
        ok = [r for r in group if r["outcome"] == "final_answer"]
        if group:
            mean_tokens = sum(r["tokens"] for r in group) / len(group)
            print(f"  -- success {len(ok)}/{len(group)}, mean tokens {mean_tokens:,.0f}")


if __name__ == "__main__":
    main()
