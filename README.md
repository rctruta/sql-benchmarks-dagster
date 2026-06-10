# SQL Benchmarking Laboratory

> **A deterministic, orchestrated harness for verifying database performance at scale.**
> Developed by Ramona C. Truta

---

## The Mission: "Ground Truth" as Code

This platform is a specialized laboratory for testing SQL performance hypotheses. It transforms query tuning from intuition into a reproducible science. 

The core of the system is a **Deterministic Orchestration Harness** that guarantees that if the logic or the environment changes, the benchmark result changes. If they do not, the result is addressable and cached.

---

## Key Features & Innovations

### 1. Context-Aware Semantic Hashing (The Experiment ID)
The Heart of the system is the **Experiment ID**, an 8-character hash that governs the entire lifecycle. This hash is a SHA-256 fingerprint generated from:
*   **The Config**: Every dimension in your YAML (rows, skew, parameters).
*   **The SQL Logic**: The actual content of the benchmarked scripts.
*   **The Python Assets**: The orchestration logic in `sql_benchmarks/assets/`.

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
*   **Docker & Docker Compose**: For containerized engine management.
*   **Python 3.11+**: Core platform runtime.
*   **Dagster**: Orchestration and state management.

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
./run.sh sql_benchmarks/experiments/queue/baseline.yaml --auto
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

## Experiment Library

| Experiment | YAML Config | SQL Scenario | Description |
| :--- | :--- | :--- | :--- |
| **Selectivity Cliff** | [selectivity_test.yaml](sql_benchmarks/experiments/archive/selectivity_test.yaml) | `/selectivity/` | Testing row-store vs columnar on varying scan selectivity. |
| **Null Density** | [null_identity.yaml](sql_benchmarks/experiments/queue/null_identity.yaml) | `/null_logic/` | Benchmarking 3-Valued Logic vs Identity Logic in Joins. |
| **Sentinel Optimization**| [null_sentinel.yaml](sql_benchmarks/experiments/queue/null_sentinel.yaml) | `/null_sentinel/` | Testing materialization prep vs query-time 2VL logic. |
| **Recursive Depth** | [recursivity_test.yaml](sql_benchmarks/experiments/archive/recursivity_test.yaml) | `/recursion/` | Measuring the performance of deep Recursive CTEs. |

---

## License

Copyright 2025-2026 Ramona C. Truta. Licensed under the [Apache License 2.0](LICENSE).

Built with **Dagster**, **Polars**, **Docker**, **DuckDB**, and **Postgres**.