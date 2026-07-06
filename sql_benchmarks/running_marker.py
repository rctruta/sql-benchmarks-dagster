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


# A run older than this is presumed dead regardless of PID state — also
# bounds the PID-reuse false-alive window. Generous: real experiments run
# minutes to ~an hour.
MAX_MARKER_AGE_SECONDS = 6 * 3600


def _pid_alive(pid) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except (OverflowError, ValueError, TypeError):
        return False  # garbage pid in the marker


def has_running_marker(results_dir: str, exp_id: str,
                       max_age_seconds: float = MAX_MARKER_AGE_SECONDS) -> bool:
    """True only if the marker exists AND the run it describes is plausibly
    alive. A crashed executor (killed API process, torn-down session) leaves
    an orphaned marker that would otherwise block resubmission of the same
    config forever — observed live 2026-07-06 (capsule 209fc5df: session
    teardown killed the API mid-execution; the stale marker had to be
    removed by hand). See TODO.md #12.

    Staleness rules, in order:
      - unreadable/corrupt marker            -> stale
      - older than max_age_seconds           -> stale (any host; also caps
                                                the PID-reuse window)
      - same host and recorded PID not alive -> stale
      - different host, within age           -> assumed alive (can't probe)

    Stale markers are REMOVED (self-heal) with a loud warning, so the
    status endpoint and check_registry recover without operator surgery."""
    payload = read_running_marker(results_dir, exp_id)
    if payload is None:
        # Missing entirely, or unreadable. If the file exists but can't be
        # parsed, it can't testify that anything is running — remove it.
        if os.path.exists(marker_path(results_dir, exp_id)):
            print(f"[WARN] corrupt running marker for {exp_id} — removing (stale)")
            clear_running_marker(results_dir, exp_id)
        return False

    age = time.time() - float(payload.get("started_at") or 0)
    if age > max_age_seconds:
        print(f"[WARN] running marker for {exp_id} is {age/3600:.1f}h old "
              f"(max {max_age_seconds/3600:.1f}h) — presumed dead, removing")
        clear_running_marker(results_dir, exp_id)
        return False

    if payload.get("hostname") == socket.gethostname():
        pid = payload.get("pid")
        if not _pid_alive(pid):
            print(f"[WARN] running marker for {exp_id} names dead pid {pid} — "
                  "executor crashed; removing stale marker")
            clear_running_marker(results_dir, exp_id)
            return False

    return True


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
