# SQL Benchmarks Platform: The "Systems Thinking" Harness

**Architect:** Ramona C. Truta
**Tech Stack:** Dagster, DuckDB, Postgres (Docker), Python, Jinja2

## 🚀 The Mission
This platform is not just a script; it is an orchestrated laboratory for testing SQL antipatterns. It transforms "anecdotal performance tuning" into reproducible science.

It was designed to prove (or disprove) database myths—specifically the impact of **"Left Join with NULL filters"** (the Defensive Join Antipattern) under high-skew data conditions (10% Orphan Records).

## 🏗 Architecture
The system follows a **Multi-Engine Asset Factory** pattern:
1.  **Data Generation:** Creates synthetic relational data (Parquet) with configurable "Orphan" rates to stress-test optimizers.
2. **Ingestion:**
    * **DuckDB:** Ingests Parquet into a local file-based DB. Implements **Sequential Locking** to handle concurrency limits.
    * **Postgres:** Ingests Parquet via Pandas into a Dockerized Postgres 16 container.
3. **The Asset Factory:**
    * Scans a library of raw `.sql` files (`scripts/sql/`).
    * Uses **Jinja2** to inject partition names (`orders_small` vs `orders_medium`).
    * Auto-generates Dagster Assets for each query.
4. **Scientific Rigor:**
    * **DuckDB:** Forces `fetchall()` to capture full execution time (defeating lazy evaluation).
    * **Postgres:** Triggers `docker restart` before every query to guarantee a **Cold Start** (clearing OS Page Cache & Shared Buffers).

## 🛠️ Setup & Installation

### 1. Prerequisites
* Python 3.10+
* Docker & Docker Compose

### 2. Infrastructure (Postgres)
Start the database container:
```bash
dagster dev
```

### 3. Environment

Create and activate the virtual environment:
```
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### 4. Running the Platform

Launch the Dagster UI:
```bash
dagster dev
```
Navigate to [http://localhost:3000](http://localhost:3000).

## 🧪 How to Add a New Experiment

You do not need to write Python code to add a test case.

1. Create an `.sql` file in `sql_benchmarks/scripts/sql/duckdb/ (or postgres/)`.

2. Use the Jinja variables `{{ orders_table }}` and `{{ customers_table }}`.

3. Reload Dagster. The system automatically provisions the new benchmark asset.

## 📊 Key Findings

1. **Hypothesis**: Modern query optimizers can rewrite "Defensive Joins" into efficient Inner Joins.

2. **Result**: FALSE under high skew.

3. **Data**: At 10% Orphan records, DuckDB performance degraded by ~1000% (0.8s vs 21s) compared to the recommended query.

© 2025 Ramona C. Truta. All Rights Reserved.

Here is the "Stellar README" draft. It frames the project as an **Engineering Case Study**, not just a repo.

It starts with the **"Hook"** (The Memory Cliff), moves to the **"Architecture"** (The Agentic System), and ends with the **"Instructions"** (How to run it).

**Action:** Replace your current `README.md` with this text.

-----

# The Deterministic Data Lab

> **A reproducible, agentic benchmarking platform for SQL engines.**
> *Architected with Dagster, Polars, Docker, and DuckDB.*

*Figure 1: The "Memory Cliff." Postgres performance collapses by 10x when the working set exceeds physical RAM, while DuckDB remains performant due to columnar compression.*

## 1\. The Problem: "Vibes" vs. Verification

Database tuning is often tribal knowledge. We "feel" like an index helps, or we "assume" SSDs fix bad queries. But rarely do we treat infrastructure with the rigor of a scientific experiment.

I built this platform to replace intuition with **Ground Truth**. It is designed to be:

1.  **Deterministic:** If the inputs (Config + SQL + Code) are the same, the result is cached.
2.  **Isolated:** Every query runs against a "Cold Cache" (via Docker restarts & OS memory flushing).
3.  **Agentic:** The platform accepts declarative YAML contracts, making it the perfect backend for AI Agents to test hypotheses without hallucinating.

-----

## 2\. The Architecture (V7)

This is not a script. It is a **Platform** implementing the Factory Pattern.

[Image of V7 Architecture Diagram]

### Key Engineering Decisions

| Feature | The Problem | The Solution |
| :--- | :--- | :--- |
| **Declarative Contracts** | Hardcoded Python scripts are fragile. | **YAML-Driven Architecture:** Experiments are defined as data. The system dynamically generates assets based on dimensions. |
| **Idempotency** | Re-running expensive benchmarks wastes time. | **Semantic Hashing:** We hash the AST of the code + Normalized SQL + Config. If the hash matches, we return the cached artifact. |
| **The "Cold Start"** | Benchmarks are noisy due to OS/DB caching. | **Docker & Syscalls:** We restart the Postgres container and use `mmap` to flush the OS Page Cache before *every* query. |
| **The OOM Crash** | Loading 50M rows crashed my 16GB laptop. | **Streaming Ingestion:** A custom Polars -\> PyArrow -\> Postgres COPY pipeline that streams data in 500k chunks (Constant Memory). |

-----

## 3\. How It Works (The "Agentic Loop")

The platform is designed to be operated by Humans *or* AI Agents.

1.  **Define Intent (YAML):**

    ```yaml
    # experiments/queue/selectivity_test.yaml
    dataset:
      tables:
        orders:
          rows: 10_000_000
          skew: "high"
    execution:
      engine: ["postgres", "duckdb"]
    ```

2.  **The Factory (Dagster):**
    The system reads the YAML and generates a Directed Acyclic Graph (DAG) of assets:

      * `synthetic_data` (Parquet)
      * `ingest_postgres` (Table)
      * `benchmark_query` (Result)

3.  **Execution (Docker):**

      * **Postgres:** Container is restarted. `work_mem` is auto-tuned based on row count.
      * **DuckDB:** Runs in-process with OS cache flushing.

4.  **Result (Ground Truth):**
    A structured HTML dashboard and CSV dataset are generated, proving exactly where performance degrades.

-----

## 4\. Quick Start

### Prerequisites

  * Docker & Docker Compose
  * Python 3.9+

### Installation

```bash
# 1. Clone the Lab
git clone https://github.com/your-username/sql-benchmarks-dagster.git
cd sql-benchmarks-dagster

