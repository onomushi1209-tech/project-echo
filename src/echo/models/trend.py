"""TrendCandidate: a candidate topic detected from a batch of SourceItems."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TrendCandidate(BaseModel):
    """A topic candidate surfaced by the DISCOVER stage."""

    trend_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="SourceItem.source_id references")
    detected_at: datetime
    velocity: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    vertical: str = Field(min_length=1)
