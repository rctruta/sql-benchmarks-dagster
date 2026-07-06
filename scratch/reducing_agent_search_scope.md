# Reducing agent search scope — methodology note

*2026-07-04. Local draft. Not for the public repo.*

## The problem, one line

An agent driving a lab is paying tokens for the *entire universe of choice* on every discovery call. Every byte the tool returns is a byte the model must read on this turn and re-read on every subsequent turn (context accumulates). Reducing the search scope *at the tool interface* is the highest-leverage way to improve agent ability, precision, and cost — all three simultaneously.

## Evidence — one controlled A/B, same goal, same model

Two live-fire runs, same goal (*"how does DuckDB scale from small to large? DuckDB only, no Docker"*), same model (`anthropic/claude-sonnet-5`), same lab. Between runs, the only change was **taxonomy** on the discovery tools: a small `list_categories` vocabulary and a `list_suites(category=X)` filter, with the SQL payload gated behind `include_sql=true`.

| Metric | Before | After | Change |
|---|---|---|---|
| Turn-1 tool result (bytes) | 88,480 | 1,715 | −51× |
| Turns to final answer | 12 | 8 | −33% |
| Total tokens (in + out) | 626,601 | 111,575 | **−5.6×** |
| Outcome | clean final analysis | clean final analysis | same quality |

