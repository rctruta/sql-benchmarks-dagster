"""Capsule lifecycle: catalog `tier` column + safe removal guards."""
import importlib.util
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel_path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_cfg(cap_dir, body):
    os.makedirs(cap_dir, exist_ok=True)
    with open(os.path.join(cap_dir, "experiment_config.yaml"), "w") as f:
        f.write(body)


# ---------- catalog tier ----------
def test_catalog_row_shows_declared_tier(tmp_path):
    cat = _load("scripts/tools/gen_experiment_catalog.py", "catmod")
    cap = tmp_path / "abcd1234"
    _write_cfg(str(cap), "meta:\n  name: T\n  tier: verified\nexecution:\n  engines: [duckdb]\n  test_suite: s\n")
    _, line = cat.row_for(str(cap))
    assert "verified" in line


def test_catalog_row_undeclared_tier_is_not_assumed(tmp_path):
    # Absent tier must NOT be assumed verified OR exploratory (sealed legacy
    # capsules can't be retroactively tiered) — it shows undeclared.
    cat = _load("scripts/tools/gen_experiment_catalog.py", "catmod2")
    cap = tmp_path / "abcd1234"
    _write_cfg(str(cap), "meta:\n  name: T\nexecution:\n  engines: [duckdb]\n")
    _, line = cat.row_for(str(cap))
    assert "| — |" in line
    assert "exploratory" not in line and "verified" not in line


# ---------- removal guards (destructive-op safety) ----------
def test_remove_refuses_non_hex_ids():
    rm = _load("scripts/dev/remove_capsule.py", "rmmod")
    assert rm.remove("not-an-id") is False        # not 8-hex
    assert rm.remove("../../etc") is False         # no path traversal possible
    assert rm.remove("DEADBEEF") is False          # uppercase not allowed
    assert rm.remove("deadbee") is False           # too short


def test_remove_missing_capsule_is_safe():
    rm = _load("scripts/dev/remove_capsule.py", "rmmod2")
    # well-formed id, but no such capsule -> returns False, deletes nothing, no crash
    assert rm.remove("deadbeef") is False
