"""Ingest orchestration tests. echo.source.ingest's `fetch` binding is
monkeypatched so nothing here touches the network -- fully offline."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from echo.models.enums import FetchStatus, ReliabilityTier, SourceType
from echo.source import ingest as ingest_module
from echo.source.config import SourceConfig
from echo.source.http_client import FetchOutcome
from echo.source.ingest import ingest_sources

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

RSS_A = b"""<rss version="2.0"><channel>
    <item><title>Story One About AI</title><link>https://a.example.com/story-one</link>
    <pubDate>Fri, 07 Aug 2026 15:20:00 GMT</pubDate><description>Body one.</description></item>
    <item><title>Story Two About Robots</title><link>https://a.example.com/story-two</link>
    <pubDate>Fri, 07 Aug 2026 16:00:00 GMT</pubDate><description>Body two.</description></item>
</channel></rss>"""

RSS_B_DUPLICATE = b"""<rss version="2.0"><channel>
    <item><title>Story One About AI</title><link>https://b.example.com/story-one-mirror</link>
    <pubDate>Fri, 07 Aug 2026 15:25:00 GMT</pubDate><description>Body one.</description></item>
</channel></rss>"""


def _source(source_id: str, url: str, source_type: SourceType = SourceType.RSS) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name=source_id,
        url=url,
        source_type=source_type,
        vertical="ai",
        reliability_tier=ReliabilityTier.A,
    )


def test_ingest_dedups_across_sources_within_one_run(repository, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        if url == "https://a.example.com/feed":
            return FetchOutcome(ok=True, url=url, status_code=200, content_type="application/rss+xml", body=RSS_A, attempts=1)
        if url == "https://b.example.com/feed":
            return FetchOutcome(
                ok=True, url=url, status_code=200, content_type="application/rss+xml", body=RSS_B_DUPLICATE, attempts=1
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)

    sources = [_source("source_a", "https://a.example.com/feed"), _source("source_b", "https://b.example.com/feed")]
    report = ingest_sources(sources, repository, now=NOW)

    assert report.total_stored == 2  # 2 unique items from A; B's item is a duplicate of A's first
    assert report.total_deduplicated == 1
    assert len(repository.list_source_items()) == 2


def test_ingest_isolates_one_source_failure_from_others(repository, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        if url == "https://ok.example.com/feed":
            return FetchOutcome(ok=True, url=url, status_code=200, content_type="application/rss+xml", body=RSS_A, attempts=1)
        return FetchOutcome(ok=False, url=url, error_type="timeout", message="request timed out", attempts=3)

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)

    sources = [
        _source("source_fail", "https://down.example.com/feed"),
        _source("source_ok", "https://ok.example.com/feed"),
    ]
    report = ingest_sources(sources, repository, now=NOW)

    statuses = {r.source_key: r.status for r in report.per_source}
    assert statuses["source_fail"] == FetchStatus.FAILED
    assert statuses["source_ok"] == FetchStatus.SUCCESS
    assert report.total_stored == 2  # source_ok's items still got ingested despite source_fail

    failures = repository.list_source_failures()
    assert len(failures) == 1
    assert failures[0]["source_key"] == "source_fail"
    assert failures[0]["error_type"] == "timeout"


def test_ingest_persists_fetch_run_per_source(repository, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        return FetchOutcome(ok=True, url=url, status_code=200, content_type="application/rss+xml", body=RSS_A, attempts=1)

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)

    ingest_sources([_source("source_a", "https://a.example.com/feed")], repository, now=NOW)

    runs = repository.list_source_fetch_runs()
    assert len(runs) == 1
    assert runs[0]["source_key"] == "source_a"
    assert runs[0]["status"] == "success"
    assert runs[0]["items_fetched"] == 2


def test_ingest_static_fixture_source_never_touches_network(repository, monkeypatch, tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "fixture_source.json").write_text(
        '{"items": [{"title": "Fixture Item", "url": "https://example.com/fixture-item", '
        '"published_at": "2026-08-08T00:00:00Z", "summary": "body"}]}',
        encoding="utf-8",
    )

    def fake_fetch(url, **kwargs):
        raise AssertionError("STATIC_FIXTURE sources must never call the network fetch layer")

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)

    sources = [_source("fixture_source", "https://example.com/unused", source_type=SourceType.STATIC_FIXTURE)]
    report = ingest_sources(sources, repository, fixtures_dir=fixtures_dir, now=NOW)

    assert report.total_stored == 1
    assert report.per_source[0].status == FetchStatus.SUCCESS


def test_ingest_missing_fixtures_dir_is_an_isolated_failure(repository) -> None:
    sources = [_source("fixture_source", "https://example.com/unused", source_type=SourceType.STATIC_FIXTURE)]
    report = ingest_sources(sources, repository, fixtures_dir=None, now=NOW)
    assert report.per_source[0].status == FetchStatus.FAILED


def test_ingest_re_running_is_idempotent_for_already_seen_items(repository, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        return FetchOutcome(ok=True, url=url, status_code=200, content_type="application/rss+xml", body=RSS_A, attempts=1)

    monkeypatch.setattr(ingest_module, "fetch", fake_fetch)
    sources = [_source("source_a", "https://a.example.com/feed")]

    first = ingest_sources(sources, repository, now=NOW)
    second = ingest_sources(sources, repository, now=NOW)

    assert first.total_stored == 2
    assert second.total_stored == 0
    assert second.total_deduplicated == 2


@pytest.mark.parametrize("age_hours,stored", [(167, 1), (168, 1), (169, 0)])
def test_injected_clock_preserves_production_age_boundary(repository, monkeypatch, age_hours, stored):
    monkeypatch.setattr(
        ingest_module, "fetch",
        lambda url: FetchOutcome(ok=True, url=url, body=RSS_B_DUPLICATE, attempts=1),
    )
    published = datetime(2026, 8, 7, 15, 25, tzinfo=timezone.utc)
    report = ingest_sources(
        [_source("source_b", "https://b.example.com/feed")], repository,
        now=published + timedelta(hours=age_hours),
    )
    assert report.total_stored == stored
    assert report.total_age_filtered == 1 - stored
