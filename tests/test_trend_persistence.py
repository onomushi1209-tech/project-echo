"""Trend re-detection persistence guard (Pre-Commit Hardening):
echo.trend.service.partition_trends_by_novelty, and the full
detect -> partition -> persist cycle against a real repository. See
docs/SOURCE_INTELLIGENCE.md "Trend persistence guard"."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.brains.real_trend_brain import RealTrendBrain
from echo.core.ids import IdFactory
from echo.core.trace import TraceIDGenerator
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.trend.service import partition_trends_by_novelty
from echo.trend.signal_config import TrendSignalConfig

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _candidate(topic: str, novelty: float) -> TrendCandidate:
    return TrendCandidate(
        trend_id=f"trend-{topic}",
        trace_id="ECHO-AI-20260809-000001",
        topic=topic,
        detected_at=NOW,
        velocity=0.5,
        novelty=novelty,
        relevance=0.5,
        vertical="ai",
    )


# -- partition_trends_by_novelty (pure) --------------------------------------


def test_partition_persists_candidate_at_or_above_threshold() -> None:
    to_persist, skipped = partition_trends_by_novelty([_candidate("a", 0.10)], novelty_threshold=0.10)
    assert len(to_persist) == 1
    assert skipped == 0


def test_partition_skips_candidate_below_threshold() -> None:
    to_persist, skipped = partition_trends_by_novelty([_candidate("a", 0.05)], novelty_threshold=0.10)
    assert to_persist == []
    assert skipped == 1


def test_partition_mixed_candidates() -> None:
    candidates = [_candidate("new", 1.0), _candidate("repeat", 0.0), _candidate("borderline", 0.10)]
    to_persist, skipped = partition_trends_by_novelty(candidates, novelty_threshold=0.10)
    assert {c.topic for c in to_persist} == {"new", "borderline"}
    assert skipped == 1


def test_partition_empty_input() -> None:
    to_persist, skipped = partition_trends_by_novelty([], novelty_threshold=0.10)
    assert to_persist == []
    assert skipped == 0


def test_partition_does_not_mutate_or_drop_input_list_identity() -> None:
    """Candidates chosen for persistence must be the same objects (not
    copies) so repository.save_trend() writes the real, fully-scored data."""
    candidate = _candidate("a", 1.0)
    to_persist, _ = partition_trends_by_novelty([candidate], novelty_threshold=0.10)
    assert to_persist[0] is candidate


# -- full detect -> partition -> persist cycle, against a real repository ----


def _item(source_id: str, title: str, minutes_ago: int = 5) -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key="s",
        url=f"https://example.com/{source_id}",
        source_name="s",
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content="body",
        language="en",
        vertical="ai",
    )


def test_repeat_detect_does_not_grow_trend_rows_but_a_new_event_does(repository) -> None:
    config = TrendSignalConfig(trend_persistence_novelty_threshold=0.10)
    trace_generator = TraceIDGenerator(vertical="ai", sequence_provider=repository.next_trace_sequence)
    ids = IdFactory(trace_generator)

    def run_detect(items: list[SourceItem]) -> tuple[list[TrendCandidate], int]:
        recent_trends = repository.list_trends()
        brain = RealTrendBrain({}, {"s": 1.0}, recent_trends, signal_config=config, now=NOW)
        candidates = brain.detect(items, "ai", ids)
        to_persist, skipped = partition_trends_by_novelty(
            candidates, config.trend_persistence_novelty_threshold
        )
        for candidate in to_persist:
            repository.save_trend(candidate)
        return to_persist, skipped

    round1_items = [_item("a", "New LLM release from a research lab")]

    persisted1, skipped1 = run_detect(round1_items)
    assert len(persisted1) == 1
    assert skipped1 == 0
    assert len(repository.list_trends()) == 1

    # Same SourceItems again: no crash (no UNIQUE errors), no row growth.
    persisted2, skipped2 = run_detect(round1_items)
    assert persisted2 == []
    assert skipped2 == 1
    assert len(repository.list_trends()) == 1

    # A third identical run: still no growth, still safe.
    persisted3, skipped3 = run_detect(round1_items)
    assert persisted3 == []
    assert skipped3 == 1
    assert len(repository.list_trends()) == 1

    # A genuinely new, unrelated event must still persist.
    round4_items = [_item("b", "Robotics startup unveils new warehouse robot", minutes_ago=1)]
    persisted4, skipped4 = run_detect(round4_items)
    assert len(persisted4) == 1
    assert skipped4 == 0
    assert len(repository.list_trends()) == 2

    # Existing rows are untouched by any of the above.
    topics = {t.topic for t in repository.list_trends()}
    assert topics == {"New LLM release from a research lab", "Robotics startup unveils new warehouse robot"}
