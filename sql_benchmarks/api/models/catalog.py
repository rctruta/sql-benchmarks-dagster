from pydantic import BaseModel
from typing import Dict, List


class EngineInfo(BaseModel):
    name: str
    available_suites: List[str]


class SuiteDetail(BaseModel):
    name: str
    engines: List[str]
    benchmark_names: List[str]
    sql_content: Dict[str, Dict[str, str]]  # {engine: {benchmark_name: sql_text}}


class CatalogEnginesResponse(BaseModel):
    engines: List[EngineInfo]


class CatalogSuitesResponse(BaseModel):
    suites: List[SuiteDetail]
