"""Tests for the category taxonomy — vocabulary, suite tagging, capsule
inheritance, and the /v1/catalog/categories + filter endpoints."""
from fastapi.testclient import TestClient

from sql_benchmarks.api.app import create_app
from sql_benchmarks.api.data import taxonomy


def test_taxonomy_yaml_loads_and_names_expected_categories():
    """taxonomy.yaml must exist at the well-known path and name the
    minimal set of categories the skills reference."""
    cats = taxonomy.list_categories()
    for expected in ("scaling", "cross-engine", "analytical", "join",
                     "selectivity", "null-handling", "transport"):
        assert expected in cats, f"taxonomy missing category: {expected}"


def test_suite_categories_analytical_wall_is_scaling_and_analytical():
    """The skill build_scaling_experiment.md says: for scaling questions,
    use `analytical_wall`. That suite must be tagged for `scaling`."""
    cats = taxonomy.suite_categories("analytical_wall")
    assert "scaling" in cats
    assert "analytical" in cats


def test_suites_in_category_returns_only_matching_suites():
    scaling = set(taxonomy.suites_in_category("scaling"))
    # analytical_wall is the canonical scaling suite
    assert "analytical_wall" in scaling
    # a suite in a different category should NOT be here
    assert "null_logic" not in scaling


def test_capsule_categories_inherit_from_suite():
    """A capsule whose suite is `analytical_wall` inherits scaling + analytical
    from the suite tags, plus any explicit override."""
    cats = taxonomy.capsule_categories(exp_id="unlisted_id", suite_name="analytical_wall")
    assert "scaling" in cats and "analytical" in cats


def test_capsule_categories_explicit_override_added_to_inherited():
    """461beee8 is explicitly tagged in taxonomy.yaml — that tag stacks with
    whatever its suite (selectivity) inherits."""
    cats = taxonomy.capsule_categories(exp_id="461beee8", suite_name="selectivity")
    assert "selectivity" in cats  # from explicit override AND suite


# --- REST endpoints ---------------------------------------------------------

def _client():
    return TestClient(create_app())


def test_get_categories_returns_vocabulary_with_counts():
    resp = _client().get("/v1/catalog/categories")
    assert resp.status_code == 200
    body = resp.json()
    names = {c["name"]: c for c in body["categories"]}
    assert "scaling" in names
    assert names["scaling"]["suite_count"] >= 1  # analytical_wall at minimum
    assert "description" in names["scaling"]


def test_get_suites_with_category_filter_narrows_results():
    resp = _client().get("/v1/catalog/suites?category=scaling")
    assert resp.status_code == 200
    suite_names = [s["name"] for s in resp.json()["suites"]]
    assert "analytical_wall" in suite_names
    assert "null_logic" not in suite_names  # different category


def test_get_suites_returns_categories_field_per_suite():
    """Every suite entry must carry its `categories` list — that's how
    the agent chains from list_suites to which category the returned
    suite belongs to."""
    resp = _client().get("/v1/catalog/suites")
    assert resp.status_code == 200
    for suite in resp.json()["suites"]:
        assert "categories" in suite
        assert isinstance(suite["categories"], list)
