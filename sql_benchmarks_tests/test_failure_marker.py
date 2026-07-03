"""Tests for the failure_marker module.

Written to make three properties safe to rely on from the API and coordinator:
  1. write is atomic (a concurrent reader never sees a half-file)
  2. read returns None when there is no marker (not-yet-failed vs failed distinct)
  3. the file lives at a stable, computable path so /status can find it
"""
import json
import os

import pytest

from sql_benchmarks.failure_marker import (
    FAILURE_MARKER_FILENAME,
    has_failure,
    marker_path,
    read_failure_marker,
    write_failure_marker,
)


def test_no_marker_yields_none_and_false(tmp_path):
    assert read_failure_marker(str(tmp_path), "abc12345") is None
    assert has_failure(str(tmp_path), "abc12345") is False


def test_marker_path_is_deterministic(tmp_path):
    path = marker_path(str(tmp_path), "abc12345")
    assert path == os.path.join(str(tmp_path), "abc12345", FAILURE_MARKER_FILENAME)


def test_write_creates_marker_with_expected_payload(tmp_path):
    write_failure_marker(
        str(tmp_path), "abc12345",
        stage="execution", error="subprocess returned 1",
    )
    assert has_failure(str(tmp_path), "abc12345") is True

    payload = read_failure_marker(str(tmp_path), "abc12345")
    assert payload["experiment_id"] == "abc12345"
    assert payload["stage"] == "execution"
    assert payload["error"] == "subprocess returned 1"
    assert isinstance(payload["timestamp"], float)
    assert "traceback" not in payload  # not provided


def test_write_includes_traceback_when_provided(tmp_path):
    write_failure_marker(
        str(tmp_path), "abc12345",
        stage="coordinator_exception",
        error="ValueError: missing key",
        traceback_text="Traceback (most recent call last):\n  File ...\nValueError: missing key",
    )
    payload = read_failure_marker(str(tmp_path), "abc12345")
    assert "Traceback" in payload["traceback"]


def test_write_is_atomic_via_tmp_then_rename(tmp_path):
    """We can't easily simulate a torn write in a unit test, but we CAN check
    that the tmp file is cleaned up (renamed) so a mid-flight reader either
    sees the old state or the complete new one — never a partial JSON blob."""
    write_failure_marker(str(tmp_path), "abc12345", stage="execution", error="x")
    exp_dir = os.path.join(str(tmp_path), "abc12345")
    files = os.listdir(exp_dir)
    assert FAILURE_MARKER_FILENAME in files
    assert not any(name.endswith(".tmp") for name in files)


def test_write_overwrites_existing_marker(tmp_path):
    """A re-run of the same exp_id should overwrite the previous marker, not
    stack them. Coordinator's `_write_failure` at each failure point should
    win the latest write."""
    write_failure_marker(str(tmp_path), "abc12345", stage="execution", error="first")
    write_failure_marker(str(tmp_path), "abc12345", stage="drift", error="second")
    payload = read_failure_marker(str(tmp_path), "abc12345")
    assert payload["stage"] == "drift"
    assert payload["error"] == "second"


def test_read_returns_none_on_malformed_json(tmp_path):
    exp_dir = os.path.join(str(tmp_path), "abc12345")
    os.makedirs(exp_dir)
    with open(os.path.join(exp_dir, FAILURE_MARKER_FILENAME), "w") as f:
        f.write("{not valid json")
    # Should not crash the /status endpoint if a marker got corrupted.
    assert read_failure_marker(str(tmp_path), "abc12345") is None
