"""server.json must stay consistent with the package it publishes.

The MCP registry resolves `packages[].identifier` on PyPI at
`packages[].version`. If server.json says 0.1.2 and PyPI only has 0.1.1, the
listing points at a version that does not exist — and the failure appears to
users as a broken install, not as a publishing mistake.

The README marker is how the registry verifies repo ownership: it compares
that string to `name`. A mismatch fails publication with a message about
authentication, which is a confusing way to learn you have a typo.
"""
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def manifest():
    with open(os.path.join(ROOT, "server.json")) as f:
        return json.load(f)


def _pyproject_version() -> str:
    with open(os.path.join(ROOT, "pyproject.toml")) as f:
        return re.search(r'^version = "([^"]+)"', f.read(), re.M).group(1)


def test_versions_agree(manifest):
    v = _pyproject_version()
    assert manifest["version"] == v, "server.json version != pyproject version"
    assert manifest["packages"][0]["version"] == v, \
        "packages[].version must be the version actually published to PyPI"


def test_package_identifier_is_the_real_distribution(manifest):
    with open(os.path.join(ROOT, "pyproject.toml")) as f:
        name = re.search(r'^name = "([^"]+)"', f.read(), re.M).group(1)
    assert manifest["packages"][0]["identifier"] == name


def test_readme_ownership_marker_matches_server_name(manifest):
    with open(os.path.join(ROOT, "README.md")) as f:
        readme = f.read()
    assert f"mcp-name: {manifest['name']}" in readme, (
        "README must carry '<!-- mcp-name: %s -->' — the registry uses it to "
        "confirm repo ownership" % manifest["name"])


def test_namespace_matches_repo_owner(manifest):
    assert manifest["name"].startswith("io.github.rctruta/"), \
        "namespace must match the GitHub account that authenticates"


def test_entry_point_declared(manifest):
    """packages[] resolves to a runnable command; without the console script
    the published package installs but cannot start."""
    with open(os.path.join(ROOT, "pyproject.toml")) as f:
        assert "sqlbench-mcp = " in f.read()


def test_transport_is_declared(manifest):
    t = manifest["packages"][0]["transport"]["type"]
    assert t in ("stdio", "streamable-http", "sse"), t


def test_taxonomy_ships_as_package_data():
    """list_categories and list_suites read experiments/taxonomy.yaml.

    It was missing from package-data until 2026-08-10, so every clean install
    returned empty arrays from both tools — the SQL shipped but the index of it
    did not. Empty-but-successful is the worst failure shape: it reads as "no
    data exists" rather than "a file is missing".
    """
    with open(os.path.join(ROOT, "pyproject.toml")) as f:
        assert "experiments/taxonomy.yaml" in f.read()


def test_results_dir_is_documented_as_an_env_var(manifest):
    """Capsules are deliberately not shipped, so list_results is empty on a
    fresh install. The manifest must tell users how to point at their own."""
    names = {e["name"] for e in manifest["packages"][0].get("environmentVariables", [])}
    assert "SB_RESULTS_DIR" in names


def test_description_within_registry_limit(manifest):
    """The registry rejects description > 100 chars with a 422.

    Learned the hard way: the failure surfaces only at `mcp-publisher
    validate`, mid-publish, and the error is easy to misread as an auth
    problem. Catching it in the suite costs nothing.
    """
    d = manifest["description"]
    assert len(d) <= 100, f"description is {len(d)} chars, registry limit is 100"


def test_title_is_present_for_display(manifest):
    """description is capped at 100 chars, so `title` carries the readable
    name in listings. Without it the entry shows a bare reverse-DNS id."""
    assert manifest.get("title"), "title is what users see in the registry"
