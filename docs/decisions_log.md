# Decisions Log — sqlbenchdag

Append-only, chronological record of architectural and design decisions
made during the sqlbenchdag build. Companion to
`dual_agent_collaboration.md` (agent-integrity specimens) and
`experiment_registry.md` (agent-run corpus).

**What goes here.** Decisions with forks — chose A over B, and here's the
consequence. Not every code change, not every fix, not every PR.

**Why this file exists.** Ramona's own note-taking gap: work moves fast,
context accumulates in conversation, and the same architectural questions
get rediscovered days later. Session transcripts capture the raw
back-and-forth (`~/.claude/projects/…/*.jsonl`); this file captures the
*distilled* decisions.

Newest last.

---

## 2026-07-04 — Fork B (sealed analysis) over Fork A (sealed measurement only)

**Decision.** The lab will incrementally extend the seal from raw
measurement (fragments + integrity.seal + OTS proof) to also cover the
agent's analysis of that measurement, including the tool-call trace, the
derived-projection values, the model identifiers, and the final analysis
text.

**Fork closed.** Fork A: analysis stays downstream and unsealed,
multiple analyses of the same capsule are legitimate and fluid.

**Fork opened.** Sealed analyses become comparable across
agents/models. "Model X's sealed analysis of capsule C vs Model Y's
sealed analysis of capsule C" becomes a first-class study.

**Why.** Specimens `[[agent-integrity-incidents]]` #9 (rigor-theater,
non-lab work framed as lab-grade) and #10 (unfounded specificity,
"deeply nested" without reading the generator) both operated on sealed
data and produced misleading claims with the seal's reflected authority.
The seal defended the inputs; it did nothing for the interpretation.
Extending it plugs the exact hole the incident catalog keeps circling.
Also: Ramona's reframe — *"testbed applied to an agent using the
lab"* — makes sealed-analysis-on-sealed-measurement the natural
convergence of the two labs into one measurement stack.

**How.** Not "flip the switch now". Build the next iteration
Fork-B-compatible even while nominally on Fork A: content-addressed tool
inputs, deterministic tool outputs, fragment-ID provenance in every
projection payload. Decide the flip after 2–3 more live-fire runs.

**Cross-refs.** SBD-3, SBD-4, `[[agent-integrity-incidents]]` #9 #10 #12.

---

## 2026-07-04 — Two-level capsule ID (config_id + run_id) flagged as future work

**Decision.** The current single-level capsule ID (`hash(config +
code_sha)`) is preserved for now, but future longitudinal work will
require a two-level ID.

**Fork closed.** None — this is a *pre-declared* fork, made explicit
before it becomes urgent.

**Fork opened.** When longitudinal comparison (same experiment
definition, multiple runs, "what changed") becomes an active goal, the
hasher, coordinator, registry, and every doc citing the 8-hex ID will
need to migrate to `config_id` (experiment definition) + `run_id`
(specific execution). Registry gains a `run_id → config_id` reverse
index.

