from __future__ import annotations

from datetime import datetime, timezone

from echo.models.source import SourceItem
from echo.research.independence import distinct_source_keys, independent_source_count

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _item(source_id: str, source_key: str) -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key=source_key,
        url=f"https://example.com/{source_id}",
        source_name=source_key,
        title="Title",
        published_at=NOW,
        retrieved_at=NOW,
        content="",
        language="en",
        vertical="ai",
    )


def test_same_source_key_multiple_items_counts_as_one() -> None:
    items = [_item("a", "s1"), _item("b", "s1"), _item("c", "s1")]
    assert independent_source_count(items) == 1


def test_distinct_source_keys_count_independently() -> None:
    items = [_item("a", "s1"), _item("b", "s2"), _item("c", "s3")]
    assert independent_source_count(items) == 3


def test_mixed_sources_counts_distinct_keys_only() -> None:
    items = [_item("a", "s1"), _item("b", "s1"), _item("c", "s2")]
    assert independent_source_count(items) == 2


def test_empty_items_is_zero() -> None:
    assert independent_source_count([]) == 0


def test_distinct_source_keys_returns_the_set() -> None:
    items = [_item("a", "s1"), _item("b", "s1"), _item("c", "s2")]
    assert distinct_source_keys(items) == {"s1", "s2"}
