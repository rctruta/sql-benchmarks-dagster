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
   the experiments directory are rejected).
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
   - `experiment_config.yaml` — the exact config that ran

**Zero-cost cache lookup**: identical question ⇒ identical ID. Check
`results/<ID>/` before running; if it exists, the answer is already on disk.

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
`quack_pushdown` (server-side execution via `remote.query()`), `postgres` (Docker),
`actian` / `typedb` (dormant/experimental). Each engine receives ONLY its own
`engine_params` namespace.

---

## Trust rules for agents

- **The ID is the receipt.** It fingerprints the question (config + SQL + code). The capsule's
  `metadata` block records the bench it ran on. Compare ratios across benches, not milliseconds.
- **DNF rows are findings**, not errors — e.g. Quack beta cannot run multi-table joins in
  attach mode; the CSV says so honestly.
- **Spread is published.** `durations_raw` exists so you can check that a claim is not an
  artifact of one lucky replication.
- **Failure capsules**: a failed run leaves config + partial logs for root-cause analysis;
  adjust the YAML and resubmit — the new ID will reflect the change.
