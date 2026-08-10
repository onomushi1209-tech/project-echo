from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.brains.real_trend_brain import RealTrendBrain
from echo.core.ids import IdFactory
from echo.core.trace import InMemorySequenceProvider, TraceIDGenerator
from echo.models.source import SourceItem
from echo.trend.signal_config import TrendSignalConfig

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

TOPIC_KEYWORDS = {
    "llm": ["LLM", "large language model"],
    "robotics": ["robot", "robotics"],
}
SOURCE_RELIABILITY = {"source_a": 1.0, "source_b": 0.7, "source_c": 0.4}


def _ids() -> IdFactory:
    generator = TraceIDGenerator(vertical="ai", sequence_provider=InMemorySequenceProvider())
    return IdFactory(generator)


def _item(source_key: str, title: str, minutes_ago: int, content: str = "") -> SourceItem:
    return SourceItem(
        source_id=f"{source_key}-{minutes_ago}-{abs(hash(title)) % 10_000}",
        source_key=source_key,
        url=f"https://{source_key}.example.com/{minutes_ago}",
        source_name=source_key,
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content=content,
        language="en",
        vertical="ai",
    )


def test_detect_returns_empty_list_for_no_sources() -> None:
    brain = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], now=NOW)
    assert brain.detect([], "ai", _ids()) == []


def test_detect_produces_one_candidate_per_cluster() -> None:
    sources = [
        _item("source_a", "New LLM release from a research lab", minutes_ago=5, content="large language model"),
        _item("source_b", "Robotics startup unveils new warehouse robot", minutes_ago=10, content="robot demo"),
    ]
    brain = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], now=NOW)
    candidates = brain.detect(sources, "ai", _ids())
    assert len(candidates) == 2


def test_detect_merges_multi_source_confirmation_into_one_candidate() -> None:
    sources = [
        _item("source_a", "New LLM release from a major research lab today", minutes_ago=5, content="large language model"),
        _item("source_b", "New LLM release confirmed by a major research lab", minutes_ago=8, content="large language model"),
        _item("source_c", "New LLM release from major research lab reported", minutes_ago=12, content="large language model"),
    ]
    brain = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], now=NOW)
    candidates = brain.detect(sources, "ai", _ids())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_count == 3
    assert candidate.cross_source_confirmation > 0.0
    assert set(candidate.sources) == {item.source_id for item in sources}


def test_detect_assigns_distinct_trace_ids_per_cluster() -> None:
    sources = [
        _item("source_a", "New LLM release from a research lab", minutes_ago=5, content="large language model"),
        _item("source_b", "Robotics startup unveils new warehouse robot", minutes_ago=10, content="robot demo"),
    ]
    brain = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], now=NOW)
    candidates = brain.detect(sources, "ai", _ids())
    trace_ids = {c.trace_id for c in candidates}
    assert len(trace_ids) == len(candidates)
    assert all(t.startswith("ECHO-AI-") for t in trace_ids)


def test_detect_relevance_reflects_topic_keyword_matches() -> None:
    sources = [
        _item("source_a", "New LLM release from a research lab", minutes_ago=5, content="large language model transformer"),
        _item("source_b", "Quarterly earnings beat analyst expectations", minutes_ago=5, content="revenue growth"),
    ]
    brain = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], now=NOW)
    candidates = {c.topic: c for c in brain.detect(sources, "ai", _ids())}

    assert candidates["New LLM release from a research lab"].relevance > 0.0
    assert candidates["Quarterly earnings beat analyst expectations"].relevance == 0.0


def test_detect_source_quality_uses_injected_reliability_map() -> None:
    sources = [_item("source_a", "Solo headline about something new", minutes_ago=1)]
    brain = RealTrendBrain(TOPIC_KEYWORDS, {"source_a": 1.0}, [], now=NOW)
    candidate = brain.detect(sources, "ai", _ids())[0]
    assert candidate.source_quality == 1.0


def test_detect_is_deterministic_given_fixed_now() -> None:
    sources = [
        _item("source_a", "New LLM release from a research lab", minutes_ago=5, content="large language model"),
        _item("source_b", "Robotics startup unveils new warehouse robot", minutes_ago=10, content="robot demo"),
    ]
    config = TrendSignalConfig()
    brain1 = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], signal_config=config, now=NOW)
    brain2 = RealTrendBrain(TOPIC_KEYWORDS, SOURCE_RELIABILITY, [], signal_config=config, now=NOW)

    result1 = [(c.topic, c.velocity, c.relevance, c.freshness) for c in brain1.detect(list(sources), "ai", _ids())]
    result2 = [(c.topic, c.velocity, c.relevance, c.freshness) for c in brain2.detect(list(sources), "ai", _ids())]
    assert result1 == result2
