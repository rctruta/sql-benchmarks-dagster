"""Granular projections over a completed experiment's fragments.

Each projection returns:
  - a small derived value (means, scaling factors, stability metrics, or
    a compact prose summary),
  - a `provenance` block naming the fragments consumed (fragment_keys,
    fragment_count, computed_at) — for eventual sealing (Fork B; see
    `docs/decisions_log.md`).

Same function backs three surfaces:
  - Python import: `from sql_benchmarks.api.logic.projections import ...`
  - REST endpoint: `sql_benchmarks/api/routers/results.py` (thin wrapper)
  - CLI: `sqlbench project <projection> <exp_id>` (thin wrapper)

Human-and-agent parity: whoever needs the projection gets it from the
surface most natural to them, hitting the same code path.
"""
from datetime import datetime, timezone
from statistics import mean, stdev
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fragment_key(f) -> str:
    """`<asset>__<partition>` — matches the on-disk filename convention."""
    return f"{f.meta.asset}__{f.meta.partition}"


def _provenance(fragments) -> dict:
    """The `(fragment set, computed_at)` tuple every projection returns.

    Fork B pre-work: when the analysis becomes sealed alongside the
    measurement capsule, this block IS the provenance receipt — the exact
    set of fragments that produced the derived value, plus when the
    derivation ran."""
    return {
        "fragment_keys": sorted(_fragment_key(f) for f in fragments),
        "fragment_count": len(fragments),
        "computed_at": _now_iso(),
    }


def get_means_by_partition(exp_id: str, reader) -> dict:
    """Mean duration per (partition, engine). The natural first read for
    any comparison question that doesn't need std/CV. Small return."""
    fragments = reader.get_fragments(exp_id)
    grouped: dict[str, dict[str, list]] = {}
    for f in fragments:
        grouped.setdefault(f.meta.partition, {}).setdefault(f.meta.engine, []).append(
            f.metrics.duration_seconds
        )
    partitions_out: dict[str, dict[str, dict]] = {}
    for part in sorted(grouped.keys()):
        partitions_out[part] = {}
        for eng in sorted(grouped[part].keys()):
            durations = grouped[part][eng]
            partitions_out[part][eng] = {
                "mean_duration_seconds": round(mean(durations), 6),
                "sample_count": len(durations),
            }
    return {
        "experiment_id": exp_id,
        "partitions": partitions_out,
        "provenance": _provenance(fragments),
    }


def get_scaling_factor(exp_id: str, reader) -> dict:
    """For each engine, pairwise scaling factors across partitions.

    Partitions are sorted alphabetically — the existing lab convention
    (matches `compare_experiment_by_partition`). The `partitions_order`
    field is returned explicitly so the caller can spot a
    wrong-direction ordering (e.g. "large","medium","small" vs the
    semantic small→medium→large) and reinterpret at analysis time.

    Per engine, returns:
      - `partitions_order`: the ordering used
      - `mean_durations`: means in that order
      - `adjacent_ratios`: [mean_i+1 / mean_i, ...]
      - `overall_ratio`: mean_last / mean_first
    """
    fragments = reader.get_fragments(exp_id)
    grouped: dict[str, dict[str, list]] = {}
    for f in fragments:
        grouped.setdefault(f.meta.engine, {}).setdefault(f.meta.partition, []).append(
            f.metrics.duration_seconds
        )
    all_partitions = sorted({f.meta.partition for f in fragments if f.meta.partition})

    engines_out: dict[str, dict] = {}
    for eng in sorted(grouped.keys()):
        parts_present = [p for p in all_partitions if p in grouped[eng]]
        means = [mean(grouped[eng][p]) for p in parts_present]
        adjacent: list = []
        for i in range(1, len(means)):
            if means[i - 1] > 0:
                adjacent.append(round(means[i] / means[i - 1], 4))
            else:
                adjacent.append(None)
        overall: float | None = None
        if len(means) >= 2 and means[0] > 0:
            overall = round(means[-1] / means[0], 4)
        engines_out[eng] = {
            "partitions_order": parts_present,
            "mean_durations": [round(m, 6) for m in means],
            "adjacent_ratios": adjacent,
            "overall_ratio": overall,
        }
    return {
        "experiment_id": exp_id,
        "note": (
            "Partitions ordered alphabetically — the existing lab convention. "
            "If your semantic ordering differs (e.g. small→medium→large), "
            "reorder at analysis time."
        ),
        "engines": engines_out,
        "provenance": _provenance(fragments),
    }


