# Experiment Registry — sqlbenchdag

Meta-log of experiments run against the lab. Each entry defines a **research
question** (what we're trying to learn), its **control conditions** (held
constant), its **variable** (typically the agent's model), and a running
table of per-model outcomes.

Distinct from the other docs:

- `docs/dual_agent_collaboration.md` — the per-run journal (SBD-N specimens,
  narrative and process detail per run).
- `docs/published_capsules.md` — the sealed SQL findings themselves, cited
  by published capsule IDs.
- `TODO.md` — architectural gaps and their fixes.

**How this file relates to the journal.** Each row in this registry cross-
references the corresponding specimen(s) in the journal. The registry is the
tabular index; the journal is the prose. A reader asking *"what have we
tested and how did each model do?"* comes here first, then follows the
cross-reference for depth.

**Why this file exists.** Ramona's framing (2026-07-04): *"each model will be
able to carry experiments differently. or maybe just 2 big categories: local
and frontier. but maybe there are variations, maybe we observe different
failings. who knows?"* — that's not a bookkeeping problem, that's a research
subject. The registry is the corpus for the research subject *"how does
model capability shape agent workflow success on the lab?"* — categories
will emerge from the data, not the other way around.

---

## Experiment: DuckDB analytical-aggregation scaling

**Question.** How does DuckDB's aggregate query time scale with data size,
and is scaling roughly linear (2× rows → 2× time) or something structurally
different?

**Control conditions (held constant across model runs).**

- Suite: `analytical_wall`
- Engines: `[duckdb]` only (no Docker required)
- Dataset template: adapted from `experiments/queue/quickstart.yaml` —
  `analytical_data` table with `region`, `category`, `price`, `quantity`,
  `discount` columns
- Matrix dimension: `rows` (swept across small/medium/large scales)
- Replication: 3–5 per scale (agent chooses within a reasonable range)
- Goal handed to the agent: verbatim reproducible across runs (see SBD-1's
  specimen for the string)

**Variable.** The agent's LLM. Each row below is one model attempting the
same goal against the same lab.

**Per-model outcomes:**

| Model | Date | Local capsule | Outcome | Turns | Notes / cross-ref |
|---|---|---|---|---|---|
| `anthropic/claude-sonnet-5` | 2026-07-04 | `162bbce7` | ✅ clean end-to-end; two-regime scaling diagnosis with checked arithmetic | 11 | SBD-1. Correctly picked `compare_engines_by_partition` + `get_experiment_result` for a scaling question; produced fluent diagnostic prose; caveats named honestly. |
| `ollama/llama3` (8B, local) | 2026-07-04 | — (no capsule) | ❌ workflow-capability failure — `MAX_EMPTY_RESPONSES=3` ceiling at turn 23/25 | 23 | SBD-2. Model produced three non-actionable responses in a row; `run_agent()`'s bailout fired as designed. New failure class in the taxonomy — see journal. |

**Follow-up experiments this one could seed.**

- Same goal at broader scale range (add a `xlarge` = 100M rows point) to
  confirm the two-regime story past 10M and test the `scaling_depth`
  cross-reference SBD-1 flagged.
- Same setup, different suite (e.g., `sort_spill`, `hypergraph`) to check
  whether the two-regime pattern is aggregation-specific or general.
- Multi-engine variant (add postgres via Docker) — different research
  question (cross-engine at scale) but shares the dataset template.

---

## Conventions

**Row shape:** `model`, `date`, `capsule (local)`, `outcome` (✅/❌/⚠️ + one-
liner), `turns`, `notes/cross-ref`. Capsule IDs cited here are LOCAL runs,
not published capsules — same convention as the journal (see the journal's
Conventions note for the verify_doc_claims exemption).

**When to add a new experiment section.** When the *question* changes.
Same question with different models → new row in the existing section. New
question → new section.

**When to split into a per-experiment file.** When any single experiment
section grows past ~5 model runs or accumulates enough per-model notes that
it dominates this file. At that point promote to `docs/experiments/<name>.md`
and leave a one-line stub here linking to it. Small now, plan for growth,
don't split prematurely.

**Failure classification (emerging).** No fixed taxonomy — Ramona's framing
is that categories emerge from N=5–10 model runs. What's been seen so far:

- **Clean success** — SBD-1 (claude-sonnet-5). Tool selection, arithmetic,
  diagnostic prose, honest caveats all present.
- **Workflow-capability failure** — SBD-2 (ollama/llama3, 8B). Not a schema
  error, not a tool-selection error, not a rate limit. The model just
  stopped producing actionable output — three non-actionable responses in
  a row, `MAX_EMPTY_RESPONSES` bailout fires. Distinct from turn-budget
  exhaustion (that's when the model makes progress but runs out of time).
  This is the model *unable to produce the workflow output at all* despite
  having the tools available.

Other categories to watch for as the corpus grows:

- **Prereq failure** (daemon down, key missing, etc.) — not really "the
  model failed"; environmental. SBD-2's first attempt (ollama down).
- **Schema construction failure** (agent can't produce valid YAML from the
  template).
- **Tool-selection failure** (picked `compare_engines` when the question
  needed `compare_engines_by_partition`, etc.). v4 hit this shape.
- **In-context arithmetic failure** (couldn't compute simple ratios /
  didn't do the scaling analysis).
- **Turn budget exhausted** — hit `MAX_TURNS=25`. Different from workflow-
  capability failure: turn-budget means the model was making progress but
  ran out of time; workflow-capability means the model *stopped producing
  actionable output*.
- **External rate limit** — v6 pattern; not really the model failing at the
  lab, but worth recording so it's not confused with a model failure.

Don't force runs into these buckets prematurely. When the data suggests a
category that's not on this list, name it and add it.
