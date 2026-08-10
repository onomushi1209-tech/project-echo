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


def partition_trends_by_novelty(
    candidates: list[TrendCandidate], novelty_threshold: float
) -> tuple[list[TrendCandidate], int]:
    """Split detected candidates into (to_persist, skipped_count).

    A candidate whose ``novelty`` is below ``novelty_threshold`` is a
    near-exact repeat of an already-detected topic/event (see
    ``echo.trend.novelty`` -- novelty is computed against recently
    detected trends, so a repeat naturally scores low) and is not written
    to the ``trends`` table. This bounds unbounded row growth from running
    ``echo trends detect`` repeatedly over unchanged SourceItems, without
    deleting or modifying any already-persisted trend row: if new
    SourceItems later push a topic's novelty back up (genuinely new
    information), it is eligible to persist again on a later run.

    Pure/side-effect-free by design so it's testable without a repository
    or CLI -- callers (``echo.cli.trends_detect``) are responsible for
    actually persisting ``to_persist`` and reporting ``skipped_count``.
    """
    to_persist = [c for c in candidates if c.novelty >= novelty_threshold]
    skipped_count = len(candidates) - len(to_persist)
    return to_persist, skipped_count
