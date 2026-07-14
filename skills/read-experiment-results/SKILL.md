---
name: read-experiment-results
description: Read and analyze completed benchmark experiment results. Use when an experiment status is complete and you need to compare engines, speedups, scaling, replication stability, or raw timings.
---
# Skill: read experiment results — pick the right tool for the question

**Use when:** an experiment's status has gone `complete` and you need to reason from the results.

## Decision table

| Question shape | Tool | Why |
|---|---|---|
| First read of any completed experiment | `python scripts/get_experiment_summary.py` | Compact: config identity + means + scaling ratios + prose narrative. Small payload, safe under tight context budgets. |
| "Who was faster on partition X?" | `python scripts/get_means_by_partition.py` | Just means + sample counts. Cheapest projection when the question is per-partition speed, not ranking. |
| "How does X scale from small to large?" | `python scripts/get_scaling_factor.py` | Returns ratios directly — `adjacent_ratios`, `overall_ratio`. Spares in-context arithmetic (which small models get wrong). |
| "Can I trust these numbers? / how noisy?" | `python scripts/get_replication_stability.py` | std, coefficient of variation, min, max over raw per-replication durations. If `sample_count=1` and `std=0`, the fragment predates raw capture — stability not measurable. |
| "Who won overall (across all partitions)?" | `python scripts/compare_engines.py` | Ranked, aggregated across partitions. Flattens the scaling curve — don't use for scaling questions. |
| "Per-partition ranking with speedups" | `python scripts/compare_engines_by_partition.py` | One ranking per partition. Use when you need speedup ratios AND the per-partition breakdown. |
| "I need every fragment's raw numbers" | `python scripts/get_experiment_result.py` | The full payload. Use ONLY if the projections above don't answer the question. Can be many KB of JSON. |

## Ordering caveat for `get_scaling_factor`

Partitions are sorted **alphabetically**, not semantically. `["small", "medium", "large"]` becomes `["large", "medium", "small"]`. The response includes `partitions_order` — check it and reinterpret if the semantic direction is reversed. `overall_ratio < 1` means partitions get *faster* along the alpha order.

## Provenance

Every projection returns a `provenance` block:

```json
"provenance": {
  "fragment_keys": ["duckdb_analytical__large", "duckdb_analytical__medium", ...],
  "fragment_count": 6,
  "computed_at": "2026-07-04T..."
}
```

These are the specific fragments consumed. In your final answer, when you cite a derived number, you can point at the fragments it came from.

## Recipe

1. `python scripts/get_experiment_summary.py <exp_id>` — always the first read. Gives you engines, partitions, means, scaling, and a narrative in one small payload.
2. Question calls for a specific projection? Fetch it by name from the table above.
3. Question calls for raw fragments? Only then reach for `python scripts/get_experiment_result.py <exp_id>`.
4. Produce a final Markdown analysis with `FINAL ANSWER:` at the top, citing the numbers and their provenance.