# 2. Install Dependencies (Virtual Env Recommended)
pip install -e ".[dev]"

# 3. Start the Platform
dagster dev
```

### Running Your First Experiment

1.  Open the Dagster UI (`localhost:3000`).
2.  Navigate to **Assets**.
3.  Click **Materialize All** to run the default `baseline.yaml` experiment.
4.  Watch the "Cold Cache" mechanism in the logs.

-----

## 5. Project Structure

This repo follows a **Strict Separation of Concerns**, ensuring the "Brain" (Utils) never touches the "Muscle" (Resources) directly.

/sql_benchmarks
├── /assets                 # The Orchestration Layer (Dagster Factories)
│   ├── data_factory.py          # Generates synthetic/raw data assets
│   ├── ingestion_factory.py     # Generates data loading & DDL assets
│   ├── benchmark_factory.py     # Generates query execution assets
│   └── reporting.py             # Generates HTML dashboards
├── /resources              # The Infrastructure Layer
│   ├── postgres.py              # Docker container control & stream loading
│   └── duckdb.py                # In-process OLAP engine
├── /utils                  # The Logic Layer (Pure Python)
│   ├── common.py                # Config parsing, math normalization, & DDL generation
│   ├── hasher.py                # AST-based Semantic Hashing (Idempotency)
│   └── system.py                # OS Memory Primitives (Safe RAM flushing)
├── /plugins                # Data Generation Plugins
│   └── data_sources/            # Pluggable generators (Synthetic, TPC-H, Local)
└── /experiments            # The Data Contracts (YAML)
    ├── active.yaml              # The currently loaded experiment configuration
    ├── /queue                   # Drop YAML files here to auto-schedule runs
    ├── /archive                 # Historical experiments 
    ├── /configs                 # Immutable hash-addressed config storage
    └── /results                 # Structured outputs (CSV & HTML Reports)

## 6\. Testing Strategy

This platform is self-verifying. We use a 3-tier test suite:

  * **Integrity Tests:** `test_config_integrity.py` validates that YAML files obey the laws of physics (no negative weights, broken FKs).
  * **Logic Tests:** `test_hasher_extended.py` proves that code comments/formatting do not invalidate the cache (AST Hashing).
  * **Mock Tests:** `test_resources.py` verifies database interactions without spinning up Docker.

<!-- end list -->

```bash
# Run the full suite
pytest sql_benchmarks_tests/
```

-----

**Built with:** [Dagster](https://dagster.io) | [Polars](https://pola.rs) | [Docker](https://www.docker.com/) | [Postgres](https://www.postgresql.org/) | [DuckDB](https://duckdb.org/)

-----

**One Final check:**
Do you have the **"Cliff Chart"** image file? If so, upload it to your repo (e.g., in `docs/cliff.png`) and update the link in the README. That image is the "Money Shot."


You are absolutely right. A "Menu of Experiments" (the table) transforms the repo from a "tool" into a "Scientific Journal." It shows that you didn't just build a runner; you used it to find answers.

Regarding the Partitioning Logic: **This is your "Systems Architect" flex.** Most people write loops. You architected a **Dimensional Matrix**. Explaining *why* (Isolation per intersection) is critical.

Here are the **Blind Spots** you missed, followed by the **Finalized README Structure**.

### The Blind Spots Check

1.  **Hardware Requirements:**

      * *Spot:* You mention "16GB Laptop" in the blog, but the README needs to warn users. If they run the `100M row` config on an 8GB Air, they won't just see a cliff; they might crash their OS.
      * *Fix:* Add a "Recommended Hardware" section.

2.  **The "Why" of Dynamic Partitions:**

      * *Spot:* You mentioned "combinations," but the key insight is **Execution Independence**.
      * *Fix:* Explain that Partition A (Postgres) and Partition B (DuckDB) can run in *parallel* because they are logically isolated assets. This justifies using Dagster over a simple Python loop.

3.  **The "Agent Interface" Definition:**

      * *Spot:* We talk *about* Agents, but we don't show *how* they interface.
      * *Fix:* Explicitly state: "Agents interact with this system via the file system (`experiments/queue/`). The platform watches this folder."

-----

### The Master README Draft

Here is the revised structure. It integrates your Table idea and the Partition logic into a cohesive narrative.

**(Copy-paste this into `README.md`)**

-----

# The Deterministic Data Lab

> **A reproducible, agentic benchmarking platform for SQL engines.**
> *Architected with Dagster, Polars, Docker, and DuckDB.*

*Figure 1: The "Memory Cliff." Postgres performance collapses by 10x when the working set (\~20GB) exceeds physical RAM (16GB), regardless of SSD tuning. DuckDB (columnar) handles the overflow gracefully.*

## 1\. The Architecture: "Ground Truth" as Code

Data engineering often relies on "Vibes" (intuition). This platform relies on **Physics**.
I built a factory that turns Declarative YAML Contracts into isolated, cold-cache experiments.

### The Core Design Pattern

1.  **Declarative Contracts:** Experiments are defined in YAML, not code.
2.  **Semantic Hashing:** We hash the AST of the Python code + Normalized SQL + YAML Config. If the hash exists, execution is skipped. **The platform is Idempotent.**
3.  **Isolation:**
      * **Postgres:** Docker container restarts before *every* query.
      * **DuckDB:** In-process execution with OS `mmap` flushing.
4.  **Streaming Ingestion:** A custom Polars $\rightarrow$ PyArrow $\rightarrow$ Postgres COPY pipeline streams 50M+ rows in constant memory (\~100MB RAM), solving the Python OOM crash.

-----

## 2\. The Experiment Matrix

The platform generates assets using a **Dimensional Matrix**.

  * **Dimensions:** Defined in YAML (e.g., `rows`, `engine`, `skew`, `tuning`).
  * **Partitions:** The Cartesian Product of all dimensions.

**Why this matters:**
Every intersection (e.g., `10M_Rows | Postgres | SSD_Tuned`) becomes a discrete, addressable Dagster Partition. This allows for:

1.  **Parallel Execution:** Different engines run concurrently.
2.  **Failure Isolation:** If Postgres crashes on 100M rows, the DuckDB benchmarks continue.
3.  **Granular Retries:** We can re-run just the failed partition, not the whole suite.

### Experiment Library

The `experiments/` folder contains the "Curriculum" of tests run on this platform.

| Experiment | Config File | SQL Logic | Dimensions Tested | Insight |
| :--- | :--- | :--- | :--- | :--- |
| **The Memory Cliff** | [`selectivity.yaml`](https://www.google.com/search?q=experiments/archive/selectivity.yaml) | [`selectivity/`](https://www.google.com/search?q=sql_benchmarks/scripts/sql/selectivity) | `rows` (10M-100M) <br> `selectivity` (0.1%-20%) | SSD tuning helps small data (+42%), but RAM bottlenecks kill row-store performance regardless of tuning. |
| **Join Explosion** | [`joins.yaml`](https://www.google.com/search?q=experiments/archive/joins.yaml) | [`joins/`](https://www.google.com/search?q=sql_benchmarks/scripts/sql/joins) | `skew` (Uniform vs Zipf) <br> `engine` | Tests how optimizers handle skewed join keys. |
| **Storage Density** | [`compression.yaml`](https://www.google.com/search?q=experiments/archive/compression.yaml) | N/A | `compression` (None, Snappy, Zstd) | Benchmarks disk footprint vs ingestion speed. |

*(Note: Move your YAMLs into `experiments/archive/` and rename them to match this table.)*

-----

## 3\. The "Agentic" Workflow

This platform solves the **LLM Hallucination Problem** regarding database performance. Instead of guessing, an Agent can use this platform as a tool.

1.  **Agent Hypothesis:** "I think an index covers this query."
2.  **Action:** Agent generates `experiments/queue/agent_hypothesis_01.yaml`.
3.  **Reaction:** The Platform detects the file, hashes it, generates the DAG, and executes it.
4.  **Learning:** The Agent reads the resulting `results/agent_hypothesis_01.csv` to see the *actual* execution time.

-----

## 4\. Quick Start

### Hardware Requirements

  * **RAM:** 16GB Minimum (to test the "Cliff").
  * **Disk:** SSD required (HDD will skew results).
  * **OS:** Linux/Mac (Windows requires WSL2 for Docker performance).

### Installation

```bash
# 1. Clone
git clone https://github.com/rctruta/sql-benchmarks-dagster.git
cd sql-benchmarks-dagster

