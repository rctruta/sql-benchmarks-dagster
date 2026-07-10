from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..data.catalog_reader import CatalogReader
from ..data.templates_reader import TemplatesReader
from ..data import taxonomy
from ..models.catalog import (
    CatalogCategoriesResponse,
    CatalogEnginesResponse,
    CatalogSuitesResponse,
    CatalogTemplatesResponse,
    CategoryInfo,
    TemplateContent,
)

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])
_reader = CatalogReader()
_templates = TemplatesReader()


@router.get("/categories", response_model=CatalogCategoriesResponse)
def list_categories():
    """List the category taxonomy. Small payload — call this FIRST to
    narrow the suite search before calling `list_suites`. See
    `sql_benchmarks/experiments/taxonomy.yaml` for the vocabulary."""
    cats = taxonomy.list_categories()
    counts = taxonomy.category_counts()
    return CatalogCategoriesResponse(categories=[
        CategoryInfo(name=name, description=desc, suite_count=counts.get(name, 0))
        for name, desc in cats.items()
    ])


@router.get("/engines", response_model=CatalogEnginesResponse)
def list_engines():
    """List available database engines and the test suites they support."""
    return _reader.get_engines_response()


@router.get("/suites", response_model=CatalogSuitesResponse)
def list_suites(
    category: Optional[str] = Query(None, description="Filter to suites tagged with this category"),
    include_sql: bool = Query(False, description="Include raw SQL per engine (large payload; default off)"),
):
    """List benchmark test suites.

    Default response is small: name, engines, benchmark_names, categories.
    Pass `?category=X` to filter to a slice of the vocabulary (see
    `/v1/catalog/categories`). Pass `?include_sql=true` to also return
    the raw SQL keyed by engine (a KB per suite — only ask if you need
    to reason about the SQL itself)."""
    return _reader.get_suites_response(include_sql=include_sql, category=category)


@router.get("/templates", response_model=CatalogTemplatesResponse)
def list_templates():
    """List curated experiment templates. Each is a valid, human-authored
    config the agent can `get_template(name)` and adapt to its needs.

    Templates are drawn from `experiments/templates/` and `experiments/queue/`
    (excluding runtime queue entries whose names look like an 8-char
    experiment_id — those are coordinator artifacts, not curated examples).
    """
    return CatalogTemplatesResponse(templates=_templates.list_templates())


@router.get("/templates/{name}", response_model=TemplateContent)
def get_template(name: str):
    """Return the raw YAML content of a template by name (stem without
    `.yaml`). Adapt the content — change engines, dataset scale, table
    names as needed — and submit via `POST /v1/experiments`.

    404 if the template name isn't in `list_templates`'s output.
    """
    content = _templates.get_template(name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    for t in _templates.list_templates():
        if t.name == name:
            return TemplateContent(name=name, content=content, path=t.path)
    raise HTTPException(status_code=404, detail=f"Template '{name}' not found")


@router.get("/published")
def search_published(category: str | None = None):
    """Discovery over the published (git-tracked + sealed) capsule corpus —
    the lab's own literature. Optional taxonomy-category filter. Read a
    hit with the existing result projections."""
    from ..logic.published_library import search_published_capsules
    return {"capsules": search_published_capsules(category=category)}


@router.get("/docs")
def list_docs():
    """Names + titles of the lab's published documents (README, FAQ,
    docs/*.md incl. the generated experiment catalog)."""
    from ..logic.lab_docs import list_lab_docs
    return {"docs": list_lab_docs()}


@router.get("/docs/{name:path}")
def get_doc(name: str):
    """One published document's text (size-capped, truncation stated)."""
    from fastapi import HTTPException
    from ..logic.lab_docs import get_lab_doc
    doc = get_lab_doc(name)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No published doc named '{name}'")
    return doc


@router.get("/skills")
def list_skills_endpoint():
    """Discovery stage of the Agent Skills spec: name + description per
    skill — never the bodies."""
    from ..logic.skills_library import list_skills
    return {"skills": list_skills()}


@router.get("/skills/{name}")
def get_skill_endpoint(name: str):
    """Activation stage: one skill's full instructions, on demand."""
    from fastapi import HTTPException
    from ..logic.skills_library import get_skill
    skill = get_skill(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"No skill named '{name}'")
    return skill
