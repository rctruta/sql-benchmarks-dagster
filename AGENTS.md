# Agentic Benchmarking Protocol

> **Specification for AI Agents and Orchestrators to interact with the SQL Laboratory.**

The SQL Benchmarking Lab is designed not just for humans, but as a **Deterministic Performance Oracle** for Agentic AI workflows. It exposes a "Filesystem API" that allows an LLM or autonomous coder to verify optimization hypotheses without manual effort.

---

## The Agentic Loop

1.  **Hypothesis**: An Agent proposes a code change or a configuration (e.g., "Increasing NULL density will cause a performance cliff").
2.  **Request Submisson**: The Agent generates a YAML configuration and writes it to `sql_benchmarks/experiments/queue/`.
3.  **Harness Execution**: The Agent triggers the run via CLI: `./run.sh experiments/queue/my_exp.yaml --auto`.
4.  **Deterministic ID (Experiment ID)**: The system returns a unique 8-character ID based on the logic hash. 
5.  **Result Retrieval**: The Agent monitors `sql_benchmarks/experiments/results/<ID>/` and parses the consolidated CSV or JSON fragments.

---

## Key Features for Agents

### 1. Context-Addressable Addressing
Every result is addressed by its **Experiment ID** (Hash of YAML + SQL + Python). 
*   **Avoid Redundancy**: If two different agents (or two turns of the same agent) ask the same question, they will generate the same ID. The Agent can check if `results/<ID>` already exists to perform a **Zero-Cost Cache Lookup**.
*   **Verification**: The ID serves as an "immutable receipt" of what was actually tested.

### 2. Failure as a Feedback Loop
If a benchmark fails or times out, the system produces a **Failure Capsule** (Config + partial Logs).
*   Agents can ingest these logs to perform **Root Cause Analysis** (e.g., OOM on Postgres) and adjust the YAML parameters (e.g., reducing partition size) for the next iteration.

### 3. Structural Consistency
Agents thrive on structure. The platform provides:
*   **Strict YAML Schema**: Predictable parameterization.
*   **Flat CSV Matrix**: One row per partition combination, ideal for `pandas` or `polars` analysis within an Agent's sandbox.
*   **JSON Primitives**: Machine-readable timing data with microsecond precision.

---

## Future: Embedding into Agent Loops

Example usage in a coding assistant (like Antigravity):
```python
# Pseudo-code for an Agentic Benchmark Tool
def benchmark_hypothesis(sql_path, rows=100000):
   exp_yaml = generate_yaml(sql_path, rows)
   exp_id = run_cli(exp_yaml)
   results = parse_results(f"results/{exp_id}/results_{exp_id}.csv")
   return results.duration.mean()
```

By using this lab, Agents move from "writing scripts that might work" to "validating technical claims against a ground-truth harness."
