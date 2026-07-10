"""Verify skills/*.md files exist and cover the expected topics.

Skills are the tactical playbook loaded into the agent's system prompt
via autonomous_agent.load_skills(). Testing the loader itself would
require importing the agent script (which pulls in litellm — not a dev
dep); testing the files directly is what actually matters: if the
files are wrong, the loader loading them correctly doesn't help.
"""
import os


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILLS_DIR = os.path.join(_REPO_ROOT, "skills")


def _read(name: str) -> str:
    with open(os.path.join(_SKILLS_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_skills_dir_exists_and_has_two_shipped_skills():
    assert os.path.isdir(_SKILLS_DIR)
    assert os.path.isfile(os.path.join(_SKILLS_DIR, "build-scaling-experiment", "SKILL.md"))
    assert os.path.isfile(os.path.join(_SKILLS_DIR, "read-experiment-results", "SKILL.md"))


def test_build_scaling_experiment_covers_known_pitfalls():
    """The pitfalls listed in the skill must match the actual validation
    surface — each one has broken a previous run and is now enforced at
    submission time. If the skill drifts from what validation rejects,
    the agent will re-hit the trap."""
    text = _read("build-scaling-experiment/SKILL.md")
    assert "literal" in text.lower()  # literal rows rejection (PR #121)
    assert "matrix alias" in text.lower()  # alias resolvability
    assert "engines" in text.lower()  # empty engines rejection
    assert "get_template" in text  # concrete tool named
    assert "quickstart" in text  # names the DuckDB-only starter


def test_read_experiment_results_names_every_projection():
    """The decision table must name every tool the agent can call for
    reading results. Missing one means the agent won't reach for it."""
    text = _read("read-experiment-results/SKILL.md")
    for tool in [
        "get_experiment_summary",
        "get_means_by_partition",
        "get_scaling_factor",
        "get_replication_stability",
        "compare_engines",
        "compare_engines_by_partition",
        "get_experiment_result",
    ]:
        assert tool in text, f"Skill missing tool: {tool}"
    # And the ordering caveat that makes get_scaling_factor safe to use
    assert "partitions_order" in text
    # And the provenance concept
    assert "provenance" in text.lower()
