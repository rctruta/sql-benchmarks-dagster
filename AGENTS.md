# Agentic Benchmarking Protocol

> **Specification for AI agents and orchestrators interacting with the SQL Benchmarking Laboratory.**

The lab is a **deterministic performance oracle**: every experiment is identified by a
content-addressed hash, every result is a verifiable capsule, and every interface below
is machine-first. An agent can verify a performance hypothesis here instead of asserting it.

---

## Three ways in

1. **Filesystem + CLI** (zero infrastructure): write a YAML config, run it, read the capsule.
2. **REST API** (`python serve.py`, then `http://localhost:8000/docs`): catalog, results,
   cross-engine comparison, engine recommendation, async experiment submission.
3. **MCP server** (`python mcp_server.py`): the same capabilities as native tools for
   MCP-capable agents (Claude, etc.). Requires the REST API to be running.

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

### Aliasing convention (one way to do it)

`dataset.tables.<name>.rows` MUST be a string alias into `definitions.rows`,
not a literal integer. The alias is what wires this table into the SQL
template substitution pipeline — SQL like `SELECT ... FROM {{ <name>_table }}`
resolves `<name>_table` to the concrete table only when `rows` is an alias.

```yaml
dataset:
  tables:
    orders:
      rows: rows          # ✅ alias into definitions.rows
      columns: [ ... ]

definitions:
  rows:
    small: 10_000
    large: 1_000_000

execution:
  matrix:
    rows: [small, large]  # sweeps the two scales; both must be keys in definitions.rows
```

Literal ints (`rows: 10000`) are rejected at submission with a message
naming the fix. This is deliberate — one form beats N variations that all
have to be tested against the same downstream pipeline. Matrix values can
be aliases OR literals; the aliasing constraint applies only to
`dataset.tables.<name>.rows`.

The template convention: `{{ <name>_table }}` in SQL substitutes to the
`<name>` table in your dataset. E.g. `SELECT * FROM {{ orders_table }}`
resolves to `SELECT * FROM orders` when your dataset has `tables.orders`.

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
