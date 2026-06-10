from pydantic import BaseModel
from typing import Dict, List


class RecommendResponse(BaseModel):
    recommended_engine: str
    confidence: str  # "high" | "medium" | "low"
    reasoning: str
    supporting_experiments: List[str]
    engine_scores: Dict[str, float]  # {engine: mean_duration_seconds}
    caveats: List[str]
