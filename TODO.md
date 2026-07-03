# TODO — Known Architectural Gaps

Running log of architectural questions and layered-validation gaps surfaced while iterating on the autonomous agent (`scripts/autonomous_agent.py`) and the REST API. Not a bug tracker — those are separate issues.

**Status summary (2026-07-03):** the punch list opened this day is resolved. Every item has shipped, been verified stale, been verified closed by audit, or been deliberately deferred with recorded options. Only `#5b` (ID widening) remains as a future decision waiting for a real trigger (capsule count approaching the birthday bound, or an organic collision detected via `#5a`). All other items are done.

Date opened: 2026-07-03. Punch list closed: 2026-07-03.

---

## 1. Two-layer validation with different rigor

**STATUS: SHIPPED via PR #110** — API + coordinator + ConfigLoader all call the same `validate_experiment_config` at `sql_benchmarks/validation.py`; matrix-missing configs now return 422 at submission instead of the previous 202-then-crash.

The submission-time API contract (`api_submission`) accepts YAML that the deeper executor (`execute_run.py` → `ConfigLoader`) rejects. Observed live:

- Agent submitted a YAML missing `execution.matrix`.
- `POST /v1/experiments` → `202 Accepted`, experiment_id `2a75665c` assigned.
- Executor immediately crashed with `ValueError: CRITICAL: Experiment must define a 'matrix' strictly under 'execution.matrix'.`

The whole point of validating at submission is to catch problems *before* they get an experiment_id. Right now the two layers don't agree on what "valid" means.

**Rough shape of fix:** the submission contract should validate against the same schema `ConfigLoader` uses, not a laxer superset. If ConfigLoader has hard requirements (matrix, non-empty engines, dataset shape), submission-time should enforce them too.

## 2. Failed executions do not surface to status

**STATUS: SHIPPED via PR #111** — coordinator writes `results/<id>/failure.json` at every failure point (execution, drift, no_results, catch-all); status endpoint reads it and returns `{"status": "failed", "detail": "[stage] error"}`; belt-and-suspenders catch-all in the API background task.

`execute_run.py` crashed and printed `[FAILURE] Technical execution failed.` But `GET /v1/experiments/<id>/status` kept returning `queued` — never `failed`. The agent had no way to know the run had already died; it polled 12+ times against a dead experiment.

