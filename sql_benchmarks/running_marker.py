"""Write and read experiment running markers.

Mirror of `sql_benchmarks/failure_marker.py`, but for the OTHER end of the
lifecycle: the coordinator writes `results/<id>/running.json` the moment it
picks up a queue entry and starts execution, and deletes it at successful
finalization. Without this marker, `/v1/experiments/<id>/status` had no way
to distinguish `queued but not started` from `running now` — both showed as
`queued` because `results_exist` was gated on the FINAL results dir move
that only happens at completion. Agents polling `queued` for minutes
concluded the run had stalled and re-submitted, opening a race window in
`check_registry` (the config archive didn't exist yet, so the resubmission
was treated as `fresh` and started a SECOND concurrent run of the same
experiment).

With this marker: the status endpoint sees `running` within seconds of the
subprocess starting; `check_registry` treats a running marker as
`duplicate` (same experiment, already in flight) and refuses the
re-submission with a helpful message.

Atomic write (tmp + rename), same as the failure marker.

Schema:
    {
      "experiment_id": "<id>",
      "started_at": <epoch seconds>,
      "pid": <coordinator process pid>,
      "hostname": "<gethostname>"
    }
"""
import json
import os
import socket
import time
from typing import Optional

RUNNING_MARKER_FILENAME = "running.json"


def marker_path(results_dir: str, exp_id: str) -> str:
    return os.path.join(results_dir, exp_id, RUNNING_MARKER_FILENAME)


def write_running_marker(results_dir: str, exp_id: str) -> None:
    """Called by the coordinator right before it spawns execute_run.py
    subprocesses. Creates results/<id>/ if it doesn't exist."""
    exp_dir = os.path.join(results_dir, exp_id)
    os.makedirs(exp_dir, exist_ok=True)
    payload = {
        "experiment_id": exp_id,
        "started_at": time.time(),
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
    }
    final = os.path.join(exp_dir, RUNNING_MARKER_FILENAME)
    tmp = final + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.rename(tmp, final)


def read_running_marker(results_dir: str, exp_id: str) -> Optional[dict]:
    path = marker_path(results_dir, exp_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def has_running_marker(results_dir: str, exp_id: str) -> bool:
    return os.path.exists(marker_path(results_dir, exp_id))


def clear_running_marker(results_dir: str, exp_id: str) -> None:
    """Called at successful finalization. The marker is transient; once the
    run has produced a config archive (is_complete) or a failure marker,
    the running marker's presence would be misleading."""
    path = marker_path(results_dir, exp_id)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass  # never written, or already cleared — either is fine
    except OSError as e:
        print(f"[WARN] could not clear running marker for {exp_id}: {e}")
