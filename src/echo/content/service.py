"""CREATE stage: orchestrates draft generation + persistence."""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.core.interfaces import ContentBrain
from echo.models.draft import ContentDraft
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate
from echo.storage.repository import EchoRepository


def create_draft(
    brain: ContentBrain,
    trend: TrendCandidate,
    research: ResearchPacket,
    score: OpportunityScore,
    ids: IdFactory,
    repository: EchoRepository,
) -> ContentDraft:
    draft = brain.draft(trend, research, score, ids)
    repository.save_draft(draft)
    return draft
