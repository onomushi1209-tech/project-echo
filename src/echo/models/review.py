"""ReviewDecision: the Human Review Gate outcome for a ContentDraft.

Critically, this is persisted for every reviewed draft -- including drafts
that were REJECT/SKIP and therefore never published. See
echo.storage.repository for how "not published" content is retained.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from echo.models.enums import DecisionType, RejectReason


class ReviewDecision(BaseModel):
    """Record of a human decision made at the Human Review Gate."""

    review_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    decision: DecisionType
    review_reason: RejectReason | None = None
    reviewer_note: str | None = None
    reviewed_at: datetime

    @model_validator(mode="after")
    def _reason_required_for_reject(self) -> ReviewDecision:
        if self.decision == DecisionType.REJECT and self.review_reason is None:
            raise ValueError("review_reason is required when decision is REJECT")
        return self