def get_replication_stability(exp_id: str, reader) -> dict:
    """Per (partition, engine): std, coefficient of variation, min, max
    across the raw per-replication durations.

    Uses `metrics.durations_raw` when present (post-#PR fragments);
    falls back to `[metrics.duration_seconds]` for older fragments that
    didn't capture the per-replication list. In the fallback case
    `sample_count == 1` and `std == 0` — a signal to the caller that
    this fragment's stability is not measurable from what was stored."""
    fragments = reader.get_fragments(exp_id)
    grouped: dict[str, dict[str, list]] = {}
    for f in fragments:
        raw = f.metrics.durations_raw or [f.metrics.duration_seconds]
        grouped.setdefault(f.meta.partition, {}).setdefault(f.meta.engine, []).extend(raw)

    partitions_out: dict[str, dict[str, dict]] = {}
    for part in sorted(grouped.keys()):
        partitions_out[part] = {}
        for eng in sorted(grouped[part].keys()):
            raw = grouped[part][eng]
            m = mean(raw)
            s = stdev(raw) if len(raw) >= 2 else 0.0
            cv = (s / m) if m > 0 else None
            partitions_out[part][eng] = {
                "mean_duration_seconds": round(m, 6),
                "std_duration_seconds": round(s, 6),
                "coefficient_of_variation": (round(cv, 4) if cv is not None else None),
                "min_duration_seconds": round(min(raw), 6),
                "max_duration_seconds": round(max(raw), 6),
                "sample_count": len(raw),
            }
    return {
        "experiment_id": exp_id,
        "partitions": partitions_out,
        "provenance": _provenance(fragments),
    }


def get_experiment_summary(exp_id: str, reader) -> dict:
    """A compact digest — the `format=summary` half of the "raw vs
    summary" fork named in `docs/decisions_log.md`.

    Combines means (from `get_means_by_partition`) and scaling ratios
    (from `get_scaling_factor`) into a single small payload plus a
    prose `narrative` field. Machine-readable *and* readable.

    The caller trades granularity for a small return: everything they
    need for a top-line comparison, none of the raw fragments."""
    fragments = reader.get_fragments(exp_id)
    config = reader.get_config(exp_id) or {}
    exec_block = config.get("execution") or {}
    suite = exec_block.get("test_suite")

    engines = sorted({f.meta.engine for f in fragments})
    partitions = sorted({f.meta.partition for f in fragments if f.meta.partition})

    means = get_means_by_partition(exp_id, reader)
    scaling = get_scaling_factor(exp_id, reader)

    lines: list[str] = [
        f"Experiment {exp_id} — suite={suite or 'unknown'}, "
        f"engines={engines}, partitions={partitions}."
    ]
    for eng in engines:
        eng_means = [
            (p, means["partitions"][p][eng]["mean_duration_seconds"])
            for p in partitions
            if eng in means["partitions"].get(p, {})
        ]
        if eng_means:
            lines.append(
                f"  {eng}: "
                + ", ".join(f"{p}={m * 1000:.2f}ms" for p, m in eng_means)
            )
        eng_scaling = scaling["engines"].get(eng, {})
        if eng_scaling.get("overall_ratio") is not None:
            po = eng_scaling.get("partitions_order") or []
            if len(po) >= 2:
                lines.append(
                    f"    scaling {po[0]}→{po[-1]}: {eng_scaling['overall_ratio']}×"
                )

    return {
        "experiment_id": exp_id,
        "suite": suite,
        "engines": engines,
        "partitions": partitions,
        "means": means["partitions"],
        "scaling": scaling["engines"],
        "narrative": "\n".join(lines),
        "provenance": _provenance(fragments),
    }


def get_means_by_benchmark(exp_id: str, reader) -> dict:
    """Mean duration per (benchmark, partition, engine) — the disaggregated
    view. Suites that encode the OBJECT of comparison as the benchmark
    (null_logic: 3VL vs hand-decomposed 2VL vs IS NOT DISTINCT FROM;
    selectivity: q_0_1_percent vs q_10_percent) are invisible to the
    partition-pooled projections — a reference-librarian run refused a
    paper-prep question for exactly this reason (2026-07-06). Additive:
    the pooled projections keep their shape."""
    fragments = reader.get_fragments(exp_id)
    grouped: dict = {}
    for f in fragments:
        raw = f.metrics.durations_raw or [f.metrics.duration_seconds]
        key = (f.meta.asset, f.meta.partition, f.meta.engine)
        grouped.setdefault(key, []).extend(raw)
    benchmarks: dict = {}
    for (asset, part, eng), raws in sorted(grouped.items()):
        m = mean(raws)
        s = stdev(raws) if len(raws) >= 2 else 0.0
        benchmarks.setdefault(asset, {}).setdefault(part, {})[eng] = {
            "mean_duration_seconds": round(m, 6),
            "std_duration_seconds": round(s, 6),
            "sample_count": len(raws),
        }
    return {
        "experiment_id": exp_id,
        "benchmarks": benchmarks,
        "provenance": _provenance(fragments),
    }
