from __future__ import annotations

from datetime import datetime, timezone

from echo.models.draft import ContentDraft
from echo.models.enums import ContentType, DecisionType, RejectReason
from echo.models.trend import TrendCandidate
from echo.review.service import pending_queue, record_decision
from echo.storage.repository import EchoRepository

NOW = datetime.now(timezone.utc)


def _seed_draft(repository: EchoRepository, draft_id: str, trend_id: str) -> ContentDraft:
    trend = TrendCandidate(
        trend_id=trend_id,
        trace_id=f"ECHO-AI-20260809-{trend_id[-6:].rjust(6, '0')}",
        topic="Topic",
        sources=["src-1"],
        detected_at=NOW,
        velocity=0.6,
        novelty=0.5,
        relevance=0.5,
        vertical="ai",
    )
    repository.save_trend(trend)
    draft = ContentDraft(
        draft_id=draft_id,
        trend_id=trend_id,
        trace_id=trend.trace_id,
        content_type=ContentType.EXPLAIN,
        hook="hook",
        body="body",
        sources=["src-1"],
        confidence=0.6,
        generated_at=NOW,
        vertical="ai",
    )
    repository.save_draft(draft)
    return draft


def test_approve_removes_draft_from_pending_queue(repository: EchoRepository) -> None:
    draft = _seed_draft(repository, "draft-approve", "trend-approve")
    assert draft.draft_id in {d.draft_id for d in pending_queue(repository)}

    review = record_decision(repository, draft, DecisionType.APPROVE)

    assert review.decision == DecisionType.APPROVE
    assert review.review_reason is None
    assert draft.draft_id not in {d.draft_id for d in pending_queue(repository)}


def test_reject_requires_and_persists_reason(repository: EchoRepository) -> None:
    draft = _seed_draft(repository, "draft-reject", "trend-reject")

    review = record_decision(
        repository,
        draft,
        DecisionType.REJECT,
        review_reason=RejectReason.LOW_VALUE,
        reviewer_note="not enough substance",
    )

    assert review.decision == DecisionType.REJECT
    assert review.review_reason == RejectReason.LOW_VALUE

    reloaded = repository.get_review_by_draft(draft.draft_id)
    assert reloaded is not None
    assert reloaded.review_reason == RejectReason.LOW_VALUE
    assert reloaded.reviewer_note == "not enough substance"


def test_rejected_draft_content_is_still_retrievable(repository: EchoRepository) -> None:
    """Content that was NOT published must still be queryable, with its reason."""
    draft = _seed_draft(repository, "draft-reject-2", "trend-reject-2")
    record_decision(
        repository,
        draft,
        DecisionType.REJECT,
        review_reason=RejectReason.HIGH_COMPLIANCE_RISK,
    )

    stored_draft = repository.get_draft(draft.draft_id)
    stored_review = repository.get_review_by_draft(draft.draft_id)

    assert stored_draft is not None
    assert stored_draft.hook == "hook"
    assert stored_review is not None
    assert stored_review.decision == DecisionType.REJECT
    assert stored_review.review_reason == RejectReason.HIGH_COMPLIANCE_RISK


def test_list_rejected_includes_reject_and_skip_but_not_approve(
    repository: EchoRepository,
) -> None:
    approved = _seed_draft(repository, "draft-a", "trend-a")
    rejected = _seed_draft(repository, "draft-r", "trend-r")
    skipped = _seed_draft(repository, "draft-s", "trend-s")

    record_decision(repository, approved, DecisionType.APPROVE)
    record_decision(
        repository, rejected, DecisionType.REJECT, review_reason=RejectReason.DUPLICATE_TOPIC
    )
    record_decision(repository, skipped, DecisionType.SKIP)

    rejected_ids = {r.draft_id for r in repository.list_rejected()}
    assert rejected_ids == {rejected.draft_id, skipped.draft_id}
