"""Human Review Gate: records APPROVE/REJECT/EDIT/SKIP decisions.

Every decision is persisted -- including REJECT/SKIP -- so Echo retains a
full, queryable record of content that was *not* published, and why.
"""

from __future__ import annotations

from datetime import datetime, timezone

from echo.core.ids import new_entity_id
from echo.models.draft import ContentDraft
from echo.models.enums import DecisionType, RejectReason
from echo.models.review import ReviewDecision
from echo.storage.repository import EchoRepository


def pending_queue(repository: EchoRepository) -> list[ContentDraft]:
    """Drafts that have passed COMPLIANCE but have no review decision yet."""
    return repository.list_drafts_pending_review()


def record_decision(
    repository: EchoRepository,
    draft: ContentDraft,
    decision: DecisionType,
    review_reason: RejectReason | None = None,
    reviewer_note: str | None = None,
) -> ReviewDecision:
    review = ReviewDecision(
        review_id=new_entity_id("review"),
        draft_id=draft.draft_id,
        trace_id=draft.trace_id,
        decision=decision,
        review_reason=review_reason,
        reviewer_note=reviewer_note,
        reviewed_at=datetime.now(timezone.utc),
    )
    repository.save_review(review)
    return review
