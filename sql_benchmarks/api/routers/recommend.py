from typing import Optional

from fastapi import APIRouter, Query

from ..data.reader import ResultReader
from ..logic.ranker import recommend_engine
from ..models.recommend import RecommendResponse

router = APIRouter(prefix="/v1", tags=["recommend"])
_reader = ResultReader()


@router.get("/recommend", response_model=RecommendResponse)
def recommend(
    suite: Optional[str] = Query(None, description="Test suite name (e.g. analytical_wall)"),
    scale: Optional[str] = Query(None, description="Partition key substring to filter by scale (e.g. 'large')"),
):
    """
    Get an engine recommendation based on pre-computed benchmark data.
    Returns the fastest engine for the given suite and scale, with confidence and reasoning.
    """
    return recommend_engine(_reader, suite=suite, scale=scale)
