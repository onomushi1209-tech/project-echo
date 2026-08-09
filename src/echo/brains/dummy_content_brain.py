"""DummyContentBrain: deterministic stub drafter.

Builds a ContentDraft directly from the research summary/facts. No external
AI API calls. content_type is always EXPLAIN in STEP 1.
"""

from __future__ import annotations

from datetime import datetime, timezone

from echo.core.ids import IdFactory
from echo.models.draft import ContentDraft
from echo.models.enums import ContentType
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate


class DummyContentBrain:
    def draft(
        self,
        trend: TrendCandidate,
        research: ResearchPacket,
        score: OpportunityScore,
        ids: IdFactory,
    ) -> ContentDraft:
        body = " ".join([research.summary, *research.key_facts]).strip()
        return ContentDraft(
            draft_id=ids.draft_id(),
            trend_id=trend.trend_id,
            trace_id=trend.trace_id,
            content_type=ContentType.EXPLAIN,
            hook=trend.topic,
            body=body,
            cta="Follow for more updates.",
            sources=research.sources,
            confidence=research.confidence,
            generated_at=datetime.now(timezone.utc),
            vertical=trend.vertical,
        )
