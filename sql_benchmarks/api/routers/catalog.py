from fastapi import APIRouter, HTTPException

from ..data.catalog_reader import CatalogReader
from ..data.templates_reader import TemplatesReader
from ..models.catalog import (
    CatalogEnginesResponse,
    CatalogSuitesResponse,
    CatalogTemplatesResponse,
    TemplateContent,
)

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])
_reader = CatalogReader()
_templates = TemplatesReader()


@router.get("/engines", response_model=CatalogEnginesResponse)
def list_engines():
    """List available database engines and the test suites they support."""
    return _reader.get_engines_response()


@router.get("/suites", response_model=CatalogSuitesResponse)
def list_suites():
    """List all benchmark test suites with their SQL content per engine."""
    return _reader.get_suites_response()


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