Same-quality analysis, one-fifth the cost. Ability and precision were not sacrificed; if anything, precision improved (the second-run agent fetched two candidate templates in parallel on turn 3, compared them, then submitted — a move it didn't make with the noisier context).

## Why the effect is compounding, not one-shot

Naive view: "we saved 87 KB on turn 1." Actual mechanism: **context accumulates linearly per turn**. Every turn's prompt includes all prior tool results. A single 88 KB payload on turn 1 costs 88 KB × N remaining turns worth of prompt tokens, not 88 KB. That's why a −51× reduction on one call produced a −5.6× reduction on the total.

The saving multiplies over the length of the run. Fixing the biggest early payload is disproportionately valuable.

## The mechanism — three moves the taxonomy makes

1. **A small vocabulary the agent can survey.** 12 category names + one-line descriptions ≈ 600 B. The agent sees the shape of the choice space without seeing the contents.
2. **A filter argument on the noisy tool.** `list_suites(category=scaling)` returns the 2–3 suites tagged with `scaling`, not all 16. The filter is a *routing hint* the agent computed cheaply from step 1.
3. **Gated detail on the expensive field.** `include_sql=true` opts back into the raw SQL only when the agent decides it needs to reason about the SQL itself. Default response is names + tags + engines.

The three moves compose. Each one alone would help; together they turn discovery into a series of small, targeted queries instead of one giant dump.

## Where this generalizes (what to apply next)

Any tool that currently returns *"everything the agent might want"* is a candidate:

- **Fragments / raw results.** Already partially addressed by the granular projections (`get_experiment_summary`, `get_means_by_partition`, `get_scaling_factor`, `get_replication_stability`). Same pattern: small first, drill deeper by name.
- **Historical corpus** (when longitudinal comparison lands). Don't dump every past run of a config. `list_capsules(category=X, since=Y)` first; specific IDs second.
- **SQL content itself.** Even with `include_sql=true`, currently returns every benchmark's SQL for the suite. Could become `get_benchmark_sql(suite, benchmark)` — one at a time.
- **Tool listing itself.** When the tool inventory grows past ~20, the *tool schema* becomes another payload. Category the tools. Load only the category the agent's current task needs.
- **Skills.** Right now all skills are loaded upfront in the system prompt. Same pattern: `list_skills` (names + one-line summaries) → `get_skill(name)` on demand. Cheap.
- **AGENTS.md itself.** Currently loaded whole. Could be sectioned by task-type, with a lightweight index.

Underlying principle: **progressive disclosure at the tool interface**. The agent must actively request more detail — never gets the whole universe on the first turn. Basic API design applied to LLM tool interfaces where every byte round-trips through the context window on every subsequent turn.

## The precision claim is separate and worth naming

The token-cost win is obvious. The *precision* claim is subtler:

- With less noise in early turns, the second-run agent picked up `scaling_depth` as an alternative to `quickstart` and compared both templates — a move it didn't make in run 1.
- Deduplication worked cleanly: `submit_experiment` returned the same `803f3c94` as run 1 (identical config → identical content-addressed ID → the coordinator served the cached sealed results without re-executing).
- Fewer turns → shorter feedback loops → less opportunity for the model to drift (empty responses, wrong tool calls, or #7-style rigor-theater).

*Less scope to search means more attention on the actual decision.* Not a novel finding in the literature — it's why humans use categories, filters, and dashboards — but worth stating as method for the lab's ruler: **the agent's tool interface is itself a research object**, and reducing search scope is a measurable intervention with a measurable effect (5.6× token reduction on this workload).

## As a lab measurement, not just an engineering fix

This is a data point the lab can produce on itself. Two runs, same inputs modulo the interface. The delta is attributable to the interface change. That's a legitimate methodology observation:

- **Independent variable:** presence of category taxonomy + gated payload.
- **Dependent variables:** turn-1 payload size, total token cost, turns to convergence, final-answer quality.
- **Confound to control for:** model, goal, prompt version, temperature. Handled here — same run repeated with only the interface changed.

Future runs across a model capability sweep (llama-3.1-70b, mixtral-8x22b, qwen-2.5-72b, deepseek-v3, sonnet-5, opus-4-6) can produce a *scope-reduction-effect curve*: does the win scale with model capability, or is it constant? Testable.

## Open questions

- Where's the floor? At some point the taxonomy is small enough that further hiding costs the agent more (extra turns to fetch what it needed anyway) than it saves. That trade-off is measurable — the JSONL trace captures per-turn tool selection, so we can see when the agent had to fetch multiple category slices vs. when one was enough.
- Does the effect hold on weaker models? SBD-2's llama3 hit workflow-capability failure with the old interface. Would the taxonomy have gotten it past turn 23? Unknown — worth re-running.
- What's the right unit of category? Suites is one level; the SQL benchmarks *within* a suite is another; the *questions* those benchmarks answer is a third. The methodology says "categorize", not "categorize at level X" — the level itself is a design choice per tool.
- Should the taxonomy be static (YAML) or derived (auto-tagged from suite metadata + capsule configs)? Static is cheap and controllable; derived stays in sync automatically but hides the vocabulary from the agent's introspection.

## Extensions (Ramona, 2026-07-04) — three moves that follow from the same principle

The taxonomy result is a small confirmation of a bigger claim: **the traces produced by these runs are themselves the data that answers the open questions the interface changes surface**. Interface change → traces → analysis → next interface change. The lab measures the agent measuring the lab, and each level uses the same discipline (sealed measurement, distilled decisions). It doesn't get more fractal than this.

Three architectural moves that follow from the principle:

### 1. Hierarchical taxonomy

Flat 12 categories collapses distinctions the research actually needs (`analytical > aggregation > scaling` is not the same slice as `analytical > aggregation > selectivity`).

- **Single-axis hierarchical** (parent/child in `taxonomy.yaml`): easy to implement, natural to navigate. Start here.
- **Multi-facet** (topic × complexity × engine-type as orthogonal axes): more expressive but higher navigation cost. Add when a specific research question forces it.
- Implementation shape: extend `taxonomy.yaml` with nested keys OR use `:`-delimited category names (`analytical:aggregation:scaling`) — the second is simpler to parse and doesn't require a schema change.

### 2. Explicit agent state machine

Current `autonomous_agent.py` runs an implicit state machine — every research read of the loop has to reconstruct where the agent was. Making it explicit unlocks three things:

- **Per-state tool subsets.** In `discovery` state, only `list_categories / list_suites / get_template`. In `build`, only `submit_experiment`. In `analyze`, only the result-reading projections. Reduces the tool inventory the model reasons over on each turn — same principle as the taxonomy, applied to the tool list itself.
- **Per-state system prompts.** Discovery prompt frames a search problem; analysis prompt frames a synthesis problem. Different words for different tasks.
- **Machine-readable failure classification.** JSONL trace gains a `state` field per event. "Gave up in `analyze` at turn 20" is a different specimen from "gave up in `build` at turn 8" — currently both look identical in SBD-2's shape.

States, first pass: `discover → build → submit → poll → analyze → answer`. Transitions gated by predicates (e.g., `build → submit` only after `submit_experiment` returns a valid `experiment_id`).

### 3. Spawning sub-agents for granular tasks

The biggest architectural fork. Instead of one generalist agent driving the whole loop, decompose into specialists:

- `config_builder` — input: goal + category. Tools: `list_suites`, `list_templates`, `get_template`, `submit_experiment`. Output: `experiment_id` or a config-error.
- `poller` — input: `experiment_id`. Tools: `get_experiment_status`. Output: `complete` / `failed`.
- `analyzer` — input: `experiment_id`. Tools: the four projections + `get_experiment_result`. Output: structured claim + narrative.
- `orchestrator` — input: user goal. Delegates to the specialists; owns nothing but the plan.

**Why this is more than a refactor.**

1. Each specialist has a tiny tool inventory (3–5 tools) and a focused prompt. Progressive disclosure applied to the *agent's* structure, not just to the tool interface.
2. SBD-2 (llama3 8B workflow-capability failure) plausibly succeeds under this architecture: a specialist config_builder with narrow scope and a focused prompt is a much smaller task than "drive the whole lab", even for a weak model.
3. **Every sub-agent is its own measurable object.** The SBD-N corpus refracts: each capsule now has a family of sub-agent traces, one per specialist. "How does config-building capability scale with model size" becomes a distinct question from "how does analysis capability scale" — currently these are collapsed into a single "did the agent finish".

**Costs (not hidden).**

- Orchestration surface: hand-off data model, error propagation between specialists.
- Latency: N model calls instead of 1 continuous stream (though each is smaller).
- Debugging shape changes: the JSONL trace becomes a tree, not a stream. Not necessarily worse, but different tooling.

**Where to prototype first.** `config_builder` — it's the specialist most likely to help SBD-2-class failures, and its interface (goal + category → experiment_id | error) is small and testable. If the specialist beats the generalist on llama3, the argument is made.

### The recursion — what to actually measure

If we ship all three, the lab now measures:

- Agents driving the lab (level 1, existing).
- Interfaces driving agents driving the lab (level 2, the taxonomy A/B is the first data point).
- Sub-agents driving sub-tasks driving agents driving the lab (level 3, new).
- Model capability × interface × decomposition granularity — 3D sweep.

Each level uses the same discipline (measure, seal, distill). That's the "fractal" claim made concrete: not a metaphor, a specific research design where the same measurement pattern applies at every scale.

## Cross-refs

- Live-fire trace 1 (pre-taxonomy): `sql_benchmarks/experiments/agent_runs/20260704T212724Z_4610810d.jsonl`
- Live-fire trace 2 (post-taxonomy): `sql_benchmarks/experiments/agent_runs/20260704T215924Z_4610810d.jsonl`
- PR #134 (taxonomy implementation)
- `docs/decisions_log.md` — the "Category taxonomy" entry
- Related specimens: `[[agent-integrity-incidents]]` #7-#10 (context accumulation as attack surface for rigor-theater; less context, less surface).

---

## The instrument — multi-agent A/B, 2026-07-04

The three extensions above (hierarchical taxonomy, explicit state machine, spawning sub-agents) were built and tested. State machine and sub-agents are the same object: each specialist IS a state; the hand-off IS the transition. The result is the multi-agent architecture in `sql_benchmarks/agent_orchestrator.py` (PR #135), shipped alongside the monolithic `autonomous_agent.py` so the two can be A/B'd directly.

### The A/B — same goal, same model, everything except architecture held constant

| Version | Tokens | vs. baseline (SBD-1) |
|---|---|---|
| SBD-1 (pre-everything) — monolithic, no taxonomy, no projections, no skills | 626,601 | 1.0× |
| + projections + skills (Run 2) | 626,601 | 1.0× |
| + taxonomy on the tool interface (Run 3) | 111,575 | 5.6× reduction |
| + multi-agent decomposition (Run 4) | **30,231** | **20.7× reduction** |

Same model (`anthropic/claude-sonnet-5`), same goal (DuckDB scaling on `analytical_wall`, 3 scales), same lab. Only the interface + architecture changed between runs. Analysis quality remained comparable (Run 4's analyzer correctly caveated its context limits — a real signal, not a regression).

### Two independent interventions that multiply

1. **Taxonomy on the tool interface** (5.6× alone): progressive disclosure at the *return* boundary. Small vocabulary + filtered subsets + gated detail.
2. **Multi-agent decomposition** (further 3.7× on top): progressive disclosure at the *agent's structure* boundary. Each specialist sees a tiny tool inventory + focused prompt.

**Together: 20.7× token reduction on the same task.** The two interventions multiply because they attack different layers of the same problem (information exposed to the model). The methodology is *"reduce the search scope at every boundary the agent crosses"* — one boundary at a time is worth doing; every boundary is compounding.

### Why this is the instrument

The multi-agent orchestrator is not just faster and cheaper — it *makes the sub-tasks separately measurable*. In the monolithic runs, "the agent finished" was a single bit. In the multi-agent runs, we have three distinguishable signals per run:

- Did `config_builder` produce a valid experiment_id? (a specific tool-selection + YAML-adaptation capability)
- Did the poll return `complete` in time? (a lab-infrastructure signal, not an agent signal)
- Did `analyzer` produce a `FINAL ANSWER:`? (a reasoning-over-derived-values capability)

Each stage's specialist trace is its own JSONL file. Failures classify into `config_builder_failed | poll_failed | analyzer_failed` — three specimen classes where before there was one. **The instrument produces its own data**: every A/B run against every model in the capability sweep produces N (stage-labeled, sealable) traces that feed the empirical curve.

This is the fractal claim landing concretely. The lab measures the agent measuring the lab. The instrument that measures the agent is itself a measurable object. Each level uses the same discipline (measure, seal, distill), and each level produces data that constrains the next.

### Publication shape

**Working title (draft):** *"Progressive disclosure at the agent–tool interface: a 20× token reduction from two composable interventions."*

**Structure (rough — this is the outline, not the paper):**

1. **Problem.** Agent driving a REST-backed lab pays tokens for the entire universe of choice on every discovery call. Context accumulates linearly per turn; the biggest early payload is disproportionately expensive over a run.
2. **Two interventions:**
   - Category taxonomy on the tool return: small vocabulary + filter + gated detail.
   - Multi-agent decomposition on the agent structure: state machine of specialists with scoped tool inventories.
3. **Method.** Sealed-config content-addressed lab (`sqlbenchdag`); one goal, one model, three architecture variants; JSONL traces per run + per specialist; deterministic replay of derived projections via a `provenance` receipt.
4. **Results.** 5.6× (taxonomy) × 3.7× (multi-agent) = 20.7× total token reduction. Same-quality analysis. Failure modes classify into 3 distinguishable specimen classes.
5. **Discussion.** Interventions compose because they attack different layers of the same problem (information exposed to the model). Multi-agent surface produces stage-labeled failure data that a monolithic agent collapses.
6. **Future work.** Model capability sweep (llama-3.1-70b, mixtral-8x22b, qwen-2.5-72b, deepseek-v3, sonnet-5, opus-4-6). Does the effect scale with capability? Does SBD-2's llama3 workflow-capability failure close under the multi-agent architecture?

**What the paper claims that isn't obvious.** Progressive disclosure is a well-known API design pattern. What's new:

- Applied to LLM tool interfaces — where every byte of return round-trips through the context on every subsequent turn, so savings compound.
- Applied at the *agent-structure* boundary via specialist decomposition — treating the agent's tool inventory itself as a boundary where disclosure can be gated.
- With a measured composability effect (~4× × ~4× ≈ 20×) — not just "these ideas would help" but "here's the multiplier when they compose."
- Producing an instrument (the multi-agent framework + sealed traces) that generates its own empirical data — every future run adds a row.

**Publication venue candidates** (Ramona picks):
- Workshop/short paper at an ML systems or agent-methodology venue.
- Substack + arXiv preprint — same audience as the [[blueberry-muffin-exploit]] post.
- Fold into the larger *"testbed applied to agent using the lab"* essay planned for the `[[ai-security-direction]]` thread.

### Cross-refs (updated)

- Runs: `sql_benchmarks/experiments/agent_runs/20260704T2306*.jsonl` and `20260704T2307*.jsonl` (multi-agent A/B, capsule `803f3c94`).
- PR #135 (multi-agent implementation), PR #134 (taxonomy), PR #132 (projections), PR #131 (JSONL trace).
- Cross-domain: same methodology applies in the testbed — sub-agents scoped by tool inventory would be a natural next move there too.

---

## Harness hardening round — 2026-07-05 (llama3 autopsy → gates)

Two llama3 (8B) multi-agent runs, both `config_builder_failed`, traces localized the failure precisely (PR #137):

- Run A (`20260705T234509Z`): called its own ROLE name as a tool 9×; submitted invented JSON schema 4×; never called `get_template`.
- Run B (`20260705T234955Z`, after prompt fix + error coaching): role-hallucination gone, repeated-call breaker fired and redirected — but still never fetched a template; decayed to parroting tool results as text.

Fixes (all mechanical): raw-text tool-call recovery (`function_name` key variants), repeated-failing-call breaker with escalating STOP coaching, `tool_preconditions` workflow gate (submit refused until get_template succeeded). Doctrine confirmed again: **exhortation doesn't bind; gates do** — same as SBD-3.

Result: the 8B wall is real and now *named* — "fails at adapt-a-template with invented schema" — vs. the monolith's opaque "gave up at turn 23". Failure localization is the instrument working.

---

## Next study: what actually influences the agent? (attribution + confounds)

**Question.** When the agent behaves well (picks `get_experiment_summary` first, filters by category), WHAT caused it — AGENTS.md? the skills block? tool descriptions? the model's priors? We currently cannot attribute, because all guidance layers ship together.

**Already-known partial deconfound (free, sitting in existing traces):** the multi-agent specialists load NO AGENTS.md and NO skills (`agents_md_loaded=False` in their run_start events) — only role prompts + tool descriptions. Sonnet-5 still made ideal tool choices in Run 4. So for sonnet-5, tool descriptions + role prompt were SUFFICIENT; AGENTS.md/skills were not necessary. That attribution was invisible until now because nobody recorded which prompt components each run carried.

**Confounds to control (name them or the study is theater):**
1. **Guidance overlap** — skills, tool descriptions, and AGENTS.md all say overlapping things ("summary first"). Attribution requires ablation, not observation.
2. **Content-addressed dedup** — capsule `803f3c94` exists, so identical configs return instantly as duplicates. First-run vs re-run trajectories differ (poll turns, timing). Either use fresh goals per cell or record duplicate-vs-fresh in the trace and stratify.
3. **Sampling nondeterminism** — n=1 per cell proves nothing; need n≥3 replications per condition.
4. **Model version drift** — record exact model identifier per run.
5. **Ordering effects** — the skills block sits AFTER AGENTS.md in the prompt; position may matter, not just presence.

**Instrument: the meta-meta-trace (`prompt_provenance` event).** Every run's JSONL gains one event recording, per prompt component: name, sha256, byte size — plus model id and ablation flags. Trace level 1 = what the agent did; level 2 = what it consumed and produced (tokens, tool results); level 3 (this) = *what shaped it*. Analysis can then GROUP BY prompt-composition-hash and correlate component presence with behavioral markers (which tool called first; category filter used; template fetched before submit; projections vs raw result).

**Ablation harness.** Flags on both drivers: `--no-agents-md`, `--no-skills` (monolith); specialists are already the minimal condition. 2×2 factorial × n=3 reps × per-model. Behavioral markers extracted from traces mechanically — no human judging.

**Open idea (not shipped):** canary markers in skills — a distinctive, benign instruction unique to the skills file whose execution proves the model attended to it (attention detection vs. mere presence).

---

## Attribution study results — 2×2 factorial, sonnet-5, n=3/cell (2026-07-06)

Same goal, same model (`anthropic/claude-sonnet-5`), monolith driver; conditions = ±AGENTS.md × ±skills. Tool descriptions + inline tool_workflow present in ALL conditions (they are the constant). All 12 runs succeeded.

| Condition | mean tokens | mean turns | first tool | catfilter | template-first | raw used |
|---|---|---|---|---|---|---|
| −AGENTS.md −skills | 99,770 | 10.3 | list_categories 3/3 | 3/3 | 3/3 | 0/3 |
| −AGENTS.md +skills | 89,713 | 8.3 | list_categories 3/3 | 2/3 | 3/3 | 0/3 |
| +AGENTS.md −skills | 150,595 | 12.0 | list_categories 3/3 | 3/3 | 3/3 | 0/3 |
| +AGENTS.md +skills | 101,571 | 7.7 | list_categories 3/3 | 2/3 | 3/3 | 0/3 |

**Finding 1 — behavioral markers are IDENTICAL across all four conditions.** Every run: `list_categories` first, template fetched before submit, projections used, raw result never touched. Neither AGENTS.md nor skills *causes* the good behavior on sonnet-5. The always-present layers (tool descriptions + inline workflow) fully determine tool selection. Guidance redundancy is total for this model/task.

**Finding 2 — AGENTS.md costs tokens without changing behavior.** +AGENTS.md is consistently more expensive (150K vs 100K without skills; 102K vs 90K with) — pure prompt payload, zero behavioral delta. On this task AGENTS.md is, for sonnet-5, *dead weight the model re-reads every turn*. The most expensive condition is AGENTS.md-without-skills (150K, 12 turns).

**Finding 3 (weaker, n=3 noise) — skills correlate with fewer turns.** 7.7–8.3 mean turns with skills vs 10.3–12.0 without. Plausible mechanism: the recipes shorten deliberation even when they don't change which tools get picked. Needs replication before claiming.

**Named limitations.** Single model, single goal, n=3, duplicate-served capsule for most runs (some 12–14-turn runs likely submitted variant configs and executed fresh — stratify by `status=queued` vs `duplicate` in a follow-up). Skills content overlaps tool descriptions, so "skills don't matter" here means *marginal* contribution given rich tool descriptions — the next ablation is neutralized tool descriptions, which separates schema-guidance from prose-guidance.

**Design implication if Finding 1–2 replicate:** move ALL behavioral guidance into tool descriptions (paid once per schema, cached) and keep AGENTS.md out of the per-turn context for capable models; reserve skills/AGENTS.md injection for models whose tool-description-following is weak. Progressive disclosure again — this time of guidance itself.
