# Published Capsules

Every published claim cites an 8-character **Experiment ID** — a SHA-256
fingerprint of the experiment's config, SQL, and all measurement-relevant
code. The capsules below are committed in full (`sql_benchmarks/experiments/results/<ID>/`)
so any cited number can be inspected down to its raw replication measurements.

| ID | Experiment | Config | Finding |
|---|---|---|---|
| `48c92f31` | Quack execution modes | [quack_execution_modes.yaml](../sql_benchmarks/experiments/queue/quack_execution_modes.yaml) | Attach-mode overhead grows with scan size (2.7× @100K → 9.4× @10M rows); pushdown stays flat at ~2×. Mechanism: attach mode streams table data client-side; pushdown ships only results. [Figure](figures/execution_modes_48c92f31.png) |
| `2d0105fe` | Pushdown residual: thread probe | [quack_residual_threads.yaml](../sql_benchmarks/experiments/queue/quack_residual_threads.yaml) | Pushdown's flat ~2× residual matches in-process DuckDB at 2–4 effective threads (of 8) — consistent with reduced parallelism in the server's execution context, not protocol transport. |
| `86aececc` | Quack vs Postgres head-to-head | [quack_vs_postgres.yaml](../sql_benchmarks/experiments/queue/quack_vs_postgres.yaml) | Client-server vs client-server: DuckDB-over-Quack (pushdown, beta) beats Postgres at every scale beyond the noise floor — 4.4× @100K, 6.4× @1M, 12.9× @10M rows. Caveat disclosed in the config: Postgres pays macOS Docker-VM tax on this bench. |
| `40f422d5` | TPC-H Q3 validation | [tpch_quack_validation.yaml](../sql_benchmarks/experiments/queue/tpch_quack_validation.yaml) | On canonical dbgen data, pushdown holds ~1.7× on a 3-way join; attach mode cannot execute multi-table joins at all (DNF, "multiple streaming scans not supported" — see duckdb-quack [#150](https://github.com/duckdb/duckdb-quack/issues/150)/[#154](https://github.com/duckdb/duckdb-quack/issues/154)). |

All four: DuckDB 1.5.3 (Quack beta), replication 5, cold cache per query,
idle bench. Full conditions in each capsule's `metadata_<ID>.json`. These four
are the verified set, covered by the signed `capsules-v1` tag.

## Act 0 — the exploratory origin (historical, *not* in the verified set)

| ID | Experiment | Finding |
|---|---|---|
| `b82b4eae` | Quack vs in-process DuckDB (first scout) | Single-replication, two-engine probe that first surfaced the trend: attach-mode overhead *growing* with scan size (2.7× @100K, 4.9× @1M). It motivated the designed experiment `48c92f31`, whose config header still cites it. |

`b82b4eae` is committed so that reference resolves and the scout is inspectable —
but it is deliberately held to a lower bar than the verified set, and you should
treat it accordingly:

- **single replication** (no error bars), only three scale points, no pushdown variant;
- produced under the **pre-migration hashing**, so re-running its config today
  yields a *different* ID — it is re-runnable, not re-derivable to this ID;
- its metadata predates the environment/seed capture, and it is **excluded from
  the signed `capsules-v1` tag**.

It is the lab-notebook entry that came first. The rigorous, verified successor is
`48c92f31`.

## What's in a capsule

```
results/<ID>/
├── <ID>.csv                 # flattened matrix: Duration, Duration_Min/Max, DNF per (engine × partition)
├── <ID>.html                # generated dashboard
├── fragments/*.json         # atomic measurements incl. durations_raw (every replication)
├── metadata_<ID>.json       # conditions: engine/Python versions, OS, machine, cores, RAM
├── experiment_config.yaml   # the exact config that ran
├── integrity.seal           # SHA-256 over every capsule file — tamper evidence
├── scaling.json             # per-engine power-law exponent — see note below
└── data_stats/              # generated-data statistics
```

`scaling.json` is a *derived* artifact: it is auto-written into capsules produced
after the feature landed, but for any capsule — including the four published
here, which predate it — the exponents are regenerated on demand from the sealed
raw fragments with `analyze_scaling.py`. The integrity guarantee lives on the
fragments; scaling is reproducible from them, so its presence as a file is a
convenience, not the source of truth.

## The trust chain — verify without trusting me

A benchmark you have to take on faith isn't evidence. Each published capsule
carries four independent guarantees, and you can check every one yourself:

| Guarantee | Answers | Mechanism | How you check it |
|---|---|---|---|
| **Reproducibility** | Did this question produce this result? | content-addressed Experiment ID | re-run the config → same ID |
| **Integrity** | Have the bytes changed since publication? | `integrity.seal` (SHA-256 over the capsule) | `verify_capsule.py <ID>` |
| **Timestamp** | Did this exist when claimed — not backdated? | `integrity.seal.ots` (OpenTimestamps → Bitcoin) | `ots verify .../integrity.seal.ots` |
| **Authorship** | Who produced it? | signed git tag | `git verify-tag <tag>` |

Together: **a result you can trust without trusting the person who ran it.**

```
python scripts/dev/verify_capsule.py <ID>     # checks integrity + timestamp
```

To verify authorship after cloning (one-time setup, then `git verify-tag`):

```
git config gpg.ssh.allowedSignersFile .github/allowed_signers
git verify-tag capsules-v1     # → Good "git" signature for ramona.truta@gmail.com
```

The repo ships `.github/allowed_signers` mapping the author's identity to the
public signing key, so the signed `capsules-v1` tag is verifiable by anyone
offline — no GitHub account or trust in GitHub required.

The timestamp proof is trustless — it anchors the seal's hash to the Bitcoin
blockchain, so neither I, nor GitHub, nor anyone can backdate or silently
edit a published result without the proof failing. New capsules are stamped
at publication with `scripts/dev/timestamp_capsule.py` (requires
`opentimestamps-client`); proofs start "pending" and finalize after the next
Bitcoin block via `ots upgrade`.

## Scaling law

Each engine's power-law exponent α (complexity class), fit from a capsule's raw
fragments. Regenerate any of these from the sealed data with:

```
python scripts/tools/analyze_scaling.py <ID>
```

**Published capsules with a row-scaled matrix:**

| Capsule | duckdb (in-process) | quack attach | quack pushdown | postgres |
|---|---|---|---|---|
| `48c92f31` | α=0.35 | α=0.55 (~√N) | α=0.32 | — |
| `86aececc` | α=0.36 | — | α=0.32 | α=0.61 |

The reading: **pushdown shares DuckDB's exponent (~0.32–0.36) — same complexity class,
separated only by a constant (the thread tax); attach mode is a worse class
(√N); and Postgres is worse still (0.61), which is why the head-to-head gap
*widens* with scale.** DuckDB reads ~0.35 in both capsules — an independent
consistency check. (`2d0105fe` is a thread sweep and `40f422d5` uses
scale_factor, not a row axis, so neither yields a meaningful scaling fit.)

α≈0 is flat, 0.5 is O(√N), 1 is linear. Engines sharing an α but offset by a
constant factor are the same algorithm at different fixed cost; a larger α is a
worse scaling class. (A meaningful fit needs ≥3 scale points — `n_points` is
recorded so two-point fits, which always show R²=1.0, are obvious.)

## How to reproduce

1. **Inspect**: open the capsule — the raw numbers behind every claim are there.
2. **Re-derive**: run the committed config on the same code revision:
   `./run.sh sql_benchmarks/experiments/queue/<config>.yaml --auto`.
   The same question produces the same ID; if code or config drifted, the ID
   changes and the comparison is refused by construction.
3. **Compare across benches**: your absolute milliseconds will differ from ours —
   compare the *ratios*. Your capsule's metadata records your bench, as ours records ours.
