"""DISCOVER stage: orchestrates trend detection + persistence.

Delegates the actual detection logic to an injected TrendBrain (see
echo.core.interfaces) -- this module only sequences the call and storage.
"""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.core.interfaces import TrendBrain
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.storage.repository import EchoRepository


def discover_trends(
    brain: TrendBrain,
    sources: list[SourceItem],
    vertical: str,
    ids: IdFactory,
    repository: EchoRepository,
) -> list[TrendCandidate]:
    trends = brain.detect(sources, vertical, ids)
    for trend in trends:
        repository.save_trend(trend)
    return trends
