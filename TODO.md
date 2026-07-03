# TODO — Known Architectural Gaps

Findings from working sessions that need addressing, but were out of scope of the immediate work. Not a bug tracker — those are separate issues. This is a running log of architectural questions and layered-validation gaps surfaced while iterating on the autonomous agent (`scripts/autonomous_agent.py`) and the REST API.

Date opened: 2026-07-03.

---

## 1. Two-layer validation with different rigor

The submission-time API contract (`api_submission`) accepts YAML that the deeper executor (`execute_run.py` → `ConfigLoader`) rejects. Observed live:

- Agent submitted a YAML missing `execution.matrix`.
- `POST /v1/experiments` → `202 Accepted`, experiment_id `2a75665c` assigned.
- Executor immediately crashed with `ValueError: CRITICAL: Experiment must define a 'matrix' strictly under 'execution.matrix'.`

The whole point of validating at submission is to catch problems *before* they get an experiment_id. Right now the two layers don't agree on what "valid" means.

**Rough shape of fix:** the submission contract should validate against the same schema `ConfigLoader` uses, not a laxer superset. If ConfigLoader has hard requirements (matrix, non-empty engines, dataset shape), submission-time should enforce them too.

## 2. Failed executions do not surface to status

`execute_run.py` crashed and printed `[FAILURE] Technical execution failed.` But `GET /v1/experiments/<id>/status` kept returning `queued` — never `failed`. The agent had no way to know the run had already died; it polled 12+ times against a dead experiment.

**Rough shape of fix:** on execute_run.py failure, write a failure marker (`results/<id>/failure.json` with the exception text and traceback) that the status endpoint reads. `{"status": "failed", "detail": "<error text>"}` returned to the agent lets the coaching-on-tool-error logic in `autonomous_agent.py` (PR #106) actually kick in — the agent retries with a fixed YAML.

## 3. Status endpoint is non-idempotent — every poll retriggers execute_run.py

Log evidence: same `ConfigLoader` crash appearing twice, from two consecutive `GET /v1/experiments/<id>/status` calls. That means the status endpoint isn't just reading state from disk — it's spinning up a full Dagster load on every check. Wasteful (heavy import per poll) and non-idempotent (side effects on read).

**Rough shape of fix:** status endpoint reads from disk-based state (queue file, results dir, failure marker), never invokes the executor. Execution is a *separate* concern — a background worker or an explicit `POST /v1/experiments/<id>/execute` call, not a side effect of GET.

## 4. Agent workflow vs. human workflow — surface the same thing

Ramona's observation from a working session: the workflow when a human runs an experiment (`./run.sh <yaml> --auto`) and when an agent runs one (`POST /v1/experiments`) should be as close as possible. Right now they're separate code paths with different validation and different failure semantics.

Each tool call should return something validated with the same rigor as the CLI would produce. This isn't a single bug; it's a design principle worth carrying into #1, #2, #3 above.

## 5. Capsule ID collision — what's the fallback?

Content-addressed IDs are 8 hex chars of SHA-256 = 32 bits of collision space. Birthday-bound collision expected around ~65k capsules; possible much sooner in adversarial or accident cases.

### 5a. Detection — SHIPPED 2026-07-03 in `sql_benchmarks/capsule_registry.py`

The correctness half of the problem is closed. `check_registry(exp_id, config, archive_dir)` returns one of:
- `"fresh"` — no archived config with this exp_id; proceed normally.
- `"duplicate"` — archived config parses to the same dict (minus `meta`) as the submitted one; this is a legitimate re-submission.
- `"collision"` — archived config parses to a DIFFERENT dict; genuine 32-bit hash collision; refuse loudly.

Comparison rule: deep equality on the parsed YAML trees, with `meta` stripped from both sides (because the hasher at `utils/hasher.py:51` excludes `meta` from the hash input — otherwise a re-submit with a renamed experiment would falsely trip). Robust to whitespace, comments, key-reordering; sensitive to real content differences.

Wired at both surfaces (the workflow-parity discipline from #4):
- API: `POST /v1/experiments` → `409 Conflict` with a diagnostic message on collision.
- CLI: `coordinator.run()` prints `[CRITICAL]` and returns False on collision.

An unparseable archived config is classified as `"collision"` — we never silently overwrite what we can't verify.

### 5b. ID widening — DEFERRED, options preserved for when it becomes real

Not shipped, not needed today. Recording the options so the decision has valid context when the pressure arrives. Trigger: capsule count within ~10× of the 65k birthday bound, OR the first organic collision observed via 5a.

- **B1. Stay at 8 chars, rely on 5a.** Current state. Correct until collision density grows. Zero migration cost. Recommended default.
- **B2. Extend to 12 chars only on collision.** Creates dual-format IDs (8 vs 12), mixed display, docs and release manifests must handle both. Migration pain scales with existing capsule count. **Not recommended.**
- **B3. Extend to 16 chars everywhere.** Cleanest going forward, but invalidates every existing 8-char reference: published capsule tables in `docs/published_capsules.md`, the `sqlbenchdag-quack-v1` release manifest, ORCID/CITATION.cff references, external citations already in the wild. Breaks the maker's mark discipline. **Not recommended.**
- **B4. Full 64-char SHA-256 always; 8-char is a display prefix.** Registry keyed on full hash. Longest reach and the only option that preserves existing 8-char references (as display shortcuts). Requires filesystem migration for existing capsules (`configs/config_<8>.yaml → configs/config_<64>.yaml` + a lookup index). **The right answer if we ever need one.**

If B becomes real: prefer B4. Design the migration script alongside the code change; keep 8-char display everywhere the maker's mark appears.

## 6. AGENTS.md loading is opt-in for standalone scripts

Standalone Python scripts (`scripts/autonomous_agent.py`) don't automatically read AGENTS.md the way harnesses like Claude Code or Cursor do — that's harness-level behavior. PR #107 added explicit `load_agents_md()` to the agent script; any *future* agents that talk to the sqlbenchdag API need the same pattern (or need a shared library that does it). Worth extracting to `sql_benchmarks.agent_utils` if a second agent shows up.

---

## Related (already fixed)

- **Agent silent-exit on empty/hallucinated tool response** — PR #106.
- **API-key handling + AGENTS.md loading in autonomous_agent.py** — PR #107.
- **Autonomous agent goal hardcodes the suite name** — the default `--goal` in `__main__` tells the agent to use `analytical_wall` instead of asking it to reason from `list_suites`. Not a bug (`--goal` is overridable), but the default should be intent-level, not suite-level.
