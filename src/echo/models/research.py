"""Research models: the structured output of the RESEARCH stage.

``ResearchPacket`` is the STEP 1 model, extended in STEP 3 with optional,
defaulted fields -- so a packet built the STEP 1 way (``DummyResearchBrain``,
no claims/evidence) still validates and persists unchanged. See
docs/RESEARCH_INTELLIGENCE.md for the STEP 3 research model.

``ResearchClaim`` / ``EvidenceItem`` / ``ConflictRecord`` /
``SourceAssessment`` are separate models (not fields hand-rolled inline on
``ResearchPacket``) so each stays independently constructible and testable
-- see ``echo.research`` for the modules that build them.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from echo.models.enums import ClaimStatus, ConflictSeverity, ReliabilityTier, ResearchStatus


class EvidenceItem(BaseModel):
    """One piece of traceable evidence backing a claim.

    Always resolvable back to the ``SourceItem`` (and its original URL) it
    came from -- ``source_item_id`` is ``SourceItem.source_id``. Never holds
    a full article body: ``excerpt`` is a short, bounded snippet (see
    ``echo.research.config.ResearchConfig.max_excerpt_length``), not logged
    or stored content in bulk (see docs/RESEARCH_INTELLIGENCE.md
    "Observability").
    """

    evidence_id: str = Field(min_length=1)
    source_item_id: str = Field(min_length=1, description="SourceItem.source_id this evidence came from")
    source_key: str = Field(min_length=1, description="SourceConfig.id the SourceItem came from")
    url: str = Field(min_length=1, description="Original SourceItem.url -- provenance, never re-fetched")
    title: str = Field(min_length=1)
    published_at: datetime
    excerpt: str = Field(min_length=1)
    is_primary_source: bool = False
    reliability_tier: ReliabilityTier


class ResearchClaim(BaseModel):
    """One extracted, claim-level (not article-level) fact candidate,
    grouped with every other evidence sentence found to be about the same
    underlying fact -- see ``echo.research.claims``."""

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1, description="Representative surface text for this claim group")
    normalized_text: str = Field(min_length=1)
    claim_type: str = Field(default="general", description="Free-form label, e.g. 'status', 'general'")
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(
        default_factory=list, description="Distinct SourceConfig.id values agreeing with `text`"
    )
    contradicting_source_ids: list[str] = Field(
        default_factory=list, description="Distinct SourceConfig.id values conflicting with `text`"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    status: ClaimStatus


class ConflictRecord(BaseModel):
    """A detected (or potential) contradiction between two pieces of
    evidence for the same claim. Deterministic heuristic detection only --
    see ``echo.research.conflicts``. Ambiguous cases use
    ``ConflictSeverity.POTENTIAL`` rather than asserting a confirmed
    contradiction."""

    conflict_id: str = Field(min_length=1)
    claim_id: str | None = Field(default=None, description="ResearchClaim this conflict was found within")
    evidence_id_a: str = Field(min_length=1)
    evidence_id_b: str = Field(min_length=1)
    source_key_a: str = Field(min_length=1)
    source_key_b: str = Field(min_length=1)
    conflict_type: str = Field(description="Heuristic that fired: 'status_keyword' | 'negation' | 'numeric' | 'date'")
    reason: str = Field(min_length=1)
    severity: ConflictSeverity


class SourceAssessment(BaseModel):
    """Per-source_key rollup of what a Research run saw for one source --
    reliability, primary-source status, and how much it contributed. Not
    a decision by itself; see ``echo.research.confidence`` /
    ``echo.research.status`` for how it's used."""

    source_key: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    reliability_tier: ReliabilityTier
    reliability_score: float = Field(ge=0.0, le=1.0)
    is_primary_source: bool = False
    item_count: int = Field(ge=0, default=0)
    evidence_count: int = Field(ge=0, default=0)


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

    # STEP 3 additions. All defaulted so a packet built the STEP 1 way
    # (DummyResearchBrain) still validates and persists unchanged -- see
    # docs/RESEARCH_INTELLIGENCE.md.
    claims: list[ResearchClaim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    source_assessments: list[SourceAssessment] = Field(default_factory=list)
    primary_source_present: bool = False
    independent_source_count: int = Field(ge=0, default=0)
    research_status: ResearchStatus = ResearchStatus.READY
    researched_at: datetime | None = Field(
        default=None, description="When RealResearchBrain ran; None for STEP 1 DummyResearchBrain output"
    )
