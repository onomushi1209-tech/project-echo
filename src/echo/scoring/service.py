"""SCORE stage + the threshold gate that decides whether to proceed to CREATE."""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.core.interfaces import ScoringBrain
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate
from echo.storage.repository import EchoRepository


def score_trend(
    brain: ScoringBrain,
    trend: TrendCandidate,
    research: ResearchPacket,
    ids: IdFactory,
    repository: EchoRepository,
) -> OpportunityScore:
    score = brain.score(trend, research, ids)
    repository.save_score(score)
    return score


def passes_threshold(score: OpportunityScore, threshold: float) -> bool:
    return score.final_score >= threshold
