import statistics
from typing import Dict, List, Optional

from ..data.reader import ResultReader
from ..models.recommend import RecommendResponse
from ..models.results import EngineRanking, Fragment


def score_engines(
    fragments: List[Fragment],
    partition_filter: Optional[str] = None,
) -> List[EngineRanking]:
    """
    Groups fragments by engine, computes mean/median/p95 duration.
    Returns rankings sorted ascending (rank 1 = fastest).
    """
    by_engine: Dict[str, List[float]] = {}
    for f in fragments:
        if partition_filter and partition_filter not in f.meta.partition:
            continue
        engine = f.meta.engine
        by_engine.setdefault(engine, []).append(f.metrics.duration_seconds)

    if not by_engine:
        return []

    stats = []
    for engine, durations in by_engine.items():
        sorted_d = sorted(durations)
        n = len(sorted_d)
        p95_idx = max(0, int(n * 0.95) - 1)
        stats.append({
            "engine": engine,
            "mean": statistics.mean(sorted_d),
            "median": statistics.median(sorted_d),
            "p95": sorted_d[p95_idx],
            "count": n,
        })

    stats.sort(key=lambda x: x["mean"])

    return [
        EngineRanking(
            engine=s["engine"],
            mean_duration_seconds=round(s["mean"], 6),
            median_duration_seconds=round(s["median"], 6),
            p95_duration_seconds=round(s["p95"], 6),
            sample_count=s["count"],
            rank=i + 1,
        )
        for i, s in enumerate(stats)
    ]


def recommend_engine(
    reader: ResultReader,
    suite: Optional[str],
    scale: Optional[str],
) -> RecommendResponse:
    summaries = reader.filter_experiments(suite=suite)
    exp_ids = [s.experiment_id for s in summaries]

    all_fragments: List[Fragment] = []
    for exp_id in exp_ids:
        all_fragments.extend(reader.get_fragments(exp_id))

    if scale:
        all_fragments = [f for f in all_fragments if scale in f.meta.partition]

    rankings = score_engines(all_fragments)
    caveats = []
    known_engines = {"postgres", "duckdb", "actian"}

    if not rankings:
        engines_with_data = set()
    else:
        engines_with_data = {r.engine for r in rankings}

    for e in known_engines:
        if e not in engines_with_data:
            caveats.append(f"No data for '{e}'" + (f" in suite '{suite}'" if suite else ""))

    if not rankings:
        return RecommendResponse(
            recommended_engine="unknown",
            confidence="low",
            reasoning="No benchmark data found for the requested filters.",
            supporting_experiments=exp_ids,
            engine_scores={},
            caveats=caveats,
        )

    winner = rankings[0]
    total_samples = sum(r.sample_count for r in rankings)

    if len(rankings) > 1:
        second = rankings[1]
        speedup = second.mean_duration_seconds / winner.mean_duration_seconds
    else:
        speedup = 1.0

    if winner.sample_count >= 10 and speedup >= 1.20:
        confidence = "high"
    elif winner.sample_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    suite_label = f"suite '{suite}'" if suite else "available suites"
    scale_label = f" at scale '{scale}'" if scale else ""
    reasoning = (
        f"Based on {total_samples} samples across {suite_label}{scale_label}, "
        f"{winner.engine} is fastest with mean {winner.mean_duration_seconds:.4f}s"
    )
    if len(rankings) > 1:
        reasoning += f" vs {rankings[1].engine} at {rankings[1].mean_duration_seconds:.4f}s ({speedup:.1f}x speedup)."
    else:
        reasoning += "."

    return RecommendResponse(
        recommended_engine=winner.engine,
        confidence=confidence,
        reasoning=reasoning,
        supporting_experiments=exp_ids,
        engine_scores={r.engine: r.mean_duration_seconds for r in rankings},
        caveats=caveats,
    )
