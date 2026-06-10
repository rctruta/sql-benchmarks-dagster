from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class FragmentMeta(BaseModel):
    timestamp: str
    experiment_id: str
    dagster_run_id: str
    engine: str
    asset: str
    partition: str


class FragmentMetrics(BaseModel):
    duration_seconds: float
    replication_factor: int
    # Raw per-replication measurements; None for fragments written before
    # raw capture (or DNF sentinels, which carry an empty list).
    durations_raw: Optional[List[float]] = None


class Fragment(BaseModel):
    meta: FragmentMeta
    metrics: FragmentMetrics
    parameters: Dict[str, Any]


class ExperimentSummary(BaseModel):
    experiment_id: str
    suite: Optional[str] = None
    engines: List[str]
    partition_count: int
    fragment_count: int
    has_csv: bool
    has_dashboard: bool
    created_at: Optional[float] = None  # unix timestamp from metadata


class ExperimentResult(BaseModel):
    experiment_id: str
    config: Optional[Dict[str, Any]] = None
    summary: ExperimentSummary
    fragments: List[Fragment]


class EngineRanking(BaseModel):
    engine: str
    mean_duration_seconds: float
    median_duration_seconds: float
    p95_duration_seconds: float
    sample_count: int
    rank: int


class CompareResult(BaseModel):
    experiment_id: str
    suite: Optional[str] = None
    partition: Optional[str] = None
    rankings: List[EngineRanking]
    winner: str
    speedup_vs_slowest: float


class ResultsListResponse(BaseModel):
    experiments: List[ExperimentSummary]
    total: int
