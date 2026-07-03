"""Write and read experiment failure markers.

When a run fails after an experiment_id has been assigned, the coordinator
writes `results/<id>/failure.json` so `/v1/experiments/<id>/status` can return
`status="failed"` with a detail string instead of hanging on `queued` while
the executor's crash goes unobserved (the concrete bug TODO #2 records).

Atomic write (tmp + rename) so a concurrent status poll never reads a half-file.

Schema:
    {
      "experiment_id": "<id>",
      "stage": "execution" | "drift" | "no_results" | "coordinator_exception",
      "error": "<one-line summary>",
      "timestamp": <epoch seconds>,
      "traceback": "<optional multi-line traceback>"
    }
"""
import json
import os
import time
from typing import Optional

FAILURE_MARKER_FILENAME = "failure.json"


def marker_path(results_dir: str, exp_id: str) -> str:
    return os.path.join(results_dir, exp_id, FAILURE_MARKER_FILENAME)


def write_failure_marker(
    results_dir: str,
    exp_id: str,
    stage: str,
    error: str,
    traceback_text: Optional[str] = None,
) -> None:
    exp_dir = os.path.join(results_dir, exp_id)
    os.makedirs(exp_dir, exist_ok=True)
    payload = {
        "experiment_id": exp_id,
        "stage": stage,
        "error": error,
        "timestamp": time.time(),
    }
    if traceback_text:
        payload["traceback"] = traceback_text

    final = os.path.join(exp_dir, FAILURE_MARKER_FILENAME)
    tmp = final + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.rename(tmp, final)


def read_failure_marker(results_dir: str, exp_id: str) -> Optional[dict]:
    path = marker_path(results_dir, exp_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def has_failure(results_dir: str, exp_id: str) -> bool:
    return os.path.exists(marker_path(results_dir, exp_id))
