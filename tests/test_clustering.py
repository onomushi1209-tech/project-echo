from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.models.source import SourceItem
from echo.trend.clustering import cluster_source_items
from echo.trend.signal_config import TrendSignalConfig

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = TrendSignalConfig()


def _item(source_key: str, title: str, minutes_ago: int = 0, content: str = "") -> SourceItem:
    return SourceItem(
        source_id=f"{source_key}-{title[:10]}-{minutes_ago}",
        source_key=source_key,
        url=f"https://example.com/{source_key}/{minutes_ago}",
        source_name=source_key,
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content=content,
        language="en",
        vertical="ai",
    )


def test_similar_titles_within_time_window_cluster_together() -> None:
    items = [
        _item("a", "OpenAI releases new reasoning model GPT update", minutes_ago=5),
        _item("b", "OpenAI releases updated reasoning model GPT release", minutes_ago=20),
    ]
    clusters = cluster_source_items(items, CONFIG)
    assert len(clusters) == 1
    assert len(clusters[0].items) == 2


def test_dissimilar_titles_form_separate_clusters() -> None:
    items = [
        _item("a", "OpenAI releases new reasoning model", minutes_ago=5),
        _item("b", "Robotics startup unveils warehouse robot", minutes_ago=10),
    ]
    clusters = cluster_source_items(items, CONFIG)
    assert len(clusters) == 2


def test_similar_titles_outside_time_window_do_not_cluster() -> None:
    config = TrendSignalConfig(cluster_time_window_hours=1.0)
    items = [
        _item("a", "OpenAI releases new reasoning model GPT update", minutes_ago=0),
        _item("b", "OpenAI releases updated reasoning model GPT release", minutes_ago=600),
    ]
    clusters = cluster_source_items(items, config)
    assert len(clusters) == 2


def test_cluster_representative_is_earliest_item() -> None:
    items = [
        _item("a", "Story breaks first version headline", minutes_ago=5),
        _item("b", "Story breaks first version headline update", minutes_ago=60),
    ]
    clusters = cluster_source_items(items, CONFIG)
    assert len(clusters) == 1
    assert clusters[0].representative.source_id == items[1].source_id  # 60 min ago = earliest


def test_empty_input_produces_no_clusters() -> None:
    assert cluster_source_items([], CONFIG) == []


def test_single_item_produces_single_single_item_cluster() -> None:
    clusters = cluster_source_items([_item("a", "Solo headline about something")], CONFIG)
    assert len(clusters) == 1
    assert len(clusters[0].items) == 1


def test_shared_entity_terms_help_cluster_short_titles() -> None:
    """Two differently-worded headlines sharing capitalized entity terms
    (and only middling plain word overlap) should still cluster thanks to
    the entity-term similarity component -- not just title-token overlap
    alone. (Entity extraction skips each title's first word, so the
    entities appear mid-sentence here, not as the opening word.)"""
    items = [
        _item("a", "Tech giant Nvidia unveils Rubin platform today", minutes_ago=1),
        _item("b", "Sources confirm Rubin platform launch from Nvidia", minutes_ago=15),
    ]
    clusters = cluster_source_items(items, CONFIG)
    assert len(clusters) == 1


def test_clustering_is_deterministic_across_runs() -> None:
    items = [
        _item("a", "OpenAI releases new reasoning model", minutes_ago=5),
        _item("b", "Robotics startup unveils warehouse robot", minutes_ago=10),
        _item("c", "OpenAI reasoning model release confirmed", minutes_ago=20),
    ]
    first_run = cluster_source_items(list(items), CONFIG)
    second_run = cluster_source_items(list(items), CONFIG)

    first_shape = sorted(sorted(i.source_id for i in c.items) for c in first_run)
    second_shape = sorted(sorted(i.source_id for i in c.items) for c in second_run)
    assert first_shape == second_shape
