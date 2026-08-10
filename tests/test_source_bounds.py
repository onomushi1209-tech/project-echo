"""Source ingestion upper bounds (Pre-Commit Hardening): max_items_per_fetch
/ max_item_age_hours, enforced at the normalize/ingest boundary
(echo.source.ingest), never in a parser. See docs/SOURCE_INTELLIGENCE.md
"Ingestion upper bounds"."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.models.enums import ReliabilityTier, SourceType
from echo.models.source import SourceItem
from echo.source.config import SourceConfig
from echo.source.ingest import _apply_source_bounds, ingest_sources
from echo.source.http_client import FetchOutcome

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _source(**overrides) -> SourceConfig:
    fields = dict(
        id="test_feed",
        name="Test Feed",
        url="https://example.com/feed",
        source_type=SourceType.RSS,
        vertical="ai",
        reliability_tier=ReliabilityTier.A,
    )
    fields.update(overrides)
    return SourceConfig(**fields)


def _item(source_id: str, hours_ago: float, title: str = "Title") -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key="test_feed",
        url=f"https://example.com/{source_id}",
        source_name="Test Feed",
        title=title,
        published_at=NOW - timedelta(hours=hours_ago),
        retrieved_at=NOW,
        content="body",
        language="en",
        vertical="ai",
    )


def test_default_bounds_are_200_items_and_168_hours() -> None:
    source = _source()
    assert source.max_items_per_fetch == 200
    assert source.max_item_age_hours == 168


def test_items_older_than_max_age_are_filtered() -> None:
    source = _source(max_item_age_hours=24)
    items = [_item("fresh", hours_ago=1), _item("old", hours_ago=200)]

    kept, age_filtered, limit_filtered = _apply_source_bounds(items, source, NOW)

    assert [i.source_id for i in kept] == ["fresh"]
    assert age_filtered == 1
    assert limit_filtered == 0


def test_max_items_per_fetch_keeps_newest_items() -> None:
    source = _source(max_items_per_fetch=2, max_item_age_hours=None)
    items = [_item("oldest", hours_ago=10), _item("newest", hours_ago=1), _item("middle", hours_ago=5)]

    kept, age_filtered, limit_filtered = _apply_source_bounds(items, source, NOW)

    assert [i.source_id for i in kept] == ["newest", "middle"]
    assert limit_filtered == 1
    assert age_filtered == 0


def test_none_bounds_disable_filtering() -> None:
    source = _source(max_items_per_fetch=None, max_item_age_hours=None)
    items = [_item(f"item{i}", hours_ago=i * 100) for i in range(10)]

    kept, age_filtered, limit_filtered = _apply_source_bounds(items, source, NOW)

    assert len(kept) == 10
    assert age_filtered == 0
    assert limit_filtered == 0


def test_source_specific_override_differs_from_default() -> None:
    strict = _source(id="strict", max_items_per_fetch=1, max_item_age_hours=1)
    lenient = _source(id="lenient", max_items_per_fetch=None, max_item_age_hours=None)
    items = [_item("a", hours_ago=0.5), _item("b", hours_ago=2)]

    strict_kept, strict_age_filtered, _ = _apply_source_bounds(items, strict, NOW)
    lenient_kept, lenient_age_filtered, _ = _apply_source_bounds(items, lenient, NOW)

    assert len(strict_kept) == 1
    assert strict_age_filtered == 1
    assert len(lenient_kept) == 2
    assert lenient_age_filtered == 0


def test_missing_timestamp_item_is_never_age_filtered() -> None:
    """An item whose published_at fell back to retrieved_at (missing/
    malformed timestamp -- see echo.source.normalize) has age 0 at
    normalize time and must never be dropped by the age bound: this is
    what keeps the bound consistent with the existing fallback policy."""
    source = _source(max_item_age_hours=1)
    fallback_item = _item("fallback", hours_ago=0)  # published_at == retrieved_at == NOW

    kept, age_filtered, _ = _apply_source_bounds([fallback_item], source, NOW)

    assert len(kept) == 1
    assert age_filtered == 0


def test_bounds_output_is_deterministic_for_same_input() -> None:
    source = _source(max_items_per_fetch=2, max_item_age_hours=None)
    items = [_item("a", hours_ago=5), _item("b", hours_ago=1), _item("c", hours_ago=3)]

    first, _, _ = _apply_source_bounds(list(items), source, NOW)
    second, _, _ = _apply_source_bounds(list(items), source, NOW)

    assert [i.source_id for i in first] == [i.source_id for i in second] == ["b", "c"]


def test_ingest_sources_reports_age_and_limit_filtered_counts(repository, monkeypatch) -> None:
    """End-to-end: a 5-item feed capped to 2 items via max_items_per_fetch
    is reflected in SourceIngestReport's observability counters."""
    from echo.source import ingest as ingest_module

    # Distinct-enough titles so the dedup layer's near-duplicate check
    # (title token-overlap) doesn't collapse them -- this test is about the
    # item-limit bound, not deduplication.
    headlines = [
        "Research lab unveils new benchmark suite",
        "Startup raises funding for robotics platform",
        "Regulator proposes new safety guidelines",
        "Conference announces keynote speaker lineup",
        "Open source project reaches major milestone",
    ]
    items_xml = "".join(
        f"<item><title>{headline}</title><link>https://example.com/story-{i}</link>"
        f'<pubDate>{(NOW - timedelta(hours=i)).strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate></item>'
        for i, headline in enumerate(headlines)
    )
    body = f'<rss version="2.0"><channel>{items_xml}</channel></rss>'.encode()

    def fake_fetch(url, **kwargs):
        return FetchOutcome(
            ok=True, url=url, status_code=200, content_type="application/rss+xml", body=body, attempts=1
        )

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)

    source = _source(
        id="capped_source", url="https://example.com/feed", max_items_per_fetch=2, max_item_age_hours=None
    )
    report = ingest_sources([source], repository, now=NOW)

    source_report = report.per_source[0]
    assert source_report.items_fetched == 5
    assert source_report.items_normalized == 5
    assert source_report.items_age_filtered == 0
    assert source_report.items_item_limit_filtered == 3
    assert source_report.items_stored == 2
    assert report.total_item_limit_filtered == 3
