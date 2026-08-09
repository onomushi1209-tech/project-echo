"""DummyResearchBrain: deterministic stub researcher.

Summarizes by concatenating matched source titles. No external calls.
"""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.models.research import ResearchPacket
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate


class DummyResearchBrain:
    def research(
        self, trend: TrendCandidate, sources: list[SourceItem], ids: IdFactory
    ) -> ResearchPacket:
        matched = [s for s in sources if s.source_id in trend.sources]
        key_facts = [s.title for s in matched][:5] or [trend.topic]
        return ResearchPacket(
            research_id=ids.research_id(),
            trend_id=trend.trend_id,
            trace_id=trend.trace_id,
            summary=f"Stub research summary for '{trend.topic}'.",
            key_facts=key_facts,
            sources=trend.sources,
            source_quality=0.6,
            conflicting_information=False,
            confidence=0.6,
        )
