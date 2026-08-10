from __future__ import annotations

from datetime import datetime, timezone

from echo.models.enums import ReliabilityTier, SourceType
from echo.source.config import SourceConfig
from echo.source.normalize import normalize_record
from echo.source.records import RawRecord

RETRIEVED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _source(**overrides) -> SourceConfig:
    fields = dict(
        id="test_feed",
        name="Test Feed",
        url="https://example.com/feed",
        source_type=SourceType.RSS,
        vertical="ai",
        reliability_tier=ReliabilityTier.A,
        language="en",
    )
    fields.update(overrides)
    return SourceConfig(**fields)


def test_normalize_produces_valid_source_item() -> None:
    record = RawRecord(
        title="A Title",
        url="https://example.com/article",
        published_at_raw="Fri, 07 Aug 2026 15:20:00 GMT",
        summary="<p>Some <b>bold</b> summary.</p>",
    )
    result = normalize_record(record, _source(), RETRIEVED_AT)

    assert result.item is not None
    assert result.dropped_reason is None
    assert result.item.title == "A Title"
    assert result.item.source_key == "test_feed"
    assert result.item.vertical == "ai"
    assert result.item.language == "en"
    assert "bold" in result.item.content
    assert "<b>" not in result.item.content


def test_normalize_parses_rfc822_timestamp_as_timezone_aware() -> None:
    record = RawRecord(
        title="A Title", url="https://example.com/a", published_at_raw="Fri, 07 Aug 2026 15:20:00 GMT"
    )
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is not None
    assert result.item.published_at.tzinfo is not None
    assert result.item.published_at.year == 2026
    assert result.used_fallback_timestamp is False


def test_normalize_parses_iso8601_timestamp_with_z_suffix() -> None:
    record = RawRecord(title="A Title", url="https://example.com/a", published_at_raw="2026-08-08T09:00:00Z")
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is not None
    assert result.item.published_at.tzinfo is not None
    assert result.used_fallback_timestamp is False


def test_normalize_falls_back_to_retrieved_at_on_missing_timestamp() -> None:
    record = RawRecord(title="A Title", url="https://example.com/a", published_at_raw=None)
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is not None
    assert result.item.published_at == RETRIEVED_AT
    assert result.used_fallback_timestamp is True


def test_normalize_falls_back_to_retrieved_at_on_malformed_timestamp() -> None:
    """Bad dates must never crash the batch -- they degrade gracefully."""
    record = RawRecord(title="A Title", url="https://example.com/a", published_at_raw="not a real date")
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is not None
    assert result.item.published_at == RETRIEVED_AT
    assert result.used_fallback_timestamp is True


def test_normalize_drops_record_missing_title() -> None:
    record = RawRecord(title="", url="https://example.com/a", published_at_raw=None)
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is None
    assert result.dropped_reason == "missing_title"


def test_normalize_drops_record_missing_url() -> None:
    record = RawRecord(title="A Title", url="", published_at_raw=None)
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is None
    assert result.dropped_reason == "missing_url"


def test_normalize_drops_record_with_invalid_url_without_raising() -> None:
    record = RawRecord(title="A Title", url="not-a-valid-url", published_at_raw=None)
    result = normalize_record(record, _source(), RETRIEVED_AT)
    assert result.item is None
    assert result.dropped_reason is not None
    assert "invalid_source_item" in result.dropped_reason


def test_normalize_stable_source_id_for_same_guid() -> None:
    record = RawRecord(title="A Title", url="https://example.com/a", published_at_raw=None, guid="stable-guid")
    first = normalize_record(record, _source(), RETRIEVED_AT)
    second = normalize_record(record, _source(), RETRIEVED_AT)
    assert first.item is not None and second.item is not None
    assert first.item.source_id == second.item.source_id
