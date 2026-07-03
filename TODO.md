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

**Verified stale 2026-07-03 by direct measurement.** Instrumented `subprocess.run` and `ConfigLoader.__init__` counters against the current handler; three `GET /v1/experiments/<id>/status` calls produced zero of each. The endpoint is pure filesystem reads (fragments, CSV, config archive, and the new failure marker from #2).

The one visible ConfigLoader instantiation at API startup was traced to `sql_benchmarks/utils/common.py:19` — an eager `_GLOBAL_COMPILER = ConfigLoader()` at module import time, pulled in via `api/routers/experiments.py → coordinator → utils.hasher → utils.common`. That was import-time cost, not per-poll cost, but it was worth closing: the API had no business parsing `active.yaml` just to boot. Made lazy in the same PR (`_get_global_compiler()` initializes on first `load_context()` call). Dagster's `CTX = load_context()` in `assets/*_factory.py` still fires eagerly at asset-definition time — same fail-hard behavior, just at first use instead of at module import.

The original TODO #3 evidence was likely a background-task crash from `_run_experiment` running once (submission time), not a per-poll retrigger. TODO #2's failure marker now surfaces those to `/status` cleanly.

## 4. Agent workflow vs. human workflow — surface the same thing

Ramona's observation from a working session: the workflow when a human runs an experiment (`./run.sh <yaml> --auto`) and when an agent runs one (`POST /v1/experiments`) should be as close as possible. Right now they're separate code paths with different validation and different failure semantics.

Each tool call should return something validated with the same rigor as the CLI would produce. This isn't a single bug; it's a design principle worth carrying into #1, #2, #3 above.

## 5. Capsule ID collision — what's the fallback?

Content-addressed IDs are 8 hex chars of SHA-256 = 32 bits of collision space. Birthday-bound collision expected around ~65k capsules; possible much sooner in adversarial or accident cases. Currently:

- Question: what happens if two experiments hash to the same 8-char ID? Overwrite? Reject? Extend to 12 chars on collision?
- Question: how would we distinguish a genuine collision (two different configs → same ID) from a re-run of an existing capsule (same config → same ID; expected)?

**Note (from Ramona):** *"i know this was not been addressed. not for now, it's more thinking required here."* Deliberately deferred; recording so it doesn't get lost.

## 6. AGENTS.md loading is opt-in for standalone scripts

Standalone Python scripts (`scripts/autonomous_agent.py`) don't automatically read AGENTS.md the way harnesses like Claude Code or Cursor do — that's harness-level behavior. PR #107 added explicit `load_agents_md()` to the agent script; any *future* agents that talk to the sqlbenchdag API need the same pattern (or need a shared library that does it). Worth extracting to `sql_benchmarks.agent_utils` if a second agent shows up.

---

## Related (already fixed)

- **Agent silent-exit on empty/hallucinated tool response** — PR #106.
- **API-key handling + AGENTS.md loading in autonomous_agent.py** — PR #107.
- **Autonomous agent goal hardcodes the suite name** — the default `--goal` in `__main__` tells the agent to use `analytical_wall` instead of asking it to reason from `list_suites`. Not a bug (`--goal` is overridable), but the default should be intent-level, not suite-level.
