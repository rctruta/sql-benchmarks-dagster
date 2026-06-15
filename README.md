# SQL Benchmarking Laboratory

> **A deterministic, orchestrated harness for verifying database performance at scale.**
> Developed by Ramona C. Truta

---

## The Mission: "Ground Truth" as Code

This platform is a specialized laboratory for testing SQL performance hypotheses. It transforms query tuning from intuition into a reproducible science. 

The core of the system is a **Deterministic Orchestration Harness** that guarantees that if the logic or the environment changes, the benchmark result changes. If they do not, the result is addressable and cached.

**Scope:** the focus to date is **synthetic and canonical (TPC-H) data**, which
is the right instrument for *mechanism* experiments — where controlled,
reproducible data isolates the variable under test. Real-data support exists but
is experimental; see the [FAQ](FAQ.md) for the synthetic-vs-real rationale, the
container model, and the roadmap (AI-security testbed, real-data trust chain).

---

## Key Features & Innovations

### 1. Context-Aware Semantic Hashing (The Experiment ID)
The Heart of the system is the **Experiment ID**, an 8-character hash that governs the entire lifecycle. This hash is a SHA-256 fingerprint generated from:
*   **The Config**: Every dimension in your YAML (rows, skew, parameters).
*   **The SQL Logic**: The actual content of the benchmarked scripts.
*   **The Code**: All measurement-relevant Python — orchestration (`assets/`), engine clients (`resources/`), and data generators (`plugins/`).

**Semantic Normalization**: The hashing engine distinguishes between a logic change and a formatting change. 
*   **SQL**: Comments, whitespace, and case are normalized before hashing.
*   **Python**: Orchestration scripts are parsed into an **Abstract Syntax Tree (AST)** to strip docstrings and formatting variations, ensuring the Experiment ID only changes when execution logic changes.

### 2. Multi-Layer Cold-Cache Isolation
To ensure IO-bound performance is not masked by memory buffers, we implement a dual-layer cold start mechanism:
*   **Out-of-Process (Postgres)**: Mandatory **Docker Container Restarts** before every query to clear engine-level shared buffers.
*   **Global OS Flush (mmap)**: A specialized `thrash_os_cache` primitive that maps and dirties a file larger than physical RAM. This forces the OS to evict Page Cache entries, ensuring cold read performance for both containerized and in-process (DuckDB) engines.

### 3. Agentic AI Integration
The platform is built for the future of **Autonomous Engineering**. The Experiment ID allows AI agents to treat the laboratory as a **Deterministic Performance API**.
*   See [AGENTS.md](AGENTS.md) for the full Agentic Benchmarking Protocol.

### 4. Declarative Matrix Orchestration
Benchmarks are defined as N-dimensional matrices in YAML. The platform expands these into a Cartesian product of **Independent Dagster Partitions**. This allows for parallel dispatch and granular retries.

---

## Usage & Technical Setup

### Prerequisites
*   **[uv](https://astral.sh/uv)**: the project's Python environment & dependency manager (fast, modern). `setup.sh` uses it, and it can install Python 3.11 for you.
*   **Python 3.11+**: core runtime (uv provisions it if missing).
*   **Docker**: for the containerized engines (Postgres, TypeDB), which the harness manages itself — *not* required for the DuckDB-only quickstart.

### Installation & Setup
The laboratory includes a comprehensive setup script that manages virtual environments, dependencies, and directory initialization.

```bash
# 1. Automate Setup
chmod +x setup.sh && ./setup.sh

# 2. Activate Laboratory
source venv/bin/activate
```

### The Execution Workflow (CLI)
While the system is powered by Dagster, the primary interface is the CLI for automated workflows.

```bash
# QUICKSTART: DuckDB only, no Docker required — runs in seconds
./run.sh sql_benchmarks/experiments/queue/quickstart.yaml --auto

# FULL BENCHMARK: Run all queued experiments (requires Docker for Postgres)
./run.sh queue --auto

# SINGLE EXPERIMENT: Pass a specific config path
./run.sh sql_benchmarks/experiments/queue/quack_execution_modes.yaml --auto
```

---

## Project Structure
Managed with a strict separation between Harness and Scenario:

```text
/sql_benchmarks
├── /assets                 # THE HARNESS: Dagster factories & pipeline logic
├── /resources              # THE INFRASTRUCTURE: DB drivers & Docker management
├── /scripts/sql            # THE SCENARIOS: Raw SQL partitioned by scenario
├── /plugins                # THE DATA: Declarative generators & scenario providers
├── /utils                  # THE BRAIN: AST-hashing, common logic, & system primitives
└── /experiments            # THE LABORATORY
    ├── active.yaml         # Current active partition matrix
    ├── /queue              # Staging area for new experiment configs
    ├── /archive            # Library of previously defined experiment templates
    ├── /configs            # Registry of immutable, hash-addressed experiment capsules
    └── /results            # Data capsules: fragments, CSVs, and Dashboards
```

---

## Published Experiments — the Quack investigation

The first published study with this lab: an independent measurement of DuckDB's
**Quack** client-server protocol (beta, v1.5.3). Each row links the runnable
config to its committed, verifiable capsule. Full numbers, scaling exponents,
and verification steps in [docs/published_capsules.md](docs/published_capsules.md).

| Act | Question | Config | Capsule | Finding |
| :--- | :--- | :--- | :--- | :--- |
| **I** | What does the protocol cost? | [quack_execution_modes.yaml](sql_benchmarks/experiments/queue/quack_execution_modes.yaml) | `b8e2bfaf` | Attach-mode overhead grows with scan size (2.6× → **9.5×** at 10M rows); pushdown stays flat at ~2×. |
| **II** | Why is pushdown ~2× and not 1×? | [quack_residual_threads.yaml](sql_benchmarks/experiments/queue/quack_residual_threads.yaml) | `25b0e134` | The residual tracks reduced server-side parallelism (~2–4 of 8 threads), not transport. |
| **III** | Does it generalize to joins? | [tpch_quack_validation.yaml](sql_benchmarks/experiments/queue/tpch_quack_validation.yaml) | `b198363e` | On canonical TPC-H Q3, pushdown holds (~1.7×); attach mode **cannot run the join at all** (DNF). |
| **IV** | Does it beat the incumbent? | [quack_vs_postgres.yaml](sql_benchmarks/experiments/queue/quack_vs_postgres.yaml) | `902d1277` | DuckDB-over-Quack (pushdown) beats PostgreSQL by up to **13.2×**, and the gap widens with scale. |
| **V** | What does an index buy — and cost? | [quack_selectivity.yaml](sql_benchmarks/experiments/queue/quack_selectivity.yaml) | `461beee8` · `28f7aa1c` | The Postgres optimizer tipping point: an index-only scan wins at 0.1% selectivity, but a bitmap heap scan at 5% is **slower than a seq scan** on a cold cache. Indexed vs no-index, EXPLAIN-verified. |

*Act 0 (`b82b4eae`) is the exploratory scout that started it — see published_capsules.md.*
*Act V is covered by its own signed tag, `sqlbenchdag-quack-selectivity-v1-20260615`.*

The lab also ships scenario suites for other studies — `selectivity/`,
`null_logic/`, `null_sentinel/`, `recursion/`, `sort_spill/`, `tpch/`, and more
under `sql_benchmarks/scripts/sql/` — each runnable across the engine matrix.

---

## Naming & Provenance

The lab works at two layers, named two different ways. Keeping them distinct is
the difference between a number you can trace and a number you have to trust.

| Layer | What it is | Named by | Example |
| :--- | :--- | :--- | :--- |
| **Capsule** | one experiment's complete results | its **Experiment ID** — an 8-char SHA-256 of the *question* (config + SQL + measurement code), assigned by the machine | `48c92f31` |
| **Release** | a signed set of capsules backing a publication | a human name: **`sqlbenchdag-<topic>-v<N>-<YYYYMMDD>`** | `sqlbenchdag-quack-v1-20260614` |

A release *contains* capsules; a capsule is one experiment. The machine names
capsules (hashes you can't forge); the author names releases (words that mean
something). `sqlbenchdag` is the lab's maker's mark — `sql` + `bench` +
`dag` (Dagster, the orchestration that distinguishes this lab from a bare query
timer). It is carried on every release this lab produces.

**Two hashes, two jobs** (a capsule contains both — they are not the same thing):
- the **Experiment ID** (8 chars) is an *address* — it *names* the capsule, and
  the same question always produces the same address;
- the **integrity seal** (64 chars, in `integrity.seal`) is a *checksum* — it
  *verifies* the capsule's contents are untouched. You file by the address; the
  seal is the tamper-evident lid.

**Reproducibility is pinned to the release.** Because the Experiment ID hashes
the measurement code, it is stable only at a fixed code revision — which is
exactly what the signed release tag freezes. To reproduce a published capsule,
check out its release tag and re-run its config; the same question yields the
same ID, or the comparison is refused by construction.

> Provenance roadmap: a per-capsule `generator` stamp (`sqlbenchdag@<commit>`)
> will record the exact build that produced each capsule. It writes through the
> finalization code, which lives inside the Experiment-ID hash, so it ships with
> a future release rather than re-numbering capsules already published.

See [docs/published_capsules.md](docs/published_capsules.md) for the full trust
chain (reproducibility, integrity, timestamp, authorship) and how to verify each.

---

## License

Copyright 2025-2026 Ramona C. Truta. Licensed under the [Apache License 2.0](LICENSE).

Built with **Dagster**, **Polars**, **Docker**, **DuckDB**, and **Postgres**.