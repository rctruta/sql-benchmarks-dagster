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

___

This is a [Dagster](https://dagster.io/) project scaffolded with [`dagster project scaffold`](https://docs.dagster.io/guides/build/projects/creating-a-new-project).

## Getting started with Dagster

First, install your Dagster code location as a Python package. By using the --editable flag, pip will install your Python package in ["editable mode"](https://pip.pypa.io/en/latest/topics/local-project-installs/#editable-installs) so that as you develop, local code changes will automatically apply.

```bash
pip install -e ".[dev]"
```

Then, start the Dagster UI web server:

```bash
dagster dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the project.

You can start writing assets in `sql_benchmarks/assets.py`. The assets are automatically loaded into the Dagster code location as you define them.

## Development

### Adding new Python dependencies

You can specify new Python dependencies in `setup.py`.

### Unit testing

Tests are in the `sql_benchmarks_tests` directory and you can run tests using `pytest`:

```bash
pytest sql_benchmarks_tests
```

### Schedules and sensors

If you want to enable Dagster [Schedules](https://docs.dagster.io/guides/automate/schedules/) or [Sensors](https://docs.dagster.io/guides/automate/sensors/) for your jobs, the [Dagster Daemon](https://docs.dagster.io/guides/deploy/execution/dagster-daemon) process must be running. This is done automatically when you run `dagster dev`.

Once your Dagster Daemon is running, you can start turning on schedules and sensors for your jobs.

## Deploy on Dagster+

The easiest way to deploy your Dagster project is to use Dagster+.

Check out the [Dagster+ documentation](https://docs.dagster.io/dagster-plus/) to learn more.
