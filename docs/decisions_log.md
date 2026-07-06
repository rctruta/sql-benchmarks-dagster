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

---

## 2026-07-04 — Category taxonomy for suites (and capsules by inheritance)

**Decision.** Add `sql_benchmarks/experiments/taxonomy.yaml` — vocabulary of categories + per-suite tags + per-capsule explicit overrides. Capsules inherit categories from the suite their config named. New `GET /v1/catalog/categories`. `GET /v1/catalog/suites` now supports `?category=` and defaults to omitting SQL content (add `?include_sql=true` if needed). New agent tool `list_categories`; existing `list_suites` gains `category` and `include_sql` params.

**Fork closed.** Every experiment starting with an 88-KB `list_suites` dump. The first live-fire against the new capabilities (2026-07-04, capsule `803f3c94`) burned ~88 KB on turn 1 for content the agent didn't need — the SQL of every suite the agent won't touch.

**Fork opened.** Capsule tagging is now first-class. `taxonomy.yaml` has a `capsules:` section for explicit overrides on top of suite inheritance — the substrate for "list capsules in category X" (endpoint deferred one iteration).

**Why.** Ramona: *"need to do a better job helping the agent decide on an experiment. each time listing all suites is very inefficient and costly. we need the proper registry with categories. need a taxonomy for categories and each capsule be listed in a category (or more)."*

**How it lands.** `list_categories` returns ~600 B (12 category names + descriptions + counts). `list_suites(category=scaling)` returns ~200 B per matching suite (no SQL). Expected turn-1 payload: from 88 KB down to ~2 KB. If the agent needs the actual SQL for a specific suite, `list_suites(category=X, include_sql=true)` gives it back.

**Cross-refs.** First live-fire run: capsule `803f3c94` trace (`sql_benchmarks/experiments/agent_runs/20260704T212724Z_4610810d.jsonl`). Skill updated: `skills/build_scaling_experiment.md`.

---

## 2026-07-04 — Multi-agent architecture: explicit state machine + specialist sub-agents

**Decision.** Ship a second driver — `scripts/multi_agent.py` — alongside `scripts/autonomous_agent.py`. State machine is `config_builder → poll → analyzer`, each stage a scoped specialist. Poller is deterministic Python (no LLM); config_builder and analyzer are LLM specialists with small tool inventories (5 and 7 tools respectively) and focused system prompts.

**Fork closed.** Single monolithic agent driving the whole lab loop. That version sees all 13 tools + full skills + full AGENTS.md on every turn.

**Fork opened.** Each specialist is now its own measurable object. *"How does config-building capability scale with model size"* is a distinct question from *"how does analysis capability scale"* — currently they collapsed into one "did the agent finish" measurement. JSONL trace tree per orchestrator run: one orchestrator trace + N specialist traces linked by `delegate` events.

**Why.** Ramona: *"agent state machine and subagents are tightly coupled."* They are — each sub-agent IS a state; hand-off between them IS the state transition. Also directly follows from the `scratch/reducing_agent_search_scope.md` methodology: progressive disclosure applied to the agent's structure, not just to the tool interface.

**Implementation.** Kept the monolithic `autonomous_agent.py` for A/B comparison. Tool inventory extracted to shared `sql_benchmarks/agent_tools.py` (single source of truth; both drivers import from it). `agent_specialist.py` has one reusable `Specialist` loop parameterized by role. `agent_orchestrator.py` threads specialists through the state machine. 17 tests, model calls mocked.

**Deliberate scoping.** Poller is pure Python because polling is a fixed-outcome procedure and burning LLM tokens on it strips signal from the capability measurement (every call would look identical). If we later want to measure *"does model X know when to stop polling"*, that's a separate `llm_poller` specialist, not shipped here.

**Cross-refs.** `scratch/reducing_agent_search_scope.md` (methodology). SBD-2 (workflow-capability failure the multi-agent architecture plausibly closes). Live-fire A/B pending.

---

## 2026-07-05 — Harness hardening from llama3 live-fire failures: gates over exhortation

**Decision.** Three mechanical defenses in the specialist loop, all derived from per-turn trace autopsy of two llama3 (8B) multi-agent runs:

1. **Raw-text tool-call recovery** — small models emit the call as JSON *text* (`{"function_name": ...}`) instead of a native tool call. Recovery now handles the `function_name`/`tool`/`tool_name` key variants the monolith's recovery missed, checks against the specialist's *scoped* tool set, and coaches on hallucinated names.
2. **Repeated-failing-call breaker** — identical (tool, args) failing twice triggers an escalating STOP coaching message naming the legal tools. llama3 had repeated one hallucinated call 9× with zero self-correction.
3. **Tool preconditions (`SpecialistRole.tool_preconditions`)** — mechanical workflow gate: `submit_experiment` refuses to dispatch until `get_template` has succeeded this run. llama3 invented a config schema from priors and 422'd four times without ever fetching a template, despite the prompt explicitly saying "adapt a template".

**Fork closed.** Strengthening the *prompts* further. The trace evidence says prompt exhortation does not bind on weak models — the same lesson as SBD-3 (`--admin` bypass: a CLAUDE.md rule didn't stop it; branch protection did) and the META-FINDING in the incident catalog (correction + self-memory don't bind; only mechanical verification catches it). The harness now applies the lab's own doctrine to its agents: gates, not requests.

**Fork opened.** `tool_preconditions` is a general workflow-DAG primitive — any specialist can declare "tool X requires prior success of tool Y". The failure classes it produces (`gate-refused` events in the trace) are themselves measurable.

**Also fixed.** Analyzer handoff now includes the config's `definitions` block (fetched server-side, zero LLM tokens) — Run 4's analyzer had to hedge its scaling claims because it didn't know what the partition labels meant in rows.

**Empirical status.** llama3 still fails config-building even with coaching (capability wall is real: it never reaches for `get_template` unprompted, and gates can redirect but not create competence). The *localization* is the result: monolith said "gave up, opaque"; multi-agent traces say "fails at the adapt-a-template step with invented schema". Failure classes per stage are exactly the instrument working. Local-model sweeps paused by Ramona's call — hardening pays off regardless of model tier.

**Cross-refs.** Traces `20260705T234509Z_*` and `20260705T234955Z_*` (local). SBD-3 (gates-over-exhortation precedent). `[[agent-integrity-incidents]]` META-FINDING.

---

## 2026-07-06 — Studies get contracts: meta-experiments follow the same YAML discipline as experiments

**Decision.** Agent studies (matrices of runs: cells × replications) are defined by verbatim YAML contracts under `sql_benchmarks/experiments/studies/`, content-addressed (`study_id = sha256(bytes)[:8]`), executed by `scripts/run_study.py`. Each run's trace carries `study_id/cell/rep` in its provenance — trace → contract is always resolvable.

**Fork closed.** Ad-hoc shell scripts driving study matrices. The first execution of the attribution 2×2 (PR #139) was driven by a throwaway `/tmp` script with hardcoded conditions — Ramona caught it: *"i thought this run is executed via a contract yaml file."* That was the lab's own founding rule ([[experiment-config-design]]) violated at the meta-level, and structurally close to specimen #9 (study definition living in a script + conversation instead of a durable artifact). The contract `attribution_2x2.yaml` codifies those parameters retroactively, with the historical note stating plainly that run 1 predates the contract.

**Fork opened.** Studies are now first-class, reproducible lab objects: re-run a study by pointing the runner at its YAML; extend the corpus by adding a cell; a future model-capability sweep is one contract file. Fork-B sealing extends naturally: `(study contract, traces, analysis)` is a sealable tuple.

**Cross-refs.** [[experiment-config-design]], PR #139 (the pre-contract execution), `scratch/reducing_agent_search_scope.md`.

---

## 2026-07-06 — Lean experimental baseline: AGENTS.md and skills dropped from new studies

**Decision.** New study contracts stop carrying AGENTS.md and skills cells. Baseline conditions are `anchor` (prose workflow + rich schema) and `floor` (schema only). Multi-agent specialists never had either, by construction.

**Fork closed.** Continuing to burn tokens on conditions the corpus has answered: AGENTS.md = ~50K/run overhead with zero behavioral delta (Finding 2, replicated cross-model in Finding 9); skills = no considerable improvement (Finding 3).

**Fork opened.** If a future model shows floor-level marker degradation (as 2.5-era Gemini did for taxonomy-first), re-introduce guidance cells FOR THAT MODEL to measure what it needs — guidance as a per-model prescription, not a default.

**Side note (Ramona).** The shared goal's "no Docker" clause is redundant — DuckDB is in-process. Kept verbatim anyway in running studies: the goal string is part of the cross-study anchor (same goal-hash across all 9+ studies); changing it breaks comparability. New-goal studies should drop it.

**Cross-refs.** Findings 2, 3, 9 in `scratch/reducing_agent_search_scope.md`. TODO #11 (agent_runs reorg, deferred).

---

## 2026-07-06 — Harness engineering tenets: mapping + the own-repo question

**Context.** Ramona surveyed the emerging harness-engineering literature; the core tenets converge with what the lab built independently. Mapping (her table → lab implementation):

| Tenet | Lab status |
|---|---|
| Sentinel-driven state machines | PARTIAL — orchestrator stages + `tool_preconditions` gates (PR #137); "passing" is grader-controlled (PR #145), not agent-claimed. No immutable gate markers yet. |
| Compaction interceptors | MISSING — no context management; runs are short enough so far. Becomes real at longer-horizon tasks. |
| Capability gating / restricted tool subsets | IMPLEMENTED — specialist tool subsets (PR #135), strict-subset tests. |
| Fail-closed safety layers | PARTIAL — repo level: pre-push + branch protection (PR #129); agent level: precondition gates. No OS-level sandboxing (agents only reach the lab through the REST API, which bounds the blast radius, but the monolith/specialist processes themselves are unsandboxed). |
| Deterministic mocking | IMPLEMENTED — 24+ state-transition tests with mocked model outputs. |

**Decision (own repo?).** The harness (`agent_tools/specialist/orchestrator/trace`, `run_study`, analyzer, grader) stays IN this repo until a second consumer exists. Extraction trigger: ai-security-testbed importing it, or the article requiring a citable standalone artifact. Extracting now would freeze the API exactly while the edge-case studies are telling us which states/tools are missing (e.g., the refusal state that edge-3 is expected to surface).

**Cross-refs.** Edge-case contracts `edge1_novel_goal`, `edge3_adversarial_goal`, `edge4_ambiguous_goal`; run_study schema v2 (`models:` list — weak→strong ladder in one contract).

---

## 2026-07-06 — SUSPENDED state + resume: the capsule is the durable hand-off

**Decision.** Poll timeout while the experiment is still executing is now `suspended`, not `poll_failed` — a first-class non-error outcome carrying the experiment_id. `Orchestrator.resume(exp_id)` (CLI: `multi_agent.py --resume <id>`) picks up at the analyzer once the capsule completes, for a few thousand tokens. Also this session: structured REFUSAL state (`HANDOFF: impossible reason=…`), contract-declared `poll_budget_seconds`, and liveness-aware running markers (TODO #12 — self-healing on dead PID / over-age / corrupt).

**Fork closed.** Tuning poll budgets per suite. Edge-4's rerun proved no budget is "right": fable-5 correctly chose a 16GB out-of-memory sort that outlived even a 30-minute budget *while executing legitimately*. Synchronous waiting conflates "slow" with "dead".

**Fork opened.** Long-running experiments become first-class: submit → suspend → resume across sessions or crashes. The capsule (content-addressed, server-side, durable) is the hand-off point — the same object that already anchors reproducibility now anchors continuity. Pairs with the liveness-aware markers: "dead" is now detected by evidence (PID, age), never inferred from silence.

**Live validation of the recovery story (same day).** A session teardown killed the runner mid-poll and the API mid-execution. Traces survived (append-per-event JSONL); the stale running marker was the only manual surgery — and that class is now self-healing.

**Cross-refs.** TODO #12, edge-3/edge-4 studies, Finding 18/19, `[[work-before-the-work]]` (states uncovered by pre-deployment probing — exactly the deliverable of the role Ramona is naming).
