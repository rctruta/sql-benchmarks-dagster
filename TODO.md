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

**Verified closed 2026-07-03 by audit.** #4 was the design principle behind #1-#3; those PRs realized it. Concrete parity between the CLI path (`./run.sh <yaml> --auto` → `run_experiment.py` → `coordinator.run()`) and the API path (`POST /v1/experiments` → `_run_experiment` → `coordinator.run()`) after #109-#112:

| Concern | State |
|---|---|
| Validation contract | Same after #110 (both call `validate_experiment_config`) |
| Config hashing | Same code path (`generate_experiment_hash`) |
| Runtime staging file | Same after #109 (both gitignored, no shared-state coupling) |
| Failure surfacing | Same after #111 (both write `results/<id>/failure.json`; the API reads it) |
| Startup cost | Same after #112 (both lazy on the ConfigLoader) |
| Registry check for duplicates | API upfront (202 + `status="duplicate"`); CLI at `coordinator.run:53` (prints "SKIPPING"). Same effect, different response surface. |
| Caller feedback shape | API async (submit → poll `/status`); CLI sync (exit code). Inherent architectural difference, not a parity gap. |

The design principle is realized. No remaining concrete gap.

## 5. Capsule ID collision — what's the fallback?

Content-addressed IDs are 8 hex chars of SHA-256 = 32 bits of collision space. Birthday-bound collision expected around ~65k capsules; possible much sooner in adversarial or accident cases. Currently:

- Question: what happens if two experiments hash to the same 8-char ID? Overwrite? Reject? Extend to 12 chars on collision?
- Question: how would we distinguish a genuine collision (two different configs → same ID) from a re-run of an existing capsule (same config → same ID; expected)?

**Note (from Ramona):** *"i know this was not been addressed. not for now, it's more thinking required here."* Deliberately deferred; recording so it doesn't get lost.

## 6. AGENTS.md loading is opt-in for standalone scripts

**Closed 2026-07-03 as YAGNI (extract when justified, not before).** Standalone Python scripts (`scripts/autonomous_agent.py`) don't automatically read AGENTS.md the way harnesses like Claude Code or Cursor do — that's harness-level behavior. PR #107 added an explicit `load_agents_md()` (~40 lines) to the agent script.

Decision: not extracting `sql_benchmarks.agent_utils` speculatively. The extraction cost (module boundary, tests, docs) exceeds the current benefit (one caller). When a second agent script appears that needs the same loader — or when the loader grows beyond what fits in a single script — extract then. The one-caller shape is not a smell; the extract-for-hypothetical-reuse is. See also: [experiment config design memory](/Users/ramona/.claude/projects/-Users-ramona-Projects-sql-benchmarks-dagster/memory/experiment-config-design.md) — same principle (no templating until a real second consumer appears).

---

## Related (already fixed)

- **Agent silent-exit on empty/hallucinated tool response** — PR #106.
- **API-key handling + AGENTS.md loading in autonomous_agent.py** — PR #107.
- **Autonomous agent goal hardcodes the suite name** — the default `--goal` in `__main__` tells the agent to use `analytical_wall` instead of asking it to reason from `list_suites`. Not a bug (`--goal` is overridable), but the default should be intent-level, not suite-level.
