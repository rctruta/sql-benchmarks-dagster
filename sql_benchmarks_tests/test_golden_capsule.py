"""Golden end-to-end: the capsule contract still holds through the whole harness.

Runs a tiny duckdb experiment via the real CLI into a THROWAWAY results dir
(SB_RESULTS_DIR -> tmp), so nothing lands in the repo and nothing is catalogued.
Asserts the pipeline produces a well-formed capsule AND that its integrity seal
actually verifies. This is the self-enforcing regression for "a run still yields
a sealed, verifiable capsule" — caught automatically instead of by hand.

Marked e2e (slow: spins the Dagster daemon). Runs in the full suite; for a fast
local loop use `pytest -m "not e2e and not integration"`.
"""
import glob
import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTIVE = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "active.yaml")
ARCHIVED = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "archive", "quickstart.yaml")
QUICKSTART = "sql_benchmarks/experiments/queue/quickstart.yaml"


def _snapshot(path):
    return open(path).read() if os.path.exists(path) else None


def _restore(path, content):
    if content is None:
        if os.path.exists(path):
            os.remove(path)          # the run created it — remove
    else:
        with open(path, "w") as f:
            f.write(content)


@pytest.mark.e2e
def test_golden_capsule_end_to_end(tmp_path):
    results = tmp_path / "results"
    env = {**os.environ,
           "SB_RESULTS_DIR": str(results),
           "SB_DATA_DIR": str(tmp_path / "data"),
           # Isolate the config registry too, or the coordinator's "already
           # exists" check skips the run when this ID was seen before (and it
           # would leave a config_<id>.yaml in the repo). Full throwaway run.
           "SB_CONFIG_ARCHIVE_DIR": str(tmp_path / "configs")}
    # run.sh rewrites repo runtime state (active.yaml + archives the queue
    # config) — snapshot and restore so the test leaves the repo clean.
    active_backup = _snapshot(ACTIVE)
    archive_backup = _snapshot(ARCHIVED)
    try:
        run = subprocess.run(["./run.sh", QUICKSTART, "--auto"],
                             cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=420)
        assert run.returncode == 0, f"run failed:\n{run.stdout[-2000:]}\n{run.stderr[-1000:]}"

        capsules = [d for d in glob.glob(str(results / "*"))
                    if os.path.isdir(d) and len(os.path.basename(d)) == 8]
        assert capsules, f"no capsule produced:\n{run.stdout[-1500:]}"
        cap = capsules[0]
        exp_id = os.path.basename(cap)

        # well-formed capsule
        assert glob.glob(os.path.join(cap, "fragments", "*.json")), "no fragments"
        assert glob.glob(os.path.join(cap, "*.csv")), "no results CSV"
        assert os.path.exists(os.path.join(cap, f"metadata_{exp_id}.json")), "no metadata"
        assert os.path.exists(os.path.join(cap, "integrity.seal")), "no integrity seal"

        # the seal must actually verify — reuse the REAL seal function (not a
        # re-impl) with the explicit capsule path
        from sql_benchmarks.utils.hasher import generate_integrity_seal
        with open(os.path.join(cap, "integrity.seal")) as f:
            stored = f.read().strip()
        assert generate_integrity_seal(cap) == stored, "integrity seal does not verify"

        # capsule landed ONLY in the throwaway dir — never the repo results/
        assert exp_id not in os.listdir(
            os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")), \
            "throwaway capsule leaked into the repo results/ dir"
    finally:
        _restore(ACTIVE, active_backup)
        _restore(ARCHIVED, archive_backup)
