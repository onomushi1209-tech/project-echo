"""DummyTrendBrain: deterministic stub trend detector.

Wraps each SourceItem into its own TrendCandidate. velocity is derived from
how recently the source was published (a simple, deterministic recency
heuristic); novelty/relevance are fixed placeholders. Real
clustering/velocity detection is out of scope for STEP 1 -- see
docs/ARCHITECTURE.md for the swap-in point (echo.core.interfaces.TrendBrain).
"""

from __future__ import annotations

from datetime import datetime, timezone

from echo.core.ids import IdFactory
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate

_RECENCY_WINDOW_HOURS = 24.0
_MIN_VELOCITY = 0.3
_MAX_VELOCITY = 0.9


class DummyTrendBrain:
    def detect(
        self, sources: list[SourceItem], vertical: str, ids: IdFactory
    ) -> list[TrendCandidate]:
        now = datetime.now(timezone.utc)
        return [
            TrendCandidate(
                trend_id=ids.trend_id(),
                trace_id=ids.trace_id(),
                topic=source.title,
                keywords=_keywords_from_title(source.title),
                sources=[source.source_id],
                detected_at=now,
                velocity=_recency_velocity(source, now),
                novelty=0.55,
                relevance=0.6,
                vertical=vertical,
            )
            for source in sources
        ]


def _recency_velocity(source: SourceItem, now: datetime) -> float:
    age_hours = max(0.0, (now - source.published_at).total_seconds() / 3600.0)
    raw = 1.0 - (age_hours / _RECENCY_WINDOW_HOURS)
    return round(max(_MIN_VELOCITY, min(_MAX_VELOCITY, raw)), 4)


def _keywords_from_title(title: str) -> list[str]:
    words = [w.strip(".,:;!?()").lower() for w in title.split()]
    return [w for w in words if len(w) > 3][:5]
