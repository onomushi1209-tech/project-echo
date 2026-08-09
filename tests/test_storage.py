from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from echo.models.draft import ContentDraft
from echo.models.enums import ContentType, DecisionType
from echo.models.research import ResearchPacket
from echo.models.review import ReviewDecision
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate
from echo.storage.db import init_db
from echo.storage.repository import EchoRepository

NOW = datetime.now(timezone.utc)

EXPECTED_TABLES = {
    "trace_sequences",
    "trends",
    "research",
    "scores",
    "drafts",
    "reviews",
    "published_posts",
    "performance",
}


def test_init_db_creates_expected_tables(db_path: Path) -> None:
    init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()

    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_init_db_is_idempotent(db_path: Path) -> None:
    init_db(db_path)
    init_db(db_path)  # must not raise


def test_next_trace_sequence_increments_and_isolates_by_vertical(repository: EchoRepository) -> None:
    day = date(2026, 8, 9)

    assert repository.next_trace_sequence("ai", day) == 1
    assert repository.next_trace_sequence("ai", day) == 2
    assert repository.next_trace_sequence("tech", day) == 1


def _trend(trend_id: str = "trend-1", trace_id: str = "ECHO-AI-20260809-000001") -> TrendCandidate:
    return TrendCandidate(
        trend_id=trend_id,
        trace_id=trace_id,
        topic="Topic",
        keywords=["topic", "keyword"],
        sources=["src-1"],
        detected_at=NOW,
        velocity=0.6,
        novelty=0.5,
        relevance=0.5,
        vertical="ai",
    )


def test_save_and_get_trend_round_trip(repository: EchoRepository) -> None:
    trend = _trend()
    repository.save_trend(trend)

    fetched = repository.get_trend(trend.trend_id)

    assert fetched is not None
    assert fetched.trend_id == trend.trend_id
    assert fetched.trace_id == trend.trace_id
    assert fetched.keywords == trend.keywords
    assert fetched.velocity == trend.velocity


def test_save_and_get_research_round_trip(repository: EchoRepository) -> None:
    trend = _trend()
    repository.save_trend(trend)
    research = ResearchPacket(
        research_id="research-1",
        trend_id=trend.trend_id,
        trace_id=trend.trace_id,
        summary="summary",
        key_facts=["fact-1", "fact-2"],
        sources=["src-1"],
        source_quality=0.6,
        conflicting_information=False,
        confidence=0.6,
    )
    repository.save_research(research)

    fetched = repository.get_research_by_trend(trend.trend_id)

    assert fetched is not None
    assert fetched.summary == "summary"
    assert fetched.key_facts == ["fact-1", "fact-2"]


def test_save_and_get_score_round_trip(repository: EchoRepository) -> None:
    trend = _trend()
    repository.save_trend(trend)
    score = OpportunityScore(
        score_id="score-1",
        trend_id=trend.trend_id,
        trace_id=trend.trace_id,
        attention_score=0.6,
        relevance_score=0.5,
        novelty_score=0.5,
        timeliness_score=0.7,
        source_score=0.6,
        monetization_score=0.5,
        risk_score=0.1,
        final_score=0.55,
        scored_at=NOW,
    )
    repository.save_score(score)

    fetched = repository.get_score_by_trend(trend.trend_id)

    assert fetched is not None
    assert fetched.final_score == 0.55


def _draft(trend: TrendCandidate, draft_id: str = "draft-1") -> ContentDraft:
    return ContentDraft(
        draft_id=draft_id,
        trend_id=trend.trend_id,
        trace_id=trend.trace_id,
        content_type=ContentType.EXPLAIN,
        hook="hook",
        body="body",
        cta="cta",
        sources=["src-1"],
        confidence=0.6,
        generated_at=NOW,
        vertical="ai",
    )


def test_save_and_get_draft_round_trip(repository: EchoRepository) -> None:
    trend = _trend()
    repository.save_trend(trend)
    draft = _draft(trend)
    repository.save_draft(draft)

    fetched = repository.get_draft(draft.draft_id)

    assert fetched is not None
    assert fetched.hook == "hook"
    assert fetched.content_type == ContentType.EXPLAIN


def test_pending_review_queue_excludes_reviewed_drafts(repository: EchoRepository) -> None:
    trend = _trend()
    repository.save_trend(trend)
    draft = _draft(trend)
    repository.save_draft(draft)

    assert [d.draft_id for d in repository.list_drafts_pending_review()] == [draft.draft_id]

    review = ReviewDecision(
        review_id="review-1",
        draft_id=draft.draft_id,
        trace_id=draft.trace_id,
        decision=DecisionType.APPROVE,
        reviewed_at=NOW,
    )
    repository.save_review(review)

    assert repository.list_drafts_pending_review() == []