**Rough shape of fix:** on execute_run.py failure, write a failure marker (`results/<id>/failure.json` with the exception text and traceback) that the status endpoint reads. `{"status": "failed", "detail": "<error text>"}` returned to the agent lets the coaching-on-tool-error logic in `autonomous_agent.py` (PR #106) actually kick in — the agent retries with a fixed YAML.

## 3. Status endpoint is non-idempotent — every poll retriggers execute_run.py

**STATUS: CLOSED via PR #112 — verified stale 2026-07-03 by direct measurement.** Instrumented `subprocess.run` and `ConfigLoader.__init__` counters against the current handler; three `GET /v1/experiments/<id>/status` calls produced zero of each. The endpoint is pure filesystem reads (fragments, CSV, config archive, and the new failure marker from #2).

The one visible ConfigLoader instantiation at API startup was traced to `sql_benchmarks/utils/common.py:19` — an eager `_GLOBAL_COMPILER = ConfigLoader()` at module import time, pulled in via `api/routers/experiments.py → coordinator → utils.hasher → utils.common`. That was import-time cost, not per-poll cost, but it was worth closing: the API had no business parsing `active.yaml` just to boot. Made lazy in the same PR (`_get_global_compiler()` initializes on first `load_context()` call). Dagster's `CTX = load_context()` in `assets/*_factory.py` still fires eagerly at asset-definition time — same fail-hard behavior, just at first use instead of at module import.

The original TODO #3 evidence was likely a background-task crash from `_run_experiment` running once (submission time), not a per-poll retrigger. TODO #2's failure marker now surfaces those to `/status` cleanly.

## 4. Agent workflow vs. human workflow — surface the same thing

**STATUS: CLOSED via PR #113 — verified by audit 2026-07-03.** #4 was the design principle behind #1-#3; those PRs realized it. Concrete parity between the CLI path (`./run.sh <yaml> --auto` → `run_experiment.py` → `coordinator.run()`) and the API path (`POST /v1/experiments` → `_run_experiment` → `coordinator.run()`) after #109-#112:

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

### 4a. `active.yaml` was doing three jobs — one file, three roles

**STATUS: SHIPPED via PR #109** — file gitignored + untracked; proper decoupling of runtime staging from tracked file deliberately left as follow-up.

Surfaced 2026-07-03. `sql_benchmarks/experiments/active.yaml` was simultaneously (a) the human's canonical entry file, (b) the coordinator's runtime staging (overwritten on every run at `coordinator.py:67-69` with the experiment_id-injected config), and (c) the source for the registry archive copy at `coordinator.py:260`. Every run left an uncommitted diff on a tracked file; multiple worktrees each accumulated their own orphan diffs; tests worked around it with a save-and-restore in `conftest.py`.

**Immediate fix (this branch):** gitignore `experiments/active.yaml` and untrack it. Coordinator still writes locally per run, but the write no longer produces git noise. Tests' `conftest.py` was updated to prefer `archive/baseline.yaml` as the stable reference (previously it fell through to whatever `active.yaml` happened to be after the last coordinator write).

**Still open (proper decoupling — deferred):** the coordinator should stage to a runtime-only path (e.g., `dagster_home/current.yaml`) and the registry archive at `coordinator.py:260` should serialize from `self._source_yaml` directly instead of re-reading a file. That eliminates the tracked-file dependency entirely — role (b) and role (c) stop sharing a path with role (a). Not blocking agentic robustness work, but the right shape for the long term.

## 5. Capsule ID collision — what's the fallback?

**STATUS:** #5a SHIPPED (PR #114) — detection classifies fresh/duplicate/collision. #5b DEFERRED — ID widening options B1–B4 preserved; wait for real trigger. #5c SHIPPED (PR #116) — set-like list canonicalization so permutation resubmits register as duplicate not collision.

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

**Interaction with 5a:** `check_registry` compares parsed YAML trees. Since ConfigLoader now canonicalizes on load, permutation-resubmits (same experiment, matrix values reordered) hash to the same exp_id and their parsed dicts compare equal → classified `"duplicate"`, not `"collision"`.

## 6. AGENTS.md loading is opt-in for standalone scripts

**STATUS: CLOSED via PR #113 as YAGNI 2026-07-03 (extract when justified, not before).** Standalone Python scripts (`scripts/autonomous_agent.py`) don't automatically read AGENTS.md the way harnesses like Claude Code or Cursor do — that's harness-level behavior. PR #107 added an explicit `load_agents_md()` (~40 lines) to the agent script.

Decision: not extracting `sql_benchmarks.agent_utils` speculatively. The extraction cost (module boundary, tests, docs) exceeds the current benefit (one caller). When a second agent script appears that needs the same loader — or when the loader grows beyond what fits in a single script — extract then. The one-caller shape is not a smell; the extract-for-hypothetical-reuse is. See also: [experiment config design memory](/Users/ramona/.claude/projects/-Users-ramona-Projects-sql-benchmarks-dagster/memory/experiment-config-design.md) — same principle (no templating until a real second consumer appears).

---

## Related (already fixed)

- **Agent silent-exit on empty/hallucinated tool response** — PR #106.
- **API-key handling + AGENTS.md loading in autonomous_agent.py** — PR #107.
- **Autonomous agent goal hardcodes the suite name** — the default `--goal` in `__main__` tells the agent to use `analytical_wall` instead of asking it to reason from `list_suites`. Not a bug (`--goal` is overridable), but the default should be intent-level, not suite-level.
