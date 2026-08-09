"""Repository layer: the only place that runs SQL against Echo's SQLite store.

Converts between Pydantic models and ``sqlite3.Row`` objects so no other
module needs to know the schema (see db.py for the schema itself).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from echo.models.draft import ContentDraft
from echo.models.enums import ContentType, DecisionType, RejectReason
from echo.models.performance import PerformanceSnapshot
from echo.models.publish import PublishedPost
from echo.models.research import ResearchPacket
from echo.models.review import ReviewDecision
from echo.models.score import OpportunityScore
from echo.models.trend import TrendCandidate
from echo.storage.db import get_connection, init_db


class EchoRepository:
    """Storage-layer gateway for all Echo pipeline entities."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        init_db(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # -- trace sequence -------------------------------------------------

    def next_trace_sequence(self, vertical: str, day: date) -> int:
        """Atomically allocate the next sequence number for (vertical, day)."""
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO trace_sequences (vertical, seq_date, last_seq)
                VALUES (?, ?, 1)
                ON CONFLICT (vertical, seq_date)
                DO UPDATE SET last_seq = last_seq + 1
                RETURNING last_seq
                """,
                (vertical.upper(), day.isoformat()),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0])
        finally:
            conn.close()

    # -- trends -----------------------------------------------------------

    def save_trend(self, trend: TrendCandidate) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO trends (trend_id, trace_id, vertical, topic, keywords_json,
                                     sources_json, detected_at, velocity, novelty, relevance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (trend_id) DO UPDATE SET
                    topic = excluded.topic,
                    keywords_json = excluded.keywords_json,
                    sources_json = excluded.sources_json,
                    velocity = excluded.velocity,
                    novelty = excluded.novelty,
                    relevance = excluded.relevance
                """,
                (
                    trend.trend_id,
                    trend.trace_id,
                    trend.vertical,
                    trend.topic,
                    json.dumps(trend.keywords),
                    json.dumps(trend.sources),
                    trend.detected_at.isoformat(),
                    trend.velocity,
                    trend.novelty,
                    trend.relevance,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_trend(self, trend_id: str) -> TrendCandidate | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM trends WHERE trend_id = ?", (trend_id,)).fetchone()
            return _row_to_trend(row) if row else None
        finally:
            conn.close()

    def list_trends(self) -> list[TrendCandidate]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM trends ORDER BY detected_at").fetchall()
            return [_row_to_trend(r) for r in rows]
        finally:
            conn.close()

    # -- research -----------------------------------------------------------

    def save_research(self, research: ResearchPacket) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO research (research_id, trend_id, trace_id, summary, key_facts_json,
                                       sources_json, source_quality, conflicting_information, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (research_id) DO UPDATE SET
                    summary = excluded.summary,
                    key_facts_json = excluded.key_facts_json,
                    sources_json = excluded.sources_json,
                    source_quality = excluded.source_quality,
                    conflicting_information = excluded.conflicting_information,
                    confidence = excluded.confidence
                """,
                (
                    research.research_id,
                    research.trend_id,
                    research.trace_id,
                    research.summary,
                    json.dumps(research.key_facts),
                    json.dumps(research.sources),
                    research.source_quality,
                    int(research.conflicting_information),
                    research.confidence,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_research_by_trend(self, trend_id: str) -> ResearchPacket | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM research WHERE trend_id = ? ORDER BY rowid DESC LIMIT 1",
                (trend_id,),
            ).fetchone()
            return _row_to_research(row) if row else None
        finally:
            conn.close()

    # -- scores -----------------------------------------------------------

    def save_score(self, score: OpportunityScore) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO scores (score_id, trend_id, trace_id, attention_score, relevance_score,
                                     novelty_score, timeliness_score, source_score, monetization_score,
                                     risk_score, final_score, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (score_id) DO UPDATE SET
                    attention_score = excluded.attention_score,
                    relevance_score = excluded.relevance_score,
                    novelty_score = excluded.novelty_score,
                    timeliness_score = excluded.timeliness_score,
                    source_score = excluded.source_score,
                    monetization_score = excluded.monetization_score,
                    risk_score = excluded.risk_score,
                    final_score = excluded.final_score
                """,
                (
                    score.score_id,
                    score.trend_id,
                    score.trace_id,
                    score.attention_score,
                    score.relevance_score,
                    score.novelty_score,
                    score.timeliness_score,
                    score.source_score,
                    score.monetization_score,
                    score.risk_score,
                    score.final_score,
                    score.scored_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_score_by_trend(self, trend_id: str) -> OpportunityScore | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM scores WHERE trend_id = ? ORDER BY rowid DESC LIMIT 1",
                (trend_id,),
            ).fetchone()
            return _row_to_score(row) if row else None
        finally:
            conn.close()

    # -- drafts -----------------------------------------------------------

    def save_draft(self, draft: ContentDraft) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO drafts (draft_id, trend_id, trace_id, vertical, content_type, hook, body,
                                     cta, sources_json, confidence, generated_at, compliance_risk_score,
                                     compliance_flags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (draft_id) DO UPDATE SET
                    hook = excluded.hook,
                    body = excluded.body,
                    cta = excluded.cta,
                    sources_json = excluded.sources_json,
                    confidence = excluded.confidence,
                    compliance_risk_score = excluded.compliance_risk_score,
                    compliance_flags_json = excluded.compliance_flags_json
                """,
                (
                    draft.draft_id,
                    draft.trend_id,
                    draft.trace_id,
                    draft.vertical,
                    draft.content_type.value,
                    draft.hook,
                    draft.body,
                    draft.cta,
                    json.dumps(draft.sources),
                    draft.confidence,
                    draft.generated_at.isoformat(),
                    draft.compliance_risk_score,
                    json.dumps(draft.compliance_flags),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_draft(self, draft_id: str) -> ContentDraft | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
            return _row_to_draft(row) if row else None
        finally:
            conn.close()

    def list_drafts_pending_review(self) -> list[ContentDraft]:
        """Drafts with no review decision yet -- i.e. the Human Review Gate queue."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT d.* FROM drafts d
                LEFT JOIN reviews r ON r.draft_id = d.draft_id
                WHERE r.draft_id IS NULL
                ORDER BY d.generated_at
                """
            ).fetchall()
            return [_row_to_draft(r) for r in rows]
        finally:
            conn.close()

    # -- reviews -----------------------------------------------------------

    def save_review(self, review: ReviewDecision) -> None:
        """Persist a review decision -- including REJECT/SKIP, which is how
        Echo retains "content that was not published, and why"."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO reviews (review_id, draft_id, trace_id, decision, review_reason,
                                      reviewer_note, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (draft_id) DO UPDATE SET
                    decision = excluded.decision,
                    review_reason = excluded.review_reason,
                    reviewer_note = excluded.reviewer_note,
                    reviewed_at = excluded.reviewed_at
                """,
                (
                    review.review_id,
                    review.draft_id,
                    review.trace_id,
                    review.decision.value,
                    review.review_reason.value if review.review_reason else None,
                    review.reviewer_note,
                    review.reviewed_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_review_by_draft(self, draft_id: str) -> ReviewDecision | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM reviews WHERE draft_id = ?", (draft_id,)).fetchone()
            return _row_to_review(row) if row else None
        finally:
            conn.close()

    def list_reviews(self) -> list[ReviewDecision]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM reviews ORDER BY reviewed_at").fetchall()
            return [_row_to_review(r) for r in rows]
        finally:
            conn.close()

    def list_rejected(self) -> list[ReviewDecision]:
        """Reviewed drafts that will never be published, with their reason."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE decision IN (?, ?) ORDER BY reviewed_at",
                (DecisionType.REJECT.value, DecisionType.SKIP.value),
            ).fetchall()
            return [_row_to_review(r) for r in rows]
        finally:
            conn.close()

    # -- published posts / performance --------------------------------------
    # No STEP 1 service writes these yet (no X API integration exists); the
    # methods exist so the schema has a stable, tested write path ready for
    # later steps.

    def save_published_post(self, post: PublishedPost) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO published_posts (post_id, draft_id, trace_id, x_post_id, published_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (post_id) DO NOTHING
                """,
                (
                    post.post_id,
                    post.draft_id,
                    post.trace_id,
                    post.x_post_id,
                    post.published_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def save_performance_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO performance (snapshot_id, post_id, trace_id, captured_at, impressions,
                                          likes, replies, reposts, bookmarks, profile_visits,
                                          followers_gained, link_clicks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.post_id,
                    snapshot.trace_id,
                    snapshot.captured_at.isoformat(),
                    snapshot.impressions,
                    snapshot.likes,
                    snapshot.replies,
                    snapshot.reposts,
                    snapshot.bookmarks,
                    snapshot.profile_visits,
                    snapshot.followers_gained,
                    snapshot.link_clicks,
                ),
            )
            conn.commit()
        finally:
            conn.close()


# -- row -> model mapping ---------------------------------------------------


def _row_to_trend(row: sqlite3.Row) -> TrendCandidate:
    return TrendCandidate(
        trend_id=row["trend_id"],
        trace_id=row["trace_id"],
        topic=row["topic"],
        keywords=json.loads(row["keywords_json"]),
        sources=json.loads(row["sources_json"]),
        detected_at=datetime.fromisoformat(row["detected_at"]),
        velocity=row["velocity"],
        novelty=row["novelty"],
        relevance=row["relevance"],
        vertical=row["vertical"],
    )


def _row_to_research(row: sqlite3.Row) -> ResearchPacket:
    return ResearchPacket(
        research_id=row["research_id"],
        trend_id=row["trend_id"],
        trace_id=row["trace_id"],
        summary=row["summary"],
        key_facts=json.loads(row["key_facts_json"]),
        sources=json.loads(row["sources_json"]),
        source_quality=row["source_quality"],
        conflicting_information=bool(row["conflicting_information"]),
        confidence=row["confidence"],
    )


def _row_to_score(row: sqlite3.Row) -> OpportunityScore:
    return OpportunityScore(
        score_id=row["score_id"],
        trend_id=row["trend_id"],
        trace_id=row["trace_id"],
        attention_score=row["attention_score"],
        relevance_score=row["relevance_score"],
        novelty_score=row["novelty_score"],
        timeliness_score=row["timeliness_score"],
        source_score=row["source_score"],
        monetization_score=row["monetization_score"],
        risk_score=row["risk_score"],
        final_score=row["final_score"],
        scored_at=datetime.fromisoformat(row["scored_at"]),
    )


def _row_to_draft(row: sqlite3.Row) -> ContentDraft:
    return ContentDraft(
        draft_id=row["draft_id"],
        trend_id=row["trend_id"],
        trace_id=row["trace_id"],
        content_type=ContentType(row["content_type"]),
        hook=row["hook"],
        body=row["body"],
        cta=row["cta"],
        sources=json.loads(row["sources_json"]),
        confidence=row["confidence"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
        vertical=row["vertical"],
        compliance_risk_score=row["compliance_risk_score"],
        compliance_flags=json.loads(row["compliance_flags_json"]),
    )


def _row_to_review(row: sqlite3.Row) -> ReviewDecision:
    return ReviewDecision(
        review_id=row["review_id"],
        draft_id=row["draft_id"],
        trace_id=row["trace_id"],
        decision=DecisionType(row["decision"]),
        review_reason=RejectReason(row["review_reason"]) if row["review_reason"] else None,
        reviewer_note=row["reviewer_note"],
        reviewed_at=datetime.fromisoformat(row["reviewed_at"]),
    )
