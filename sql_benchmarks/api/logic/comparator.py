from typing import Optional

from ..data.reader import ResultReader
from ..logic.ranker import score_engines
from ..models.results import CompareByPartitionResult, CompareResult


def compare_experiment(
    exp_id: str,
    reader: ResultReader,
    partition: Optional[str] = None,
) -> CompareResult:
    fragments = reader.get_fragments(exp_id)
    config = reader.get_config(exp_id)
    suite = config.get("execution", {}).get("test_suite") if config else None

    rankings = score_engines(fragments, partition_filter=partition)

    if not rankings:
        return CompareResult(
            experiment_id=exp_id,
            suite=suite,
            partition=partition,
            rankings=[],
            winner="unknown",
            speedup_vs_slowest=1.0,
        )

    winner = rankings[0]
    slowest = rankings[-1]
    speedup = (
        slowest.mean_duration_seconds / winner.mean_duration_seconds
        if winner.mean_duration_seconds > 0
        else 1.0
    )

    return CompareResult(
        experiment_id=exp_id,
        suite=suite,
        partition=partition,
        rankings=rankings,
        winner=winner.engine,
        speedup_vs_slowest=round(speedup, 2),
    )


def compare_experiment_by_partition(
    exp_id: str,
    reader: ResultReader,
) -> CompareByPartitionResult:
    """One CompareResult per partition. Used by callers that need to see the
    shape of a scaling curve or the per-scale breakdown, not the aggregate.

    Partitions are discovered from the fragments' meta.partition field —
    every partition that has at least one fragment gets its own entry.
    """
    fragments = reader.get_fragments(exp_id)
    config = reader.get_config(exp_id)
    suite = config.get("execution", {}).get("test_suite") if config else None

    partitions = sorted({f.meta.partition for f in fragments if f.meta.partition})

    per_partition = {
        pk: compare_experiment(exp_id, reader, partition=pk)
        for pk in partitions
    }

    return CompareByPartitionResult(
        experiment_id=exp_id,
        suite=suite,
        partitions=per_partition,
    )
