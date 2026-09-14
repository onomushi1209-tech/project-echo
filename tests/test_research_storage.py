"""STEP 3 storage tests: ResearchPacket/claim/evidence/conflict
persistence, traceability, and additive schema migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from echo.brains.real_research_brain import RealResearchBrain
from echo.core.ids import IdFactory
from echo.core.trace import TraceIDGenerator
from echo.models.enums import ReliabilityTier
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.evidence import SourceRegistryInfo
from echo.storage.db import init_db

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

REGISTRY = {
    "official_blog": SourceRegistryInfo(name="Official Blog", reliability_tier=ReliabilityTier.A, is_primary_source=True),
    "news_a": SourceRegistryInfo(name="News A", reliability_tier=ReliabilityTier.B, is_primary_source=False),
}


def _item(source_id: str, source_key: str, title: str, minutes_ago: int = 5) -> SourceItem:
    return SourceItem(
        source_id=source_id, source_key=source_key, url=f"https://{source_key}.example.com/{source_id}",
        source_name=source_key, title=title, published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW, content="", language="en", vertical="ai",
    )


def _researched_packet(repository):
    sources = [
        _item("s1", "official_blog", "Product X released today", minutes_ago=5),
        _item("s2", "news_a", "Product X release delayed", minutes_ago=8),
    ]
    trend = TrendCandidate(
        trend_id="trend-storage", trace_id="ECHO-AI-20260809-000001", topic=sources[0].title,
        sources=[s.source_id for s in sources], detected_at=NOW, velocity=0.5, novelty=1.0,
        relevance=1.0, vertical="ai",
    )
    repository.save_trend(trend)
    trace_gen = TraceIDGenerator(vertical="ai", sequence_provider=repository.next_trace_sequence)
    ids = IdFactory(trace_gen)
    brain = RealResearchBrain(source_registry_info=REGISTRY, now=NOW)
    packet = brain.research(trend, sources, ids)
    return trend, packet


def test_save_and_get_research_round_trips(repository) -> None:
    _, packet = _researched_packet(repository)
    repository.save_research(packet)

    reloaded = repository.get_research(packet.research_id)

    assert reloaded is not None
    assert reloaded.research_id == packet.research_id
    assert reloaded.research_status == packet.research_status
    assert reloaded.confidence == packet.confidence
    assert reloaded.primary_source_present == packet.primary_source_present
    assert reloaded.independent_source_count == packet.independent_source_count


def test_claims_persist_and_are_listable(repository) -> None:
    _, packet = _researched_packet(repository)
    repository.save_research(packet)

    claims = repository.list_claims_by_research(packet.research_id)

    assert len(claims) == len(packet.claims)
    assert claims[0].claim_id == packet.claims[0].claim_id
    assert claims[0].status == packet.claims[0].status


def test_evidence_persists_and_is_listable(repository) -> None:
    _, packet = _researched_packet(repository)
    repository.save_research(packet)

    evidence = repository.list_evidence_by_research(packet.research_id)

    assert len(evidence) == len(packet.evidence)
    ids = {e.evidence_id for e in evidence}
    assert ids == {e.evidence_id for e in packet.evidence}


def test_conflicts_persist_and_are_listable(repository) -> None:
    _, packet = _researched_packet(repository)
    repository.save_research(packet)

    conflicts = repository.list_conflicts_by_research(packet.research_id)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "status_keyword"


def test_get_research_by_trend_returns_latest_run(repository) -> None:
    trend, packet1 = _researched_packet(repository)
    repository.save_research(packet1)

    trace_gen = TraceIDGenerator(vertical="ai", sequence_provider=repository.next_trace_sequence)
    ids = IdFactory(trace_gen)
    packet2 = RealResearchBrain(source_registry_info=REGISTRY, now=NOW).research(
        trend, [_item("s1", "official_blog", "Product X released today", minutes_ago=5),
                _item("s2", "news_a", "Product X release delayed", minutes_ago=8)], ids
    )
    repository.save_research(packet2)

    assert packet2.research_id != packet1.research_id
    latest = repository.get_research_by_trend("trend-storage")
    assert latest.research_id == packet2.research_id


def test_traceability_source_item_to_evidence_to_claim(repository) -> None:
    sources = [_item("s1", "official_blog", "Official breaking announcement made today", minutes_ago=1)]
    trend = TrendCandidate(
        trend_id="trend-trace", trace_id="ECHO-AI-20260809-000002", topic=sources[0].title,
        sources=["s1"], detected_at=NOW, velocity=0.5, novelty=1.0, relevance=1.0, vertical="ai",
    )
    repository.save_trend(trend)
    trace_gen = TraceIDGenerator(vertical="ai", sequence_provider=repository.next_trace_sequence)
    ids = IdFactory(trace_gen)
    packet = RealResearchBrain(source_registry_info=REGISTRY, now=NOW).research(trend, sources, ids)
    repository.save_research(packet)

    reloaded = repository.get_research(packet.research_id)
    evidence = reloaded.evidence[0]
    claim = reloaded.claims[0]

    assert evidence.source_item_id == "s1"  # traces back to the original SourceItem
    assert evidence.evidence_id in claim.evidence_ids  # claim references this evidence
    assert reloaded.trend_id == trend.trend_id
    assert reloaded.trace_id == trend.trace_id


def test_research_schema_migrates_additively_from_pre_step3_db(tmp_path: Path) -> None:
    """Simulates a pre-STEP3 `research` table (no claims/evidence/conflicts
    tables, no STEP3 scalar columns) and confirms init_db() upgrades it in
    place without losing the existing row."""
    db_path = tmp_path / "pre_step3.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE trends (
            trend_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL UNIQUE, vertical TEXT NOT NULL,
            topic TEXT NOT NULL, keywords_json TEXT NOT NULL, sources_json TEXT NOT NULL,
            detected_at TEXT NOT NULL, velocity REAL NOT NULL, novelty REAL NOT NULL, relevance REAL NOT NULL
        );
        CREATE TABLE research (
            research_id TEXT PRIMARY KEY, trend_id TEXT NOT NULL REFERENCES trends (trend_id),
            trace_id TEXT NOT NULL, summary TEXT NOT NULL, key_facts_json TEXT NOT NULL,
            sources_json TEXT NOT NULL, source_quality REAL NOT NULL,
            conflicting_information INTEGER NOT NULL, confidence REAL NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO trends (trend_id, trace_id, vertical, topic, keywords_json, sources_json, "
        "detected_at, velocity, novelty, relevance) VALUES "
        "('trend-legacy', 'ECHO-AI-20260101-000001', 'ai', 'Legacy topic', '[]', '[]', "
        "'2026-01-01T00:00:00+00:00', 0.5, 0.5, 0.5)"
    )
    conn.execute(
        "INSERT INTO research (research_id, trend_id, trace_id, summary, key_facts_json, sources_json, "
        "source_quality, conflicting_information, confidence) VALUES "
        "('research-legacy', 'trend-legacy', 'ECHO-AI-20260101-000001', 'Legacy summary', '[]', '[]', "
        "0.5, 0, 0.5)"
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    init_db(db_path)  # repeat: must be a no-op

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(research)")]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    legacy_row = conn.execute("SELECT * FROM research WHERE research_id = 'research-legacy'").fetchone()
    conn.close()

    assert "primary_source_present" in cols
    assert "independent_source_count" in cols
    assert "research_status" in cols
    assert "researched_at" in cols
    assert "source_assessments_json" in cols
    assert {"research_claims", "research_evidence", "research_conflicts"} <= tables
    assert legacy_row["summary"] == "Legacy summary"  # existing data preserved
    assert legacy_row["research_status"] == "ready"  # additive default applied
