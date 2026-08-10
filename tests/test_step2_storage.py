from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.source.dedup import canonicalize_url, content_fingerprint
from echo.storage.db import get_connection, init_db
from echo.storage.repository import EchoRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_init_db_creates_step2_tables(db_path: Path) -> None:
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert {"source_items", "source_fetch_runs", "source_failures"} <= tables


def test_init_db_migrates_pre_step2_database_in_place(db_path: Path) -> None:
    """Simulates a database created by STEP 1 code (trends table without
    the STEP 2 columns) and verifies init_db() upgrades it additively,
    preserving existing rows."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE trends (
            trend_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL UNIQUE, vertical TEXT NOT NULL,
            topic TEXT NOT NULL, keywords_json TEXT NOT NULL, sources_json TEXT NOT NULL,
            detected_at TEXT NOT NULL, velocity REAL NOT NULL, novelty REAL NOT NULL, relevance REAL NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO trends VALUES ('t1','ECHO-AI-20260101-000001','ai','Old topic','[]','[]',"
        "'2026-01-01T00:00:00+00:00',0.5,0.5,0.5)"
    )
    conn.commit()
    conn.close()

    init_db(db_path)  # must migrate, not destroy

    conn = get_connection(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(trends)")}
        row = conn.execute("SELECT * FROM trends WHERE trend_id = 't1'").fetchone()
    finally:
        conn.close()

    assert {"freshness", "source_quality", "source_count", "cross_source_confirmation"} <= columns
    assert row["topic"] == "Old topic"
    assert row["freshness"] == 0.5
    assert row["source_count"] == 1


def test_init_db_migration_is_idempotent(db_path: Path) -> None:
    init_db(db_path)
    init_db(db_path)  # second call must not raise or duplicate columns
    conn = get_connection(db_path)
    try:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(trends)")]
    finally:
        conn.close()
    assert columns.count("freshness") == 1


def _source_item(source_id: str = "src-1", url: str = "https://example.com/a") -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key="test_feed",
        url=url,
        source_name="Test Feed",
        title="A Title",
        published_at=NOW,
        retrieved_at=NOW,
        content="body text",
        language="en",
        vertical="ai",
    )


def test_save_and_list_source_items_round_trip(repository: EchoRepository) -> None:
    item = _source_item()
    repository.save_source_item(
        item,
        canonical_url=canonicalize_url(str(item.url)),
        content_fingerprint=content_fingerprint(item.title, item.content),
    )

    items = repository.list_source_items()
    assert len(items) == 1
    assert items[0].source_id == "src-1"
    assert items[0].source_key == "test_feed"


def test_list_source_items_filters_by_vertical(repository: EchoRepository) -> None:
    ai_item = _source_item(source_id="src-ai", url="https://example.com/ai")
    repository.save_source_item(
        ai_item,
        canonical_url=canonicalize_url(str(ai_item.url)),
        content_fingerprint=content_fingerprint(ai_item.title, ai_item.content),
    )

    assert len(repository.list_source_items(vertical="ai")) == 1
    assert len(repository.list_source_items(vertical="tech")) == 0


def test_save_source_item_is_idempotent_on_same_id(repository: EchoRepository) -> None:
    item = _source_item()
    for _ in range(3):
        repository.save_source_item(
            item,
            canonical_url=canonicalize_url(str(item.url)),
            content_fingerprint=content_fingerprint(item.title, item.content),
        )
    assert len(repository.list_source_items()) == 1


def test_known_canonical_urls_and_fingerprints_are_queryable(repository: EchoRepository) -> None:
    item = _source_item()
    canonical = canonicalize_url(str(item.url))
    fingerprint = content_fingerprint(item.title, item.content)
    repository.save_source_item(item, canonical_url=canonical, content_fingerprint=fingerprint)

    assert canonical in repository.list_known_canonical_urls()
    assert fingerprint in repository.list_known_content_fingerprints()


def _trend_candidate(**overrides) -> TrendCandidate:
    fields = dict(
        trend_id="trend-1",
        trace_id="ECHO-AI-20260809-000001",
        topic="A detected trend",
        keywords=["a", "b"],
        sources=["src-1"],
        detected_at=NOW,
        velocity=0.6,
        novelty=0.8,
        relevance=0.7,
        vertical="ai",
        freshness=0.9,
        source_quality=0.75,
        source_count=3,
        cross_source_confirmation=0.5,
    )
    fields.update(overrides)
    return TrendCandidate(**fields)


def test_trend_candidate_step2_fields_round_trip(repository: EchoRepository) -> None:
    trend = _trend_candidate()
    repository.save_trend(trend)

    fetched = repository.get_trend(trend.trend_id)

    assert fetched is not None
    assert fetched.freshness == 0.9
    assert fetched.source_quality == 0.75
    assert fetched.source_count == 3
    assert fetched.cross_source_confirmation == 0.5


def test_trend_candidate_defaults_persist_when_using_dummy_style_construction(
    repository: EchoRepository,
) -> None:
    """A TrendCandidate built the STEP 1 way (no STEP 2 fields passed) must
    still save/load correctly with its defaults."""
    trend = TrendCandidate(
        trend_id="trend-legacy",
        trace_id="ECHO-AI-20260809-000002",
        topic="Legacy-style trend",
        detected_at=NOW,
        velocity=0.5,
        novelty=0.5,
        relevance=0.5,
        vertical="ai",
    )
    repository.save_trend(trend)

    fetched = repository.get_trend("trend-legacy")

    assert fetched is not None
    assert fetched.freshness == 0.5
    assert fetched.source_quality == 0.5
    assert fetched.source_count == 1
    assert fetched.cross_source_confirmation == 0.0