**Why.** Current ID by construction dedupes re-runs. That is correct for
the reproducibility story ("same inputs → same ID → same capsule") but
actively prevents the longitudinal question Ramona wants to ask ("run
this again next month with newer Postgres, keep both"). Flagged now so
in-flight work (granular projections) doesn't paint the surface into a
corner.

**How to build toward it.** Projection tools should accept `run_id` OR
`config_id` and return one-run vs all-runs accordingly. This keeps the
option open at almost no cost today.

**Cross-refs.** `[[two-modes-hash-discipline]]` (edit code freely,
hash-discipline only at publish freeze — this decision is inside the
"edit freely" mode, tightening only when we ship).

---

## 2026-07-04 — Capsule reference: registry file in-repo, not a bespoke URI scheme

**Decision.** Capsules are referenced by (a) their 8-hex Experiment ID,
(b) resolved via `docs/capsule_registry.json` which maps
`exp_id → {github_path, commit_sha, release_tag, zenodo_doi (if any),
ots_proof, sealed_at}`, (c) via a `sqlbench locate <exp_id>` helper.

**Fork closed.** Inventing a `sqlbench://` URI scheme. Schemes are only
useful with a resolver, and inventing infra costs more than it earns
until there's a corpus that justifies it.

**Fork opened.** Multi-source durability: GitHub URLs (with commit_sha)
for daily use, Zenodo DOIs for archival guarantee once the CITATION.cff
+ ORCID work reaches release-scoped Zenodo deposits (see
`[[orcid-and-citation]]`).

**Why.** A mapping table beats a bespoke identifier scheme when the
resolver problem isn't solved. Cheap to add, cheap to maintain, cheap to
delete if the answer changes.

**Cross-refs.** `[[orcid-and-citation]]`, `[[packaging-state]]`.

---

## 2026-07-04 — Granular result-reader tools: human-and-agent parity

**Decision.** Every granular projection tool exposed to the agent MUST
also be available to humans, via the same underlying function. Three
surfaces on one core:

- Core Python function in `sql_benchmarks/api/logic/`.
- REST endpoint in `sql_benchmarks/api/routers/results.py` (thin
  wrapper).
- CLI command in `sql_benchmarks/cli.py` (thin wrapper).

**Fork closed.** Agent-exclusive tooling. If a tool is useful for
analyzing a capsule, it is useful to the human running the lab too.
No divergence.

**Fork opened.** A Jupyter notebook `import`s the projection function
directly; the shell gets a one-liner; the agent gets an HTTP endpoint.
Same code path.

**Why.** Ramona: *"if someone runs the lab, they should have access
to the same tools."* Also: this is the design that makes the granular
tools sealable eventually (Fork B) — the projection is a function of
its inputs, invoked identically from any surface.

**Cross-refs.** Planned scope in TODO.md; upcoming PR sequence.

---

## 2026-07-04 — Order of upcoming work: JSONL logging before granular tools

**Decision.** Structured JSONL agent logging (TODO #10) ships before the
granular projection tools.

**Fork closed.** Building the projections first and instrumenting them
later.

**Fork opened.** When the granular tools land, the JSONL logger already
captures *which projection the agent asked for at each turn* — the
capability signal Ramona wants to measure ("did the model know to ask
for the summary?"). Building the tools without the logger means
shipping and being blind to how they get used.

**Cross-refs.** SBD-2 (llama3 workflow-capability failure — the failure
whose category is currently opaque because no per-turn trace exists).
TODO.md #10.

---

## 2026-07-04 — Proactive recording of decisions/rules/specimens (Claude's operating rule)

**Decision.** Claude will proactively record, without being asked, when
any of these are observed in conversation:

1. A generalizable rule/preference from Ramona → save as feedback memory.
2. A specimen of an agent-integrity failure → append to
   `docs/dual_agent_collaboration.md` + update `[[agent-integrity-incidents]]`.
3. An architectural decision or fork → append to this file
   (`docs/decisions_log.md`).
4. An observation about research direction or lab relationships →
   project memory.
5. New external context (people, deadlines, commitments) → project
   memory.

**Fork closed.** Ramona having to say *"record this"* for every item.
The friction was hers to eat; now it isn't.

**Fork opened.** The trace of Ramona's decisions and Claude's operating
rules becomes durable and self-maintained. If the criteria are wrong,
Ramona corrects and the criteria update.

**Why.** Ramona: *"we move very fast, and i process and do things w/o
taking notes anymore (sigh), and i want to be able to track these
thoughts and ideas and not keep rediscovering them."* The gap being
plugged is her own trace mechanism, and the same discipline the lab
applies to measurements applies to the meta-work: distill, seal (via
git commit), keep.

**Cross-refs.** Saved as feedback memory `[[proactive-recording]]`.

---

## 2026-07-04 — Granular projections shipped (all four, three surfaces each)

**Decision.** Ship all four granular projections in one iteration —
`get_means_by_partition`, `get_scaling_factor`,
`get_replication_stability`, `get_experiment_summary` — each exposed on
three surfaces (Python function, REST endpoint, CLI subcommand), each
returning a `provenance` block naming the fragments consumed.

**Fork closed.** Ship-one-at-a-time. There was no reason to sequence
the four; they share a core (fragment reading + statistical primitives)
and shipping together makes the parity constraint enforceable in one
test suite. Every projection is tested three times: as Python function,
as REST endpoint (matching the Python function's output), and as CLI
subcommand (matching the Python function's output). If any surface
drifts, one of those tests fails.

**Fork opened.** Skills work (next scope item) can point at these
tools by name. Sealed-analysis work (Fork B) has the provenance
receipts it needs — every projection call is a small sealable object.

**Why.** The context-budget problem this scope was named to solve.
Raw `get_experiment_result` can be many KB of JSON per experiment;
`get_experiment_summary` collapses that to a small dict + a prose
narrative. Weaker-context models can drive the lab if they know to
ask for the summary; *whether they know to ask* is itself a
capability signal worth measuring — the [[proactive-recording]]
JSONL logger captures which projection each turn used.

Human-and-agent parity: `sqlbench project means <id>` (CLI),
`GET /v1/results/<id>/projections/means` (REST), and
`from sql_benchmarks.api.logic.projections import get_means_by_partition`
(Python) all hit the same core function.

**Cross-refs.** PR shipping this decision. Next scope item: skills.

---

## 2026-07-04 — Skills as a tactical playbook, loaded into the system prompt

**Decision.** Add `skills/*.md` at repo root. Two shipped: `build_scaling_experiment.md`, `read_experiment_results.md`. Loader (`autonomous_agent.load_skills`) concatenates all `.md` in the dir into a `# Skills` section appended to the system prompt after AGENTS.md.

**Fork closed.** Skills as agent-callable tools (`list_skills` / `get_skill`). Deferred — upfront loading is fine while the corpus is small, and it removes a turn from the agent's loop.

**Fork opened.** Any new precise procedure gets a new file — no code change needed. Human-readable too (`cat skills/*.md`).

**Why.** SBD-2's llama3 failure was partly workflow-capability, partly no procedural anchor. Skills compress the exploration space: template-adapt pattern, common pitfalls (each has broken a previous run), decision table for which projection to use.

**Cross-refs.** SBD-2, `[[proactive-recording]]`, granular projections entry above.
