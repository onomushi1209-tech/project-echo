"""DummyScoringBrain: deterministic stub scorer.

Derives sub-scores from trend/research fields where available and uses
fixed placeholders elsewhere. final_score is a weighted blend discounted by
risk_score, clamped to [0, 1].
"""

from __future__ import annotations

from datetime import datetime, timezone

from echo.core.ids import IdFactory
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate

_WEIGHTS = {
    "attention": 0.20,
    "relevance": 0.20,
    "novelty": 0.15,
    "timeliness": 0.15,
    "source": 0.15,
    "monetization": 0.15,
}


class DummyScoringBrain:
    def score(
        self, trend: TrendCandidate, research: ResearchPacket, ids: IdFactory
    ) -> OpportunityScore:
        attention = trend.velocity
        relevance = trend.relevance
        novelty = trend.novelty
        timeliness = 0.7
        source = research.source_quality
        monetization = 0.5
        risk = 0.2 if research.conflicting_information else 0.1

        weighted = (
            attention * _WEIGHTS["attention"]
            + relevance * _WEIGHTS["relevance"]
            + novelty * _WEIGHTS["novelty"]
            + timeliness * _WEIGHTS["timeliness"]
            + source * _WEIGHTS["source"]
            + monetization * _WEIGHTS["monetization"]
        )
        final = max(0.0, min(1.0, weighted * (1 - risk)))

        return OpportunityScore(
            score_id=ids.score_id(),
            trend_id=trend.trend_id,
            trace_id=trend.trace_id,
            attention_score=attention,
            relevance_score=relevance,
            novelty_score=novelty,
            timeliness_score=timeliness,
            source_score=source,
            monetization_score=monetization,
            risk_score=risk,
            final_score=round(final, 4),
            scored_at=datetime.now(timezone.utc),
        )
