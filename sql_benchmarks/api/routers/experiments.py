import os

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...constants import CONFIG_ARCHIVE_DIR, EXPERIMENTS_DIR, ROOT_DIR
from ...coordinator import ExperimentCoordinator
from ...utils.hasher import generate_experiment_hash
from ...validation import validate_experiment_config
from ..data.reader import ResultReader
from ..models.experiments import ExperimentStatus, ExperimentSubmitRequest, ExperimentSubmitResponse

router = APIRouter(prefix="/v1/experiments", tags=["experiments"])
_reader = ResultReader()


def _run_experiment(yaml_path: str):
    """FastAPI BackgroundTask entry point.

    Wraps the coordinator so any exception the coordinator's own failure-marker
    hooks didn't already record still surfaces to /status as `status="failed"`.
    Without this, the FastAPI background task would swallow the exception and
    the poller would sit on `queued` forever (the original TODO #2 symptom)."""
    import traceback as _tb
    from ...constants import RESULTS_DIR
    from ...failure_marker import write_failure_marker, has_failure

    coordinator = ExperimentCoordinator(yaml_path, headless=True)
    try:
        coordinator.run()
    except Exception as e:
        exp_id = getattr(coordinator, "exp_id", None)
        if exp_id and not has_failure(RESULTS_DIR, exp_id):
            write_failure_marker(
                RESULTS_DIR, exp_id, "coordinator_exception",
                f"{type(e).__name__}: {e}", _tb.format_exc(),
            )


@router.post("", response_model=ExperimentSubmitResponse, status_code=202)
def submit_experiment(body: ExperimentSubmitRequest, background_tasks: BackgroundTasks):
    """
    Submit a new benchmark experiment as a YAML config string.
    Returns immediately with the experiment ID. Use /status to poll progress.
    """
    try:
        config = yaml.safe_load(body.config_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {e}")

    try:
        validate_experiment_config(config, source_label="api_submission")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    exp_id = generate_experiment_hash(config, ROOT_DIR)

    if os.path.exists(os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_id}.yaml")):
        return ExperimentSubmitResponse(
            experiment_id=exp_id,
            status="duplicate",
            detail="Results already exist for this experiment. Retrieve them at /v1/results/{exp_id}",
        )

    queue_dir = os.path.join(EXPERIMENTS_DIR, "queue")
    os.makedirs(queue_dir, exist_ok=True)
    yaml_path = os.path.join(queue_dir, f"{exp_id}.yaml")
    with open(yaml_path, "w") as f:
        yaml.dump(config, f, sort_keys=False)

    background_tasks.add_task(_run_experiment, yaml_path)

    return ExperimentSubmitResponse(experiment_id=exp_id, status="queued")


@router.get("/{exp_id}/status", response_model=ExperimentStatus)
def get_status(exp_id: str):
    """Check the status of a submitted experiment."""
    fragments = _reader.get_fragments(exp_id)
    has_csv = _reader.has_csv(exp_id)

    detail = None
    # Priority: complete > failed > running > queued > not_found.
    # "failed" comes before "running" because a run that produced partial
    # fragments and then died would satisfy both results_exist() and has_failure();
    # the failure marker is the authoritative terminal state.
    if _reader.is_complete(exp_id):
        status = "complete"
    elif _reader.has_failure(exp_id):
        status = "failed"
        failure = _reader.get_failure(exp_id)
        if failure:
            detail = f"[{failure.get('stage', 'unknown')}] {failure.get('error', '')}".strip()
    elif _reader.results_exist(exp_id):
        status = "running"
    elif _reader.is_queued(exp_id):
        status = "queued"
    else:
        status = "not_found"

    return ExperimentStatus(
        experiment_id=exp_id,
        status=status,
        has_results=_reader.results_exist(exp_id),
        fragment_count=len(fragments),
        has_csv=has_csv,
        detail=detail,
    )
