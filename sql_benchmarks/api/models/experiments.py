from pydantic import BaseModel
from typing import Optional


class ExperimentSubmitRequest(BaseModel):
    config_yaml: str


class ExperimentSubmitResponse(BaseModel):
    experiment_id: str
    status: str  # "queued" | "duplicate" | "rejected"
    detail: Optional[str] = None


class ExperimentStatus(BaseModel):
    experiment_id: str
    status: str  # "queued" | "running" | "complete" | "failed" | "not_found"
    has_results: bool
    fragment_count: int
    has_csv: bool
    # Populated only when status == "failed". Format: "[<stage>] <error>".
    # Stages emitted by the coordinator: execution, drift, no_results,
    # coordinator_exception. See sql_benchmarks/failure_marker.py.
    detail: Optional[str] = None
