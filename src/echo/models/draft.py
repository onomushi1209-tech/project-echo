"""ContentDraft: the CREATE stage output, prior to compliance/review."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from echo.models.enums import ContentType


class ContentDraft(BaseModel):
    """A drafted piece of content awaiting compliance check and human review."""

    draft_id: str = Field(min_length=1)
    trend_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    content_type: ContentType
    hook: str = Field(min_length=1)
    body: str = Field(min_length=1)
    cta: str | None = None
    sources: list[str] = Field(default_factory=list, description="SourceItem.source_id references")
    confidence: float = Field(ge=0.0, le=1.0)
    generated_at: datetime
    vertical: str = Field(min_length=1)

    # Populated by the COMPLIANCE stage. Kept on the draft (rather than a
    # separate table) so the Human Review Gate always sees compliance
    # context -- compliance never auto-rejects, it only informs the human.
    compliance_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    compliance_flags: list[str] = Field(default_factory=list)
