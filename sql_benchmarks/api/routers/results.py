from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..data.reader import ResultReader
from ..logic.comparator import compare_experiment, compare_experiment_by_partition
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
