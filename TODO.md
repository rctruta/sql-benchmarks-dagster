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

### 5c. Set-like list canonicalization — SHIPPED (this PR)

Two configs that differ only in the order of a set-like list (`execution.engines: [duckdb, postgres]` vs `[postgres, duckdb]`; `execution.matrix.rows: [medium, large]` vs `[large, medium]`) now hash to the same exp_id and produce the same partition_keys. Author is no longer responsible for remembering to sort these lists.

**Mechanism:** `sql_benchmarks/canonicalization.py` holds a declarative registry `SET_LIKE_PATHS` of dotted paths that are order-independent. `canonicalize(config)` returns a deep copy with those paths sorted. Called from three places:
- `utils/hasher.py::generate_experiment_hash` — the exp_id becomes canonical.
- `config_loader.py::ConfigLoader._load_and_validate` — partition_keys generation sees canonical order.
- `coordinator.py::run` — the `active.yaml` written before execution is the canonical form (author's raw bytes are still preserved via `_source_yaml` → `_archive_source_config`, so the sealed capsule retains provenance).

Extension rule: add a new dotted path to `SET_LIKE_PATHS` when adding a schema field that is genuinely set-like. `*` matches any dict key at that level. The safer default is NOT to declare a field set-like — sequence-ness is the correct assumption when in doubt.

Currently registered:
- `execution.engines` — the set of engines to test.
- `execution.matrix.*` — the values for each matrix dimension.

Explicitly NOT registered (order matters):
- `dataset.tables.<t>.columns` — DDL column order.
- `dataset.tables.<t>.indexes[N].columns` — composite index prefix.
- `choice` provider `options` — pairs positionally with `weights` for reproducible RNG.

Engine params (`execution.engine_params.<engine>.<param>`) are DICTS, not lists — already order-invariant via `json.dumps(sort_keys=True)`. Runtime iteration order in the drivers follows Python dict insertion order; harmless for current allowlist (session-level `SET` statements are commutative for the params we allow). If a future engine param needs deterministic SET order, that's a driver concern, not a hashing concern.

## 6. AGENTS.md loading is opt-in for standalone scripts

Standalone Python scripts (`scripts/autonomous_agent.py`) don't automatically read AGENTS.md the way harnesses like Claude Code or Cursor do — that's harness-level behavior. PR #107 added explicit `load_agents_md()` to the agent script; any *future* agents that talk to the sqlbenchdag API need the same pattern (or need a shared library that does it). Worth extracting to `sql_benchmarks.agent_utils` if a second agent shows up.

---

## Related (already fixed)

- **Agent silent-exit on empty/hallucinated tool response** — PR #106.
- **API-key handling + AGENTS.md loading in autonomous_agent.py** — PR #107.
- **Autonomous agent goal hardcodes the suite name** — the default `--goal` in `__main__` tells the agent to use `analytical_wall` instead of asking it to reason from `list_suites`. Not a bug (`--goal` is overridable), but the default should be intent-level, not suite-level.
