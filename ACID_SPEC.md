# ACID Staging & Integrity Specification

## Overview
This document specifies the **Isolated Clean Room** architecture of the SQL Benchmarking Laboratory. This design ensures that every benchmark execution is an **Atomic Transaction**, protected against "Semantic Injection" (the Blueberry Muffin exploit) and TOCTOU (Time-of-Check to Time-of-Use) vulnerabilities.

## 1. The Isolation Protocol (ACID)

### **A - Atomicity**
Experiments no longer run from the live repository. At execution starts, a **Genesis Snapshot** is taken into a `tempfile.TemporaryDirectory()`. This snapshot includes:
*   The entire `sql_benchmarks/` logic package.
*   The `execute_run.py` entry point.
*   The specific SQL scenario assets required by the configuration.

### **C - Consistency**
The system uses an **Integrity Monitor** (`sql_benchmarks/utils/integrity_monitor.py`) to take a cryptographic fingerprint of the staging area *before* execution starts. 

### **I - Isolation**
The benchmark runs with `cwd` and `PYTHONPATH` restricted to the staging directory. It is impossible for a process modifying the root repository to affect the isolated execution once it has started.

### **D - Durability (Atomic Commit)**
Results are not written to the repository until the run is complete. 
1.  Execution produces `results/` in the staging zone.
2.  The **Integrity Seal** (`hasher.generate_integrity_seal`) is generated against the isolated results.
3.  The `IntegrityMonitor` re-scans for **Semantic Drift**. If any codebase files in staging were modified during the run, the commit is aborted.
4.  Successful, verified capsules are moved to the permanent `results/` registry.

---

## 2. Verification Evidence

### **Scenario: ACID Resilience Suite**
*   **Goal**: Prove structural integrity between Harness and Scenario via manual infection.
*   **Status**: VERIFIED.
*   **Proof Folder**: `sql_benchmarks/experiments/security/acid_resilience.yaml`
*   **Last Verified Seal**: `cfc5ea31` (Atomic Isolation Verified).

---

## 3. Self-Defense Demo (Run it Yourself)
Run the following to verify the architectural guarantees:
```bash
# 1. Start the long-running resilience demo
python3 run_experiment.py sql_benchmarks/experiments/security/acid_resilience.yaml --auto

# 2. WHILE IT IS RUNNING: 
# Modify ANY file in /sql_benchmarks (e.g. add a comment to a resource).

# 3. VERIFY:
# The run completes succesfully (Isolation Proof)
# The final log flags an [ACID VIOLATION] with SHA-256 hashes (Integrity Proof)
```