# 2. Install (Virtual Env)
pip install -e ".[dev]"

# 3. Verify Integrity (Runs the Test Suite)
pytest sql_benchmarks_tests/
```

### Running an Experiment

```bash
# 1. Start the UI
dagster dev

# 2. Open localhost:3000
# 3. Click "Materialize All" on the 'baseline' job.
```

To run a specific configuration, edit `experiments/active.yaml` and reload.

-----

## 5\. Directory Structure

```text
/sql_benchmarks
├── /assets                 # The Orchestration Layer
│   ├── benchmark_factory.py     # Generates query tests
│   ├── ingestion_factory.py     # Generates data loaders
│   └── reporting.py             # Generates HTML dashboards
├── /resources              # The Infrastructure Layer
│   ├── postgres.py              # Docker control & stream loading
│   └── duckdb.py                # In-process OLAP
├── /utils                  # The Logic Layer (Pure Python)
│   ├── common.py                # Config parsing & Math
│   ├── hasher.py                # AST-based Semantic Hashing
│   └── system.py                # OS Memory Primitives (Safe RAM flushing)
└── /experiments            # The Data Contracts
    ├── active.yaml              # Current Run
    ├── /archive                 # Historical benchmarks
    └── /results                 # Structured outputs
```

-----

## 6\. Future Roadmap

  * **Graph Database Support:** Adapting the "Cold Start" Docker pattern to benchmark SPARQL engines (Virtuoso/Blazegraph).
  * **Cloud Simulation:** Adding `network_latency` delays to `postgres.py` to simulate AWS RDS vs local NVMe.

-----

**Built with:** [Dagster](https://dagster.io) | [Polars](https://pola.rs) | [Docker](https://www.docker.com/) | [Postgres](https://www.postgresql.org/)

-----

### Action Items for You:

1.  **Rename your YAMLs:** Make them look professional. `experiment_skew_test.yaml` $\rightarrow$ `skew_test.yaml`.
2.  **Move them:** Create `experiments/archive/` and move the old ones there so the root stays clean.
3.  **Screenshot the DAG:** Take a picture of the Dagster graph (the big spiderweb of nodes) and put it in the "Architecture" section. It visually proves the "Partition Matrix" concept.

You are done. This is a repository you can pin to your profile for years.