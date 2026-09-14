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
from echo.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ContentType,
    DecisionType,
    FetchStatus,
    ReliabilityTier,
    RejectReason,
    ResearchStatus,
)
from echo.models.performance import PerformanceSnapshot
from echo.models.publish import PublishedPost
from echo.models.research import ConflictRecord, EvidenceItem, ResearchClaim, ResearchPacket, SourceAssessment
from echo.models.review import ReviewDecision
from echo.models.score import OpportunityScore
from echo.models.source import SourceItem
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
                                     sources_json, detected_at, velocity, novelty, relevance,
                                     freshness, source_quality, source_count, cross_source_confirmation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (trend_id) DO UPDATE SET
                    topic = excluded.topic,
                    keywords_json = excluded.keywords_json,
                    sources_json = excluded.sources_json,
                    velocity = excluded.velocity,
                    novelty = excluded.novelty,
                    relevance = excluded.relevance,
                    freshness = excluded.freshness,
                    source_quality = excluded.source_quality,
                    source_count = excluded.source_count,
                    cross_source_confirmation = excluded.cross_source_confirmation
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
                    trend.freshness,
                    trend.source_quality,
                    trend.source_count,
                    trend.cross_source_confirmation,
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

    # -- research (STEP 3: claims/evidence/conflicts persist alongside) -----

    def save_research(self, research: ResearchPacket) -> None:
        """Persists the research row plus every claim/evidence/conflict it
        carries, in one connection. Claims/evidence/conflicts always have
        freshly-allocated ids (see echo.core.ids.IdFactory), so -- like
        ``save_trend`` -- there is never an UPDATE path for them, only
        INSERT ... ON CONFLICT DO NOTHING: a re-run of research for the
        same trend produces an entirely new ``research_id`` and its own
        fresh child rows, never mutating a prior research run's."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO research (research_id, trend_id, trace_id, summary, key_facts_json,
                                       sources_json, source_quality, conflicting_information, confidence,
                                       source_assessments_json, primary_source_present,
                                       independent_source_count, research_status, researched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (research_id) DO UPDATE SET
                    summary = excluded.summary,
                    key_facts_json = excluded.key_facts_json,
                    sources_json = excluded.sources_json,
                    source_quality = excluded.source_quality,
                    conflicting_information = excluded.conflicting_information,
                    confidence = excluded.confidence,
                    source_assessments_json = excluded.source_assessments_json,
                    primary_source_present = excluded.primary_source_present,
                    independent_source_count = excluded.independent_source_count,
                    research_status = excluded.research_status,
                    researched_at = excluded.researched_at
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
                    json.dumps([a.model_dump(mode="json") for a in research.source_assessments]),
                    int(research.primary_source_present),
                    research.independent_source_count,
                    research.research_status.value,
                    research.researched_at.isoformat() if research.researched_at else None,
                ),
            )
            for claim in research.claims:
                self._insert_claim(conn, research.research_id, claim)
            for evidence in research.evidence:
                self._insert_evidence(conn, research.research_id, evidence)
            for conflict in research.conflicts:
                self._insert_conflict(conn, research.research_id, conflict)
            conn.commit()
        finally:
            conn.close()

    def _insert_claim(self, conn: sqlite3.Connection, research_id: str, claim: ResearchClaim) -> None:
        conn.execute(
            """
            INSERT INTO research_claims (claim_id, research_id, text, normalized_text, claim_type,
                                          evidence_ids_json, supporting_source_ids_json,
                                          contradicting_source_ids_json, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (claim_id) DO NOTHING
            """,
            (
                claim.claim_id,
                research_id,
                claim.text,
                claim.normalized_text,
                claim.claim_type,
                json.dumps(claim.evidence_ids),
                json.dumps(claim.supporting_source_ids),
                json.dumps(claim.contradicting_source_ids),
                claim.confidence,
                claim.status.value,
            ),
        )

    def _insert_evidence(self, conn: sqlite3.Connection, research_id: str, evidence: EvidenceItem) -> None:
        conn.execute(
            """
            INSERT INTO research_evidence (evidence_id, research_id, source_item_id, source_key, url,
                                            title, published_at, excerpt, is_primary_source, reliability_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evidence_id) DO NOTHING
            """,
            (
                evidence.evidence_id,
                research_id,
                evidence.source_item_id,
                evidence.source_key,
                evidence.url,
                evidence.title,
                evidence.published_at.isoformat(),
                evidence.excerpt,
                int(evidence.is_primary_source),
                evidence.reliability_tier.value,
            ),
        )

    def _insert_conflict(self, conn: sqlite3.Connection, research_id: str, conflict: ConflictRecord) -> None:
        conn.execute(
            """
            INSERT INTO research_conflicts (conflict_id, research_id, claim_id, evidence_id_a, evidence_id_b,
                                             source_key_a, source_key_b, conflict_type, reason, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (conflict_id) DO NOTHING
            """,
            (
                conflict.conflict_id,
                research_id,
                conflict.claim_id,
                conflict.evidence_id_a,
                conflict.evidence_id_b,
                conflict.source_key_a,
                conflict.source_key_b,
                conflict.conflict_type,
                conflict.reason,
                conflict.severity.value,
            ),
        )

    def get_research(self, research_id: str) -> ResearchPacket | None:
        """Fully hydrated: includes this research run's claims/evidence/
        conflicts, not just the scalar `research` row."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM research WHERE research_id = ?", (research_id,)).fetchone()
            if row is None:
                return None
            claims = [_row_to_claim(r) for r in conn.execute(
                "SELECT * FROM research_claims WHERE research_id = ?", (research_id,)
            ).fetchall()]
            evidence = [_row_to_evidence(r) for r in conn.execute(
                "SELECT * FROM research_evidence WHERE research_id = ?", (research_id,)
            ).fetchall()]
            conflicts = [_row_to_conflict(r) for r in conn.execute(
                "SELECT * FROM research_conflicts WHERE research_id = ?", (research_id,)
            ).fetchall()]
            return _row_to_research(row, claims=claims, evidence=evidence, conflicts=conflicts)
        finally:
            conn.close()

    def get_research_by_trend(self, trend_id: str) -> ResearchPacket | None:
        """Latest research run for a trend, fully hydrated -- see get_research."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT research_id FROM research WHERE trend_id = ? ORDER BY rowid DESC LIMIT 1",
                (trend_id,),
            ).fetchone()
        finally:
            conn.close()
        return self.get_research(row["research_id"]) if row else None

    def list_claims_by_research(self, research_id: str) -> list[ResearchClaim]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM research_claims WHERE research_id = ?", (research_id,)
            ).fetchall()
            return [_row_to_claim(r) for r in rows]
        finally:
            conn.close()

    def list_evidence_by_research(self, research_id: str) -> list[EvidenceItem]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM research_evidence WHERE research_id = ?", (research_id,)
            ).fetchall()
            return [_row_to_evidence(r) for r in rows]
        finally:
            conn.close()

    def list_conflicts_by_research(self, research_id: str) -> list[ConflictRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM research_conflicts WHERE research_id = ?", (research_id,)
            ).fetchall()
            return [_row_to_conflict(r) for r in rows]
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

    # -- source items / fetch runs / failures (STEP 2) ----------------------

    def save_source_item(self, item: SourceItem, canonical_url: str, content_fingerprint: str) -> None:
        """Idempotent: a re-ingested item with the same id or canonical_url
        is silently ignored rather than overwritten, since SourceItem is
        immutable raw material, not something later stages edit in place."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO source_items (source_item_id, source_key, vertical, url, canonical_url,
                                           content_fingerprint, source_name, title, published_at,
                                           retrieved_at, content, language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_item_id) DO NOTHING
                """,
                (
                    item.source_id,
                    item.source_key,
                    item.vertical,
                    str(item.url),
                    canonical_url,
                    content_fingerprint,
                    item.source_name,
                    item.title,
                    item.published_at.isoformat(),
                    item.retrieved_at.isoformat(),
                    item.content,
                    item.language,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_known_canonical_urls(self) -> set[str]:
        """Seed data for echo.source.dedup.Deduplicator so duplicates are
        caught across ingest runs, not just within one batch."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT canonical_url FROM source_items").fetchall()
            return {row["canonical_url"] for row in rows}
        finally:
            conn.close()

    def list_known_content_fingerprints(self) -> set[str]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT content_fingerprint FROM source_items").fetchall()
            return {row["content_fingerprint"] for row in rows}
        finally:
            conn.close()

    def list_source_items(self, vertical: str | None = None) -> list[SourceItem]:
        conn = self._connect()
        try:
            if vertical is None:
                rows = conn.execute("SELECT * FROM source_items ORDER BY published_at").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM source_items WHERE vertical = ? ORDER BY published_at", (vertical,)
                ).fetchall()
            return [_row_to_source_item(r) for r in rows]
        finally:
            conn.close()

    def save_source_fetch_run(
        self,
        run_id: str,
        source_key: str,
        vertical: str,
        started_at: datetime,
        finished_at: datetime,
        status: FetchStatus,
        items_fetched: int,
        items_normalized: int,
        items_deduplicated: int,
        items_age_filtered: int = 0,
        items_item_limit_filtered: int = 0,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO source_fetch_runs (run_id, source_key, vertical, started_at, finished_at,
                                                status, items_fetched, items_normalized, items_age_filtered,
                                                items_item_limit_filtered, items_deduplicated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    run_id,
                    source_key,
                    vertical,
                    started_at.isoformat(),
                    finished_at.isoformat(),
                    status.value,
                    items_fetched,
                    items_normalized,
                    items_age_filtered,
                    items_item_limit_filtered,
                    items_deduplicated,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_source_fetch_runs(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM source_fetch_runs ORDER BY started_at").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_source_failure(
        self,
        failure_id: str,
        source_key: str,
        vertical: str,
        occurred_at: datetime,
        stage: str,
        error_type: str,
        message: str,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO source_failures (failure_id, source_key, vertical, occurred_at, stage,
                                              error_type, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (failure_id) DO NOTHING
                """,
                (failure_id, source_key, vertical, occurred_at.isoformat(), stage, error_type, message),
            )
            conn.commit()
        finally:
            conn.close()

    def list_source_failures(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM source_failures ORDER BY occurred_at").fetchall()
            return [dict(r) for r in rows]
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
    row_keys = row.keys()
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
        freshness=row["freshness"] if "freshness" in row_keys else 0.5,
        source_quality=row["source_quality"] if "source_quality" in row_keys else 0.5,
        source_count=row["source_count"] if "source_count" in row_keys else 1,
        cross_source_confirmation=(
            row["cross_source_confirmation"] if "cross_source_confirmation" in row_keys else 0.0
        ),
    )


def _row_to_research(
    row: sqlite3.Row,
    claims: list[ResearchClaim] | None = None,
    evidence: list[EvidenceItem] | None = None,
    conflicts: list[ConflictRecord] | None = None,
) -> ResearchPacket:
    row_keys = row.keys()
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
        claims=claims or [],
        evidence=evidence or [],
        conflicts=conflicts or [],
        source_assessments=(
            [SourceAssessment(**item) for item in json.loads(row["source_assessments_json"])]
            if "source_assessments_json" in row_keys and row["source_assessments_json"]
            else []
        ),
        primary_source_present=(
            bool(row["primary_source_present"]) if "primary_source_present" in row_keys else False
        ),
        independent_source_count=(
            row["independent_source_count"] if "independent_source_count" in row_keys else 0
        ),
        research_status=(
            ResearchStatus(row["research_status"])
            if "research_status" in row_keys and row["research_status"]
            else ResearchStatus.READY
        ),
        researched_at=(
            datetime.fromisoformat(row["researched_at"])
            if "researched_at" in row_keys and row["researched_at"]
            else None
        ),
    )


def _row_to_claim(row: sqlite3.Row) -> ResearchClaim:
    return ResearchClaim(
        claim_id=row["claim_id"],
        text=row["text"],
        normalized_text=row["normalized_text"],
        claim_type=row["claim_type"],
        evidence_ids=json.loads(row["evidence_ids_json"]),
        supporting_source_ids=json.loads(row["supporting_source_ids_json"]),
        contradicting_source_ids=json.loads(row["contradicting_source_ids_json"]),
        confidence=row["confidence"],
        status=ClaimStatus(row["status"]),
    )


def _row_to_evidence(row: sqlite3.Row) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=row["evidence_id"],
        source_item_id=row["source_item_id"],
        source_key=row["source_key"],
        url=row["url"],
        title=row["title"],
        published_at=datetime.fromisoformat(row["published_at"]),
        excerpt=row["excerpt"],
        is_primary_source=bool(row["is_primary_source"]),
        reliability_tier=ReliabilityTier(row["reliability_tier"]),
    )


def _row_to_conflict(row: sqlite3.Row) -> ConflictRecord:
    return ConflictRecord(
        conflict_id=row["conflict_id"],
        claim_id=row["claim_id"],
        evidence_id_a=row["evidence_id_a"],
        evidence_id_b=row["evidence_id_b"],
        source_key_a=row["source_key_a"],
        source_key_b=row["source_key_b"],
        conflict_type=row["conflict_type"],
        reason=row["reason"],
        severity=ConflictSeverity(row["severity"]),
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


def _row_to_source_item(row: sqlite3.Row) -> SourceItem:
    return SourceItem(
        source_id=row["source_item_id"],
        source_key=row["source_key"],
        url=row["url"],
        source_name=row["source_name"],
        title=row["title"],
        published_at=datetime.fromisoformat(row["published_at"]),
        retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
        content=row["content"],
        language=row["language"],
        vertical=row["vertical"],
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
