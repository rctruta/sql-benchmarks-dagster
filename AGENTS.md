# Agentic Benchmarking Protocol

> **Specification for AI agents and orchestrators interacting with the SQL Benchmarking Laboratory.**

The lab is an **empirical benchmarking harness**: every experiment is identified by a
content-addressed hash, every result is a verifiable capsule, and every interface below
is machine-first. An agent can verify a performance hypothesis here instead of asserting it.

---

## Standard Engineering Practices (No One-Offs)

- All code, scripts, linters, and configurations must adhere to standard engineering practices.
- Do not create ad-hoc, brittle single-use scripts, custom regex parsers, or bespoke governance mechanisms where industry-standard tooling exists.
- **Private material stays outside the repository.** Personal notes, summaries of chat conversations, local machine paths, and unpublished work are never copied in, referenced by absolute path, or quoted in code, comments, tests, commit messages or PR text. Code that needs private data reads its location from an environment variable.

---

## Documentation Triggers (When to Update README)

Do NOT update the README for internal bug fixes, refactorings, or minor code edits.
Review and update README and agent instructions ONLY when a change crosses an external boundary:
1. **CLI / Entrypoints:** A command, CLI flag, or runner script is added, renamed, or removed.
2. **Dependencies & Toolchain:** A dependency, interpreter version, or external tool requirement is changed in `pyproject.toml`.
3. **Environment & Configuration:** A new environment variable, configuration table, or setup prerequisite is introduced.
4. **Repository Layout:** A top-level directory or primary data pipeline is added, moved, or removed.
If none of these boundaries was crossed, leave the README untouched.

---

## Four ways in

1. **Filesystem + CLI** (zero infrastructure): write a YAML config, run it, read the capsule.
2. **REST API** (`python serve.py`, then `http://localhost:8000/docs`): catalog, results,
   cross-engine comparison, engine recommendation, async experiment submission.
3. **MCP server, this checkout** (`python mcp_server.py`): the same capabilities as
   native tools for MCP-capable agents. Requires the REST API to be running — it is
   an HTTP client against `SB_API_BASE`, default `http://localhost:8000`.
   *(Note: This repository is natively Agent-Ready. It ships a `claude.json` configuration, meaning Claude Code will automatically mount the MCP server upon entering the directory.)*
4. **MCP server, installed** (`uvx --from sqlbenchdag sqlbench-mcp`): the published
   entry point, `sql_benchmarks.mcp.server`. **No REST API and no setup** — it reads
   the committed capsules directly, so a cold install answers questions about
   pre-computed results in one command. This is the path anyone outside this
   repository uses; the two servers are separate code with separate requirements.

---

## The agentic loop (CLI form)

1. **Hypothesis** — e.g. "Quack's attach mode degrades with scan size."
2. **Submit** — write a YAML config to `sql_benchmarks/experiments/queue/` (configs outside
   the experiments directory are rejected). Start from a curated template — either the
   fully-annotated `sql_benchmarks/experiments/templates/experiment_template.yaml`, or
   an existing valid experiment in `sql_benchmarks/experiments/queue/` (e.g.
   `quickstart.yaml`). REST-API agents fetch templates via `GET /v1/catalog/templates`
   and `GET /v1/catalog/templates/{name}` — see "Template discovery" below.
3. **Execute** — `./run.sh sql_benchmarks/experiments/queue/my_exp.yaml --auto`
4. **Identity** — the system derives the 8-character **Experiment ID**: a SHA-256 fingerprint
   of the config + the SQL + all measurement-relevant Python (orchestration, engine clients,
   data generators). Formatting and comments never change an ID; logic always does.
5. **Retrieve** — `sql_benchmarks/experiments/results/<ID>/`:
   - `<ID>.csv` — flattened matrix: one row per (engine × partition), with `Duration`,
     `Duration_Min`/`Duration_Max` (replication spread), and `DNF` (did-not-finish:
     an engine limitation recorded as data, not a crash)
   - `fragments/*.json` — atomic per-partition measurements including `durations_raw`
     (every replication, not just the mean)
   - `metadata_<ID>.json` — the **conditions**: engine/Python versions, OS, machine, cores, RAM
   - `experiment_config.yaml` — the exact config that ran, archived **verbatim** (the
     author's source bytes, not a re-serialization)
   - `queries/<dialect>/*.sql` — the exact SQL each engine ran (the dialect set the
     config's engines selected)

**Zero-cost cache lookup**: identical question ⇒ identical ID. Check
`results/<ID>/` before running; if it exists, the answer is already on disk.

---

## Reading results — pick the right shape

Three endpoints for reading a completed experiment. Pick by the shape of the
question:

```
GET /v1/results/<id>                         # full raw fragments (mean/median/p95 + per-rep durations)
GET /v1/results/<id>/compare                 # aggregated ranking across all partitions
GET /v1/results/<id>/compare/by-partition    # one ranking per partition (scaling / matrix-sweep)
```

**Rule:** `/compare` aggregates across partitions. If the experiment ran a
matrix sweep (e.g., `rows: [tiny, small, large]`), the aggregate view
flattens the scaling curve and can give a misleading "winner." For scaling
analysis, always use `/compare/by-partition` or read the raw fragments.

An agent asking *"which engine is fastest?"* wants `/compare`. An agent asking
*"how does DuckDB scale from 100 to 1M rows?"* wants `/compare/by-partition`.
An agent computing anything from raw measurements (spread, distribution
tails, p95 across replications) wants `/v1/results/<id>` — the fragments
carry `durations_raw` per replication, not just the mean.

---

## Template discovery (REST API)

The SQL each suite runs expects a *specific* dataset shape — particular tables and columns.
Constructing a valid dataset from scratch means reverse-engineering that contract from
the SQL. Templates short-circuit this: they are human-curated example configs where the
dataset and the suite already match.

```
GET /v1/catalog/templates            → [{name, description, path}, ...]
GET /v1/catalog/templates/<name>     → {name, content, path}   # `content` is the raw YAML text
```

Templates are drawn from `experiments/templates/` and `experiments/queue/`. Runtime
queue entries (files whose stem is an 8-char experiment_id) are excluded — they're
coordinator artifacts, not curated examples.

**Recommended REST-API flow for an agent:** `list_suites` (understand what SQL runs)
→ `list_templates` (see available starters) → `get_template(<name>)` (fetch the YAML)
→ adapt it (change engines, scale, matrix) → `POST /v1/experiments` (submit the adapted text).
This gets you a working dataset shape without inferring it from SQL.

---

## Experiment YAML essentials

```yaml
dataset:
  source: sql_benchmarks.plugins.data_sources.declarative_gen   # or ...tpc_h (official dbgen)
  seed: 42            # optional; data seed is part of the config, hence part of the ID
  tables: { ... }

execution:
  test_suite: analytical_wall          # selects sql/<suite>/<dialect>/*.sql
  engines: [duckdb, quack, quack_pushdown, postgres]
  replication: 3
  engine_params:                       # per-engine tuning namespaces (fixed)
    postgres: {work_mem: "64MB"}
    duckdb:   {threads: 4}
  matrix:                              # varied dimensions => partitions
    rows: [tiny, small]
    postgres.work_mem: [4MB, 1GB]      # namespaced dim = varied engine param
```

Engines: `duckdb` (in-process), `quack` (DuckDB client-server, attach mode),
`quack_pushdown` (server-side execution via `remote.query()`), `quack_adbc` /
`quack_arrow` (Arrow-serving variants), `postgres` (Docker), `postgres_transport`
(different result-serialization path), `actian` / `typedb` (dormant/experimental).
Each engine receives ONLY its own `engine_params` namespace.

---

## Trust rules for agents

- **The ID is the receipt.** It fingerprints the question (config + SQL + measurement code) — so it
  *changes when the measurement code changes*. Reproduce against the build the capsule records
  (`generator` in its `metadata`, e.g. `sqlbenchdag@<sha>`), not arbitrary HEAD; on a different build
  you get a different ID, by design. The `metadata` also records the bench — compare ratios across
  benches, not milliseconds.
- **DNF rows are findings**, not errors — e.g. Quack beta cannot run multi-table joins in
  attach mode; the CSV says so honestly.
- **Spread is published.** `durations_raw` exists so you can check that a claim is not an
  artifact of one lucky replication.
- **Failure capsules**: a failed run leaves config + partial logs for root-cause analysis;
  adjust the YAML and resubmit — the new ID will reflect the change.

---

## Releasing & Packaging Discipline

Package distributions and published wheels are strictly guarded:

1. **A release is a tag, never a local upload.** `release.yml` fires on
   `v*.*.*` and builds from the tagged commit. If you find yourself running
   `twine upload`, stop: whatever is in your working directory is about to
   become public.
2. **If it ships, it is committed.** Before tagging, confirm that every module
   and data file the package needs is on `main` — not merely present on your
   disk. `git ls-files <path>` answers this; `ls` does not.
3. **`include-package-data` stays false.** Package data is whatever
   `[tool.setuptools.package-data]` names and nothing else. Adding a file to
   the distribution is a deliberate line in that table.
4. **`scratch/` is never packaged, never published, never committed.** It is
   where one-off scripts land regardless of which project they operate on, so
   its contents are routinely about other work entirely.
5. **Inspect the artifact, not the build.** List what is actually inside the
   wheel and assert that nothing sits outside the package directory:

   ```sh
   python3 -c "import zipfile,glob,collections; \
     n=zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist(); \
     print(collections.Counter(x.split('/')[0] for x in n))"
   ```

   Anything other than `sql_benchmarks` and `*.dist-info` is a defect.
6. **Then install it and drive it.** A wheel that imports is not a wheel that
   works. `list_categories` returned an empty array on every clean install for
   two months because one data file was missing from the manifest, and the call
   succeeded while returning nothing. Empty-but-successful is the worst failure
   shape: it reads as "no data" rather than "missing file".

## Verifying, and two ways an agent fools itself

- **An empty grep against a file that does not exist is not a negative
  result.** `git show origin/main:some/file.py | grep X` prints nothing both
  when there are no matches and when the file is absent. Check existence
  first; otherwise "no HTTP client found" means "no such file".
- **A check that cannot run has not passed.** A claim registered as verified
  against a URL that answers 403 is not verified by anything. Either make it
  checkable or record it as testimony, and never leave a green status standing
  for a check that never executed.

## The Golden Rule for AI Agents

**Retrieval must be a typed tool, not a foraging behavior.** 

Because this repository ships an active MCP server, you are explicitly forbidden from using raw bash (`ls`, `cat`, `grep`) to forage through `.parquet` data files, `results/` directories, or `SKILL.md` prose files to discover schema or results.

Using bash for data retrieval causes massive token bloat and silent fabrication. You **must** use the provided typed MCP tools for all database querying, catalog discovery, and experiment reading. 
