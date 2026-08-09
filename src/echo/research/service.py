"""RESEARCH stage: orchestrates research packet generation + persistence."""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.core.interfaces import ResearchBrain
from echo.models.research import ResearchPacket
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.storage.repository import EchoRepository


def research_trend(
    brain: ResearchBrain,
    trend: TrendCandidate,
    sources: list[SourceItem],
    ids: IdFactory,
    repository: EchoRepository,
) -> ResearchPacket:
    research = brain.research(trend, sources, ids)
    repository.save_research(research)
    return research
