"""Tests for the running-marker module.

Load-bearing contract:
  - `/status` returns `running` (not `queued`) once the coordinator has
    picked up a queue entry and started execution. This closes the window
    where agents polled `queued` for minutes and re-submitted, opening a
    race in check_registry that spawned duplicate concurrent runs.
  - A running marker gets cleared on successful completion.
  - The marker is written atomically (no torn read on concurrent poll).
"""
import json
import os

import pytest

from sql_benchmarks.running_marker import (
    RUNNING_MARKER_FILENAME,
    clear_running_marker,
    has_running_marker,
    marker_path,
    read_running_marker,
    write_running_marker,
)


def test_no_marker_yields_none_and_false(tmp_path):
    assert read_running_marker(str(tmp_path), "abc12345") is None
    assert has_running_marker(str(tmp_path), "abc12345") is False


def test_marker_path_is_deterministic(tmp_path):
    p = marker_path(str(tmp_path), "abc12345")
    assert p == os.path.join(str(tmp_path), "abc12345", RUNNING_MARKER_FILENAME)


def test_write_creates_marker_with_expected_payload(tmp_path):
    write_running_marker(str(tmp_path), "abc12345")
    assert has_running_marker(str(tmp_path), "abc12345")

    payload = read_running_marker(str(tmp_path), "abc12345")
    assert payload["experiment_id"] == "abc12345"
    assert isinstance(payload["started_at"], float)
    assert isinstance(payload["pid"], int)
    assert isinstance(payload["hostname"], str)


def test_write_is_atomic_no_tmp_left_behind(tmp_path):
    """We can't easily simulate a torn write in a unit test, but we can
    verify the tmp file is renamed away — so a concurrent status poll sees
    either the old state or the complete new one, never a partial file."""
    write_running_marker(str(tmp_path), "abc12345")
    exp_dir = os.path.join(str(tmp_path), "abc12345")
    files = os.listdir(exp_dir)
    assert RUNNING_MARKER_FILENAME in files
    assert not any(name.endswith(".tmp") for name in files)


def test_clear_removes_marker(tmp_path):
    write_running_marker(str(tmp_path), "abc12345")
    assert has_running_marker(str(tmp_path), "abc12345")
    clear_running_marker(str(tmp_path), "abc12345")
    assert not has_running_marker(str(tmp_path), "abc12345")


def test_clear_missing_marker_is_noop(tmp_path):
    """Coordinator calls clear_running_marker unconditionally in a finally
    block. Missing marker (e.g., write failed earlier) must not raise."""
    clear_running_marker(str(tmp_path), "abc12345")
    assert not has_running_marker(str(tmp_path), "abc12345")


def test_read_returns_none_on_malformed_json(tmp_path):
    """A corrupt marker (partial write from an old crash) must not crash
    the /status endpoint. Mirror of failure_marker.py's semantics."""
    exp_dir = os.path.join(str(tmp_path), "abc12345")
    os.makedirs(exp_dir)
    with open(os.path.join(exp_dir, RUNNING_MARKER_FILENAME), "w") as f:
        f.write("{not valid json")
    assert read_running_marker(str(tmp_path), "abc12345") is None


def test_write_overwrites_existing(tmp_path):
    """Same exp_id re-picked-up by the coordinator (e.g., after a restart)
    should overwrite, not error. Latest write wins."""
    write_running_marker(str(tmp_path), "abc12345")
    first = read_running_marker(str(tmp_path), "abc12345")
    import time
    time.sleep(0.01)  # ensure timestamp differs
    write_running_marker(str(tmp_path), "abc12345")
    second = read_running_marker(str(tmp_path), "abc12345")
    assert second["started_at"] >= first["started_at"]
