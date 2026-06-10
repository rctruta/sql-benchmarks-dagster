from fastapi import APIRouter

from ..data.catalog_reader import CatalogReader
from ..models.catalog import CatalogEnginesResponse, CatalogSuitesResponse

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])
_reader = CatalogReader()


@router.get("/engines", response_model=CatalogEnginesResponse)
def list_engines():
    """List available database engines and the test suites they support."""
    return _reader.get_engines_response()


@router.get("/suites", response_model=CatalogSuitesResponse)
def list_suites():
    """List all benchmark test suites with their SQL content per engine."""
    return _reader.get_suites_response()
