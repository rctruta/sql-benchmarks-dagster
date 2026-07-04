from pydantic import BaseModel
from typing import Dict, List


class EngineInfo(BaseModel):
    name: str
    available_suites: List[str]


class SuiteDetail(BaseModel):
    name: str
    engines: List[str]
    benchmark_names: List[str]
    # Categories from taxonomy.yaml (may be empty for uncategorized suites).
    categories: List[str] = []
    # `sql_content` is now OPTIONAL. Default response omits it (default
    # per-suite payload dropped from ~5 KB to ~200 B). Callers pass
    # `?include_sql=true` when they specifically need the raw SQL.
    sql_content: Dict[str, Dict[str, str]] = {}


class CategoryInfo(BaseModel):
    name: str
    description: str
    suite_count: int


class CatalogCategoriesResponse(BaseModel):
    categories: List[CategoryInfo]


class CatalogEnginesResponse(BaseModel):
    engines: List[EngineInfo]


class CatalogSuitesResponse(BaseModel):
    suites: List[SuiteDetail]


class TemplateSummary(BaseModel):
    """One curated example config the agent can `get_template(name)` and adapt.

    Fields:
      name        — stem of the YAML file (no extension); the value to pass
                    back to `get_template`.
      description — best-effort one-liner: meta.description → meta.name →
                    top comment line → filename.
      path        — relative path from EXPERIMENTS_DIR, for traceability.
    """
    name: str
    description: str
    path: str


class CatalogTemplatesResponse(BaseModel):
    templates: List[TemplateSummary]


class TemplateContent(BaseModel):
    """Full YAML source of a template. The agent adapts this and submits the
    modified text via `submit_experiment`."""
    name: str
    content: str
    path: str
