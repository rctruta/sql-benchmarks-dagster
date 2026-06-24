# Known Issues

Open integrity gaps found in the lab, recorded so they are not silently relied
upon. An entry stays here until it is fixed (with a test that would have caught
it) or consciously closed as won't-fix.

---

## 1. The "semantic firewall" does not currently audit anything

**Status:** open
**Found:** 2026-06-24, while verifying whether datagen output is checked against config.
**Severity:** high — the gate is presented as a correctness guard but is, in its
current state, decorative.

### What it claims to do
`assets/semantic_gate.py` is wired into `definitions.py` and described as auditing
benchmark results "for hallucinations." It depends on each benchmark asset and is
meant to flag results that violate expected semantics.

### What it actually does
Three independent reasons it does not function as a guard today:

1. **Wrong fragment path.** The gate reads
   `RESULTS_DIR/fragments/<name>__<pk>.json`, but benchmarks write to
   `RESULTS_DIR/<experiment_id>/fragments/<name>__<pk>.json`
   (`assets/benchmark_factory.py`). The `experiment_id` segment is missing, so
   the gate looks in a path that holds only **stale fragments from a legacy run
   (`e_3395f19b`)**. For any current experiment it finds nothing and returns
   `missing_fragment` without auditing.

2. **It never fails.** On a detected violation the gate only attaches metadata —
   the code says so verbatim: *"For this PoC, we add metadata."* A violation does
   not raise, tag high-severity, or stop the pipeline.

3. **It checks almost nothing.** `utils/semantic_auditor.py`'s `OntologyRegistry`
   is an explicit *"Placeholder for Proof-of-Concept"* asserting only
   `total_count >= 0`, `avg_value >= 0`, and `duration_seconds >= 0`. No result
   row counts, no cardinality, no relationship to the generated data.

### Impact
Any prior statement that the lab enforces "hard row-count / correctness
assertions" via a semantic firewall is **not** backed by the code. Capsules
produced to date were not audited by this gate.

### Suggested fix (separate from the datagen-contract work)
- Correct the fragment path to include `experiment_id`.
- Decide the policy: raise on violation (fail-fast) vs. record-and-flag.
- Replace the placeholder `OntologyRegistry` with real, per-experiment expected
  invariants (e.g. result row count for a known-selectivity query), or remove
  the gate until it does something, so it cannot be mistaken for a guarantee.

---

## What WAS fixed alongside this finding

The **datagen↔reality contract** (`utils/datagen_contract.py`) now verifies that
generated data matches what the config declared, and fails loudly when it does
not:

- **Staging contract** (`assets/data_quality.py`): observed polars dtype and null
  rate per column vs. the declared provider / `null_probability`. Raises on drift.
- **Loaded-schema contract** (`resources/postgres_client.py`): every column with
  a `type:` override (e.g. `jsonb`, `integer[]`) is checked against the **live
  Postgres `information_schema`** at load time. Raises if the override did not
  land. This closes the specific gap where a column declared `type: jsonb` could
  have silently been stored as text while `data_stats` (which profiles the
  staging frame) only ever reported `String`.

Tests: `sql_benchmarks_tests/test_datagen_contract.py`.
