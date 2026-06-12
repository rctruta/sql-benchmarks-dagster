# Published Capsules

Every published claim cites an 8-character **Experiment ID** — a SHA-256
fingerprint of the experiment's config, SQL, and all measurement-relevant
code. The capsules below are committed in full (`sql_benchmarks/experiments/results/<ID>/`)
so any cited number can be inspected down to its raw replication measurements.

| ID | Experiment | Config | Finding |
|---|---|---|---|
| `3e2fe152` | Quack execution modes | [quack_execution_modes.yaml](../sql_benchmarks/experiments/queue/quack_execution_modes.yaml) | Attach-mode overhead grows with scan size (2.6× @100K → 8.8× @10M rows); pushdown stays flat at ~2×. Mechanism: attach mode streams table data client-side; pushdown ships only results. [Figure](figures/execution_modes_3e2fe152.png) |
| `45db01a4` | Pushdown residual: thread probe | [quack_residual_threads.yaml](../sql_benchmarks/experiments/queue/quack_residual_threads.yaml) | Pushdown's flat ~2× residual matches in-process DuckDB at 2–4 effective threads (of 8) — consistent with reduced parallelism in the server's execution context, not protocol transport. |
| `0ee24e68` | Quack vs Postgres head-to-head | [quack_vs_postgres.yaml](../sql_benchmarks/experiments/queue/quack_vs_postgres.yaml) | Client-server vs client-server: DuckDB-over-Quack (pushdown, beta) beats Postgres at every scale beyond the noise floor — 3.4× @100K, 6.1× @1M, 10.7× @10M rows. Caveat disclosed in the config: Postgres pays macOS Docker-VM tax on this bench. |
| `25ce1385` | TPC-H Q3 validation | [tpch_quack_validation.yaml](../sql_benchmarks/experiments/queue/tpch_quack_validation.yaml) | On canonical dbgen data, pushdown holds ~1.7× on a 3-way join; attach mode cannot execute multi-table joins at all (DNF, "multiple streaming scans not supported" — see duckdb-quack [#150](https://github.com/duckdb/duckdb-quack/issues/150)/[#154](https://github.com/duckdb/duckdb-quack/issues/154)). |

All four: DuckDB 1.5.3 (Quack beta), replication 5, cold cache per query,
idle bench. Full conditions in each capsule's `metadata_<ID>.json`.

## What's in a capsule

```
results/<ID>/
├── <ID>.csv                 # flattened matrix: Duration, Duration_Min/Max, DNF per (engine × partition)
├── <ID>.html                # generated dashboard
├── fragments/*.json         # atomic measurements incl. durations_raw (every replication)
├── metadata_<ID>.json       # conditions: engine/Python versions, OS, machine, cores, RAM
├── experiment_config.yaml   # the exact config that ran
├── integrity.seal           # SHA-256 over every capsule file — tamper evidence
└── data_stats/              # generated-data statistics
```

## How to verify a capsule hasn't been tampered with

```
python scripts/dev/verify_capsule.py <ID>
```

recomputes the aggregate hash over the capsule's files and compares it to
the stored `integrity.seal`.

## How to reproduce

1. **Inspect**: open the capsule — the raw numbers behind every claim are there.
2. **Re-derive**: run the committed config on the same code revision:
   `./run.sh sql_benchmarks/experiments/queue/<config>.yaml --auto`.
   The same question produces the same ID; if code or config drifted, the ID
   changes and the comparison is refused by construction.
3. **Compare across benches**: your absolute milliseconds will differ from ours —
   compare the *ratios*. Your capsule's metadata records your bench, as ours records ours.
