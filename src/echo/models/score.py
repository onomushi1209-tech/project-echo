"""OpportunityScore: the SCORE stage output used for the threshold gate."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OpportunityScore(BaseModel):
    """Composite score describing whether a trend is worth drafting content for."""

    score_id: str = Field(min_length=1)
    trend_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    attention_score: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    timeliness_score: float = Field(ge=0.0, le=1.0)
    source_score: float = Field(ge=0.0, le=1.0)
    monetization_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    final_score: float = Field(ge=0.0, le=1.0)
    scored_at: datetime
