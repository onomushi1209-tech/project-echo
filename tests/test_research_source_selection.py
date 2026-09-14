from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.config import ResearchConfig
from echo.research.source_selection import select_relevant_sources
from echo.trend.signal_config import TrendSignalConfig
import echo.research.source_selection as selection_module

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
SIGNAL_CONFIG = TrendSignalConfig()
RESEARCH_CONFIG = ResearchConfig()


def _item(source_id: str, source_key: str, title: str, minutes_ago: int = 5) -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key=source_key,
        url=f"https://{source_key}.example.com/{source_id}",
        source_name=source_key,
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content="",
        language="en",
        vertical="ai",
    )


def _trend(source_ids: list[str], topic: str) -> TrendCandidate:
    return TrendCandidate(
        trend_id="trend-1",
        trace_id="ECHO-AI-20260809-000001",
        topic=topic,
        sources=source_ids,
        detected_at=NOW,
        velocity=0.5,
        novelty=1.0,
        relevance=1.0,
        vertical="ai",
    )


def test_direct_matches_are_always_selected() -> None:
    items = [_item("a", "s1", "Story about a launch", minutes_ago=5)]
    trend = _trend(["a"], "Story about a launch")

    result = select_relevant_sources(trend, items, SIGNAL_CONFIG, RESEARCH_CONFIG)

    assert [i.source_id for i in result.selected] == ["a"]
    assert result.sources_selected == 1


def test_expands_to_a_later_ingested_item_about_the_same_event() -> None:
    # Reuses echo.trend.clustering (STEP 2, unstemmed token-overlap) as-is
    # -- wording chosen to share enough exact tokens for that module's own
    # similarity threshold, matching its own test fixtures' style.
    direct = _item("a", "s1", "OpenAI releases new reasoning model GPT update", minutes_ago=5)
    expansion = _item("b", "s2", "OpenAI releases updated reasoning model GPT release", minutes_ago=8)
    trend = _trend(["a"], direct.title)

    result = select_relevant_sources(trend, [direct, expansion], SIGNAL_CONFIG, RESEARCH_CONFIG)

    selected_ids = {i.source_id for i in result.selected}
    assert selected_ids == {"a", "b"}


def test_irrelevant_source_is_excluded() -> None:
    direct = _item("a", "s1", "Research lab unveils new model today", minutes_ago=5)
    unrelated = _item("z", "s3", "Quarterly earnings beat analyst expectations", minutes_ago=6)
    trend = _trend(["a"], direct.title)

    result = select_relevant_sources(trend, [direct, unrelated], SIGNAL_CONFIG, RESEARCH_CONFIG)

    selected_ids = {i.source_id for i in result.selected}
    assert selected_ids == {"a"}
    assert "z" not in selected_ids


def test_item_far_outside_time_window_is_excluded() -> None:
    direct = _item("a", "s1", "Research lab unveils new model today", minutes_ago=5)
    far_away = _item(
        "b", "s2", "Research lab has unveiled a new model", minutes_ago=60 * 24 * 30
    )  # 30 days
    trend = _trend(["a"], direct.title)

    result = select_relevant_sources(trend, [direct, far_away], SIGNAL_CONFIG, RESEARCH_CONFIG)

    selected_ids = {i.source_id for i in result.selected}
    assert selected_ids == {"a"}


def test_no_trend_sources_returns_empty_selection() -> None:
    items = [_item("a", "s1", "Unrelated story", minutes_ago=5)]
    trend = _trend([], "Some topic with no matched sources")

    result = select_relevant_sources(trend, items, SIGNAL_CONFIG, RESEARCH_CONFIG)

    assert result.selected == []
    assert result.sources_considered == 0
    assert result.sources_selected == 0


def test_selection_capped_at_max_research_sources() -> None:
    direct = _item("a", "s0", "Widely covered breaking story today", minutes_ago=1)
    others = [
        _item(f"s{i}", f"source{i}", "Widely covered breaking story reported", minutes_ago=2 + i)
        for i in range(10)
    ]
    trend = _trend(["a"], direct.title)
    config = ResearchConfig(max_research_sources=3)

    result = select_relevant_sources(trend, [direct, *others], SIGNAL_CONFIG, config)

    assert result.sources_selected <= 3
    assert len(result.selected) <= 3


def test_selection_keeps_newest_items_first() -> None:
    direct = _item("a", "s0", "Breaking story unfolding now", minutes_ago=1)
    older = _item("b", "s1", "Breaking story unfolding currently", minutes_ago=5)
    newer = _item("c", "s2", "Breaking story unfolding presently", minutes_ago=0)
    trend = _trend(["a"], direct.title)

    result = select_relevant_sources(trend, [direct, older, newer], SIGNAL_CONFIG, RESEARCH_CONFIG)

    published_times = [item.published_at for item in result.selected]
    assert published_times == sorted(published_times, reverse=True)


def test_large_pool_is_bounded_before_clustering_with_stable_priority(monkeypatch):
    direct = _item("anchor", "s0", "Widely covered breaking story today", minutes_ago=500)
    items = [direct] + [_item(f"item-{i:04}", f"source-{i}", direct.title, minutes_ago=1) for i in range(500)]
    original = selection_module.cluster_source_items
    calls = []
    def observe(pool, config):
        calls.append([item.source_id for item in pool])
        return original(pool, config)
    monkeypatch.setattr(selection_module, "cluster_source_items", observe)
    config = ResearchConfig(max_research_candidates=7, max_research_sources=3)
    results = [select_relevant_sources(_trend([direct.source_id], direct.title), pool, SIGNAL_CONFIG, config)
               for pool in (items, list(reversed(items)), items[100:] + items[:100])]
    assert calls[0] == calls[1] == calls[2]
    assert len(calls[0]) == 7
    assert calls[0][0] == "anchor"  # direct anchors precede newer expansions
    assert calls[0][1:] == [f"item-{i:04}" for i in range(6)]
    assert all(r.sources_considered == 501 and r.candidates_clustered == 7 and r.candidates_truncated == 494 for r in results)
    assert all([i.source_id for i in r.selected] == ["item-0000", "item-0001", "item-0002"] for r in results)


def test_direct_anchors_over_cap_do_not_reenter_selection(monkeypatch):
    items = [_item(f"item-{i:02}", "s0", "Widely covered breaking story today", minutes_ago=i) for i in range(30)]
    original = selection_module.cluster_source_items
    counts = []
    def observe(pool, config):
        counts.append(len(pool))
        return original(pool, config)
    monkeypatch.setattr(selection_module, "cluster_source_items", observe)
    result = select_relevant_sources(
        _trend([i.source_id for i in items], items[0].title), items, SIGNAL_CONFIG,
        ResearchConfig(max_research_candidates=4, max_research_sources=10),
    )
    assert counts == [4]
    assert [i.source_id for i in result.selected] == [f"item-{i:02}" for i in range(4)]


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "20"])
@pytest.mark.parametrize("field", ["max_research_candidates", "max_research_sources"])
def test_invalid_selection_bounds_fail_fast(field, value):
    with pytest.raises(ValueError, match=field):
        ResearchConfig(**{field: value})


def test_precluster_environment_setting_is_supported(monkeypatch):
    from echo.config.settings import Settings
    monkeypatch.setenv("ECHO_MAX_RESEARCH_CANDIDATES", "37")
    assert Settings.load().research_config().max_research_candidates == 37
    monkeypatch.setenv("ECHO_MAX_RESEARCH_CANDIDATES", "0")
    with pytest.raises(ValueError, match="max_research_candidates"):
        Settings.load().research_config()
