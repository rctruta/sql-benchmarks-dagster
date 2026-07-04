from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..data.reader import ResultReader
from ..logic.comparator import compare_experiment, compare_experiment_by_partition
from ..logic.projections import (
    get_experiment_summary,
    get_means_by_partition,
    get_replication_stability,
    get_scaling_factor,
)
from ..models.results import (
    CompareByPartitionResult,
    CompareResult,
    ExperimentResult,
    ResultsListResponse,
)

router = APIRouter(prefix="/v1/results", tags=["results"])
_reader = ResultReader()


@router.get("", response_model=ResultsListResponse)
def list_results(
    suite: Optional[str] = Query(None, description="Filter by test suite name"),
    engine: Optional[str] = Query(None, description="Filter by engine name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List completed benchmark experiments, optionally filtered by suite or engine."""
    summaries = _reader.filter_experiments(suite=suite, engine=engine)
    summaries.sort(key=lambda s: s.created_at or 0, reverse=True)
    page = summaries[offset: offset + limit]
    return ResultsListResponse(experiments=page, total=len(summaries))


@router.get("/{exp_id}", response_model=ExperimentResult)
def get_result(exp_id: str):
    """Get full benchmark results for a specific experiment ID."""
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    summary = _reader.build_summary(exp_id)
    fragments = _reader.get_fragments(exp_id)
    config = _reader.get_config(exp_id)
    return ExperimentResult(
        experiment_id=exp_id,
        config=config,
        summary=summary,
        fragments=fragments,
    )


@router.get("/{exp_id}/compare", response_model=CompareResult)
def compare_result(
    exp_id: str,
    partition: Optional[str] = Query(None, description="Filter to a specific partition key"),
):
    """Get a ranked cross-engine performance comparison for an experiment.

    Aggregates across all partitions unless `partition` is set. For a
    partition-by-partition breakdown (needed for scaling analysis), use
    `/compare/by-partition` instead — the aggregate view flattens the
    scaling curve.
    """
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return compare_experiment(exp_id, _reader, partition=partition)


@router.get("/{exp_id}/compare/by-partition", response_model=CompareByPartitionResult)
def compare_result_by_partition(exp_id: str):
    """Get per-partition cross-engine rankings — one CompareResult per
    partition key that has fragments. Use for scaling analysis and
    matrix-sweep experiments where the aggregate hides the shape.
    """
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return compare_experiment_by_partition(exp_id, _reader)


# --- Granular projections ---------------------------------------------------
# One projection per endpoint. Small returns with a `provenance` block naming
# the fragments consumed — Fork-B pre-work (see docs/decisions_log.md).


@router.get("/{exp_id}/projections/means")
def projection_means(exp_id: str):
    """Mean duration per (partition, engine). Cheap first read when the
    question is "who's faster on partition X" without needing std/CV."""
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return get_means_by_partition(exp_id, _reader)


@router.get("/{exp_id}/projections/scaling")
def projection_scaling(exp_id: str):
    """Per-engine adjacent + overall scaling ratios across partitions.
    Partitions ordered alphabetically (existing lab convention); the
    `partitions_order` field makes the ordering explicit."""
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return get_scaling_factor(exp_id, _reader)


@router.get("/{exp_id}/projections/stability")
def projection_stability(exp_id: str):
    """Per (partition, engine): std, coefficient of variation, min, max
    over raw per-replication durations. When a fragment predates raw
    capture, sample_count=1 and std=0 signal not-measurable."""
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return get_replication_stability(exp_id, _reader)


@router.get("/{exp_id}/projections/summary")
def projection_summary(exp_id: str):
    """Compact digest: config identity + means + scaling + a prose
    `narrative`. The `format=summary` half of the "raw vs summary" fork
    (docs/decisions_log.md). Prefer this over `/{exp_id}` (raw) when the
    context budget is tight or the question is top-line."""
    if not _reader.results_exist(exp_id):
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
    return get_experiment_summary(exp_id, _reader)
