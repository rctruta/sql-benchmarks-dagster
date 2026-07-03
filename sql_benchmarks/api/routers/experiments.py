import os

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...capsule_registry import check_registry
from ...constants import CONFIG_ARCHIVE_DIR, EXPERIMENTS_DIR, ROOT_DIR
from ...coordinator import ExperimentCoordinator
from ...utils.hasher import generate_experiment_hash
from ...validator import ExperimentValidator
from ..data.reader import ResultReader
from ..models.experiments import ExperimentStatus, ExperimentSubmitRequest, ExperimentSubmitResponse

router = APIRouter(prefix="/v1/experiments", tags=["experiments"])
_reader = ResultReader()


def _run_experiment(yaml_path: str):
    coordinator = ExperimentCoordinator(yaml_path, headless=True)
    coordinator.run()


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
        ExperimentValidator.validate(config, source_label="api_submission")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    exp_id = generate_experiment_hash(config, ROOT_DIR)

    registry_status = check_registry(exp_id, config, CONFIG_ARCHIVE_DIR)
    if registry_status == "duplicate":
        return ExperimentSubmitResponse(
            experiment_id=exp_id,
            status="duplicate",
            detail="Results already exist for this experiment. Retrieve them at /v1/results/{exp_id}",
        )
    if registry_status == "collision":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Hash collision: experiment_id {exp_id!r} is already held by a "
                "different config in the registry. This is a genuine 32-bit "
                "SHA-256 prefix collision; the submitted YAML does NOT match the "
                "archived one and must be rejected to avoid returning wrong results. "
                "See TODO.md #5 for the long-term ID-widening options."
            ),
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

    if _reader.is_complete(exp_id):
        status = "complete"
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
    )
