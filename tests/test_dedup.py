from __future__ import annotations

from datetime import datetime, timezone

from echo.models.source import SourceItem
from echo.source.dedup import (
    Deduplicator,
    canonicalize_url,
    content_fingerprint,
    normalize_title,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _item(source_id: str, url: str, title: str, content: str = "body") -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key="test_feed",
        url=url,
        source_name="Test Feed",
        title=title,
        published_at=NOW,
        retrieved_at=NOW,
        content=content,
        language="en",
        vertical="ai",
    )


def test_canonicalize_url_strips_tracking_params_and_sorts_remaining() -> None:
    a = canonicalize_url("https://Example.com/Article/?utm_source=x&utm_medium=y&id=1")
    b = canonicalize_url("https://example.com/Article?id=1")
    assert a == b


def test_canonicalize_url_strips_default_port_and_trailing_slash() -> None:
    a = canonicalize_url("https://example.com:443/path/")
    b = canonicalize_url("https://example.com/path")
    assert a == b


def test_canonicalize_url_drops_fragment() -> None:
    a = canonicalize_url("https://example.com/path#section-2")
    b = canonicalize_url("https://example.com/path")
    assert a == b


def test_canonicalize_url_preserves_non_tracking_query_params() -> None:
    result = canonicalize_url("https://example.com/path?id=1&utm_campaign=x")
    assert "id=1" in result
    assert "utm_campaign" not in result


def test_normalize_title_strips_punctuation_and_case() -> None:
    assert normalize_title("State-of-the-Art Reasoning!") == "state of the art reasoning"


def test_content_fingerprint_stable_for_equivalent_text() -> None:
    a = content_fingerprint("Hello, World!", "Some body text.")
    b = content_fingerprint("hello world", "some body text")
    assert a == b


def test_content_fingerprint_differs_for_different_text() -> None:
    a = content_fingerprint("Title A", "Body A")
    b = content_fingerprint("Title B", "Body B")
    assert a != b


def test_deduplicator_keeps_first_item() -> None:
    dedup = Deduplicator()
    item = _item("s1", "https://example.com/a", "Unique Title")
    outcome = dedup.process(item)
    assert outcome.decision.value == "keep"


def test_deduplicator_flags_exact_duplicate_by_canonical_url() -> None:
    dedup = Deduplicator()
    first = _item("s1", "https://example.com/a?utm_source=x", "Title One")
    second = _item("s2", "https://example.com/a", "Title One (mirror)")

    dedup.process(first)
    outcome = dedup.process(second)

    assert outcome.decision.value == "exact_duplicate"


def test_deduplicator_flags_exact_duplicate_by_content_fingerprint() -> None:
    dedup = Deduplicator()
    first = _item("s1", "https://example.com/a", "Same Story", content="identical body")
    second = _item("s2", "https://example.com/b", "Same Story!!", content="identical body")

    dedup.process(first)
    outcome = dedup.process(second)

    assert outcome.decision.value == "exact_duplicate"


def test_deduplicator_flags_near_duplicate_by_title_overlap() -> None:
    dedup = Deduplicator(near_duplicate_threshold=0.6)
    first = _item("s1", "https://example.com/a", "New open weight language model release")
    second = _item(
        "s2", "https://example.com/b", "New open weight language model launch", content="different body"
    )

    dedup.process(first)
    outcome = dedup.process(second)

    assert outcome.decision.value == "near_duplicate"


def test_deduplicator_keeps_dissimilar_titles() -> None:
    dedup = Deduplicator()
    first = _item("s1", "https://example.com/a", "Robotics startup unveils warehouse robot")
    second = _item("s2", "https://example.com/b", "Quarterly earnings beat analyst expectations")

    dedup.process(first)
    outcome = dedup.process(second)

    assert outcome.decision.value == "keep"


def test_deduplicator_seeded_state_catches_cross_run_duplicates() -> None:
    seen_url = canonicalize_url("https://example.com/a")
    dedup = Deduplicator(seen_canonical_urls={seen_url})

    outcome = dedup.evaluate(_item("s1", "https://example.com/a", "Already Seen"))

    assert outcome.decision.value == "exact_duplicate"
