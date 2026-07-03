"""Tests for the templates discovery layer.

Contract:
  - Files in `templates/` and `queue/` are surfaced as templates.
  - Files whose stem looks like an 8-char experiment_id are excluded
    (runtime queue entries, not curated examples).
  - `get_template(name)` returns the raw file content by stem.
  - Description falls back through meta.description → meta.name →
    top comment → filename.
"""
import os
import pytest

from sql_benchmarks.api.data.templates_reader import TemplatesReader
from sql_benchmarks.api.data import templates_reader as tr


@pytest.fixture
def fake_experiments(tmp_path, monkeypatch):
    """Point EXPERIMENTS_DIR at a scratch directory populated with a mix of
    curated and runtime-looking files across templates/ and queue/."""
    exp_dir = tmp_path
    templates_dir = exp_dir / "templates"
    queue_dir = exp_dir / "queue"
    templates_dir.mkdir()
    queue_dir.mkdir()

    # Curated template with a meta.description
    (templates_dir / "annotated.yaml").write_text(
        'meta:\n  description: "The annotated all-fields example."\ndataset: {}\n'
    )
    # Curated queue entry with meta.name only
    (queue_dir / "quickstart.yaml").write_text(
        'meta:\n  name: "Tiny quickstart"\ndataset: {}\n'
    )
    # Curated queue entry with only a top comment
    (queue_dir / "top_comment_only.yaml").write_text(
        "# a description from a top comment\ndataset: {}\n"
    )
    # Curated queue entry with nothing describable
    (queue_dir / "bare.yaml").write_text("dataset: {}\n")
    # Runtime queue entry — should be EXCLUDED
    (queue_dir / "deadbeef.yaml").write_text('meta:\n  name: "runtime artifact"\n')
    # Another runtime entry (8 hex chars)
    (queue_dir / "abcd1234.yaml").write_text("dataset: {}\n")
    # Not-yaml file — should be ignored
    (queue_dir / "readme.txt").write_text("noise")

    monkeypatch.setattr(tr, "EXPERIMENTS_DIR", str(exp_dir))
    return exp_dir


def test_lists_curated_files_only(fake_experiments):
    names = {t.name for t in TemplatesReader().list_templates()}
    assert names == {"annotated", "quickstart", "top_comment_only", "bare"}


def test_runtime_id_files_excluded(fake_experiments):
    """Files whose stem matches ^[0-9a-f]{8}$ are coordinator artifacts."""
    names = {t.name for t in TemplatesReader().list_templates()}
    assert "deadbeef" not in names
    assert "abcd1234" not in names


def test_description_prefers_meta_description(fake_experiments):
    templates = {t.name: t for t in TemplatesReader().list_templates()}
    assert templates["annotated"].description == "The annotated all-fields example."


def test_description_falls_back_to_meta_name(fake_experiments):
    templates = {t.name: t for t in TemplatesReader().list_templates()}
    assert templates["quickstart"].description == "Tiny quickstart"


def test_description_falls_back_to_top_comment(fake_experiments):
    templates = {t.name: t for t in TemplatesReader().list_templates()}
    assert templates["top_comment_only"].description == "a description from a top comment"


def test_description_falls_back_to_filename(fake_experiments):
    templates = {t.name: t for t in TemplatesReader().list_templates()}
    assert templates["bare"].description == "bare.yaml"


def test_get_template_returns_raw_content(fake_experiments):
    content = TemplatesReader().get_template("quickstart")
    assert content is not None
    assert 'name: "Tiny quickstart"' in content


def test_get_template_returns_none_for_missing_name(fake_experiments):
    assert TemplatesReader().get_template("nonexistent") is None


def test_get_template_returns_none_for_runtime_id(fake_experiments):
    """Even if the runtime file exists on disk, it must not be fetchable via
    the template API — the filter is authoritative on both list and get."""
    assert TemplatesReader().get_template("deadbeef") is None


def test_path_field_is_relative_to_experiments_dir(fake_experiments):
    templates = {t.name: t for t in TemplatesReader().list_templates()}
    assert templates["quickstart"].path == os.path.join("queue", "quickstart.yaml")
    assert templates["annotated"].path == os.path.join("templates", "annotated.yaml")
