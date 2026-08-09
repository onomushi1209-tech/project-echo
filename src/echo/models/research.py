"""ResearchPacket: the researched context supporting a TrendCandidate."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchPacket(BaseModel):
    """Output of the RESEARCH stage for a given trend."""

    research_id: str = Field(min_length=1)
    trend_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    key_facts: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="SourceItem.source_id references")
    source_quality: float = Field(ge=0.0, le=1.0)
    conflicting_information: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
