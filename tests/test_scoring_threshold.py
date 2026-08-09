from __future__ import annotations

from datetime import datetime, timezone

from echo.models.score import OpportunityScore
from echo.scoring.service import passes_threshold

NOW = datetime.now(timezone.utc)


def _score(final_score: float) -> OpportunityScore:
    return OpportunityScore(
        score_id="score-1",
        trend_id="trend-1",
        trace_id="ECHO-AI-20260809-000001",
        attention_score=0.5,
        relevance_score=0.5,
        novelty_score=0.5,
        timeliness_score=0.5,
        source_score=0.5,
        monetization_score=0.5,
        risk_score=0.1,
        final_score=final_score,
        scored_at=NOW,
    )


def test_score_above_threshold_passes() -> None:
    assert passes_threshold(_score(0.7), threshold=0.5) is True


def test_score_below_threshold_fails() -> None:
    assert passes_threshold(_score(0.3), threshold=0.5) is False


def test_score_equal_to_threshold_passes() -> None:
    assert passes_threshold(_score(0.5), threshold=0.5) is True
