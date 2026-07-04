# Dual-Agent Collaboration Journal — sqlbenchdag

Running log of meaningful agent-driven interactions with the SQL Benchmarking
Laboratory. Companion to the testbed's `dual_agent_collaboration.md` —
same discipline (numbered specimens, sealed evidence, cross-agent
verification), different object of study.

This journal is about **the agent's use of the lab**, not the lab's
architecture (that's `TODO.md`) and not the lab's SQL findings (those are
sealed in capsules under `sql_benchmarks/experiments/results/` and cited in
`docs/published_capsules.md`).

Specimens numbered SBD-1, SBD-2, ... (S = sqlbenchdag) so they don't
collide with testbed numbering when the two journals get cross-referenced.

Newest first.

---

## SBD-1. First end-to-end agent run against the completed toolbox — clean loop, real scaling analysis (2026-07-04, model: `anthropic/claude-sonnet-5`, capsule: `162bbce7`)

**Context.** Punch list of 7 gaps surfaced by the v4 + v5 live-fires (see TODO.md, PRs #109–#124) all closed. This run was the verification pass: does the agent now use the tools well and produce a real answer to the same class of question that stumped v4?

**Goal given to the agent (verbatim):**

> *"Investigate how DuckDB performance scales on analytical aggregation queries. Test at least three data scales — small, medium, and something larger. Report the mean duration per scale, and whether the scaling looks roughly linear (2x rows → 2x time) or something different. DuckDB only, no Docker."*

**Tool sequence (11 turns, zero failed submissions, zero guessing):**

1. `list_suites`
2. `list_templates`
3. `get_template` ×2 (comparing candidates)
4. `submit_experiment` → `experiment_id: 162bbce7`
5. `get_experiment_status` ×6 — **5× `running`, then `complete`** — Gap 1 (running marker) empirically confirmed in the wild; agent saw the transition and never re-submitted
6. `compare_engines_by_partition` (Gap 3 tool, new)
7. `get_experiment_result` (Gap 4 tool, new)
8. Final analysis

**The agent's answer:**

| Scale | Rows | Mean duration | Spread (5 reps) |
|---|---|---|---|
| small | 100,000 | 7.34 ms | 6.96–7.57 ms |
| medium | 1,000,000 | 12.59 ms | 11.13–15.03 ms |
| large | 10,000,000 | 93.16 ms | 82.7–99.98 ms |

Diagnosis (agent's own): **two distinct scaling regimes**:
- small → medium (10× rows): 1.72× time — fixed overhead dominates
- medium → large (10× rows): 7.40× time — actual compute cost dominates, close to linear

**How the agent produced the analysis (checkable trace).** No external script, no reporting tool, no `bash` or `python` invocation. Two data-fetching tool calls (`compare_engines_by_partition` and `get_experiment_result`) returned the ground-truth numbers. The agent then:

- Read means directly from `compare_engines_by_partition`.
- Computed spread ranges by inspecting the `durations_raw` field per fragment from `get_experiment_result`.
- Computed multipliers by arithmetic in-context (`12.59 / 7.34 = 1.72`; `93.16 / 12.59 = 7.40` — both check out).
- Formed the two-regime diagnosis as its own inference (a real, known pattern in vectorized analytical engines — not hallucinated).
- Cross-referenced `sql_benchmarks/experiments/queue/scaling_depth.yaml` (which does exist; the agent saw it in `list_templates` output).

**Load-bearing property this run empirically confirms.** Measurement is the sealed capsule's job; interpretation is the agent's job; verification is possible because the arithmetic is checkable against the trace. That is the whole point of the lab. This is the first end-to-end demonstration.

**Cross-reference to prior live-fires (all in the punch-list PRs):**

- **v4** (same goal, pre-fix, gpt-4o): aggregate `mean 0.021s`, agent conceded *"the experiment data did not explicitly differentiate mean times per scale."*
- **v5** (multi-engine, pre-fix): failed on hallucinated table names + engine ambiguity in error detail; 15+ turns of guessing.
- **v6** (same goal, post-fix, gpt-4o): experiment ran cleanly server-side; agent crashed on OpenAI rate limit before reasoning about results.
- **v6.5** (same goal, post-fix, claude-sonnet-5): **this run.** Clean.

The delta between v4 and v6.5 is the entire punch list.

**What this run cannot claim.** N=1 experiment (5 reps, but one config). Three scale points don't confirm the linearity story past 10M rows. The agent honestly named these limits as caveats in its final answer, including a cross-reference to `scaling_depth` which specifically probes higher scales.

**What is worth naming beyond the immediate result.** The agent's failure modes documented across v4–v5 (misdirection under ambiguous errors, resubmit-under-queued-stall, reverse-engineering SQL contracts) are the same *class* of failure the testbed's specimens describe: agents perform structure-compliance under pressure (schema-satisfying YAML, apparent-recovery guesses) while substance drifts. The sqlbenchdag lab addresses that class by making the substance externally verifiable — every claim traces to a sealed measurement, every tool response is JSON with checkable numbers, the agent's arithmetic can be independently confirmed against the trace. That is the same principle the testbed applies to LLM-behavior measurement; here it applies to LLM *tool-use* measurement. — [C]

---

## Conventions

- Newest specimen at the top.
- Each specimen records: model used, capsule ID (if any), tool sequence, the agent's answer, and — critically — *how* the agent arrived at the answer (which sources were data, which were inference, whether the arithmetic is checkable).
- If the agent produces a numerical claim, the source of each number is named. The lab is verifiable by design; the journal preserves the verifiability trail.
- Failures get recorded with the same discipline as successes — a failed run + its actionable error text is data.
- `[C]` = Claude, `[G]` = Gemini, `Ramona` = the human owner. Attribution matters when the collaboration involves multiple agents.

**Capsule ID citations in this file are LOCAL, not published.** A reader tracing an ID like `162bbce7` will not find it in the git-tracked `results/` tree — these are transient live-fire runs. Reproducibility works differently here: the reader re-runs the same YAML at the same code SHA and derives the same ID from the hasher. The published-capsule discipline (see `docs/published_capsules.md`, `scripts/tools/verify_doc_claims.py`) applies to publication-grade claims; this journal is a run log, and the verifier is configured to skip it (`LIVE_FIRE_JOURNALS` in the verifier).
