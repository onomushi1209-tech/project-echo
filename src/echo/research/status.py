"""Research Status: ResearchPacket.research_status determination.

Informational only -- never a publish/reject decision. COMPLIANCE and the
Human Review Gate keep that responsibility (see docs/DEVELOPMENT_RULES.md
rule 3); this module only describes how far along/solid the research
itself is.

Config-driven via ``ResearchConfig``; see docs/RESEARCH_INTELLIGENCE.md
"Minimum evidence rules" for why a lone primary source is not
automatically rejected (``require_primary_source_for_single_source_claim``).
"""

from __future__ import annotations

from echo.models.enums import ClaimStatus, ConflictSeverity, ResearchStatus
from echo.models.research import ConflictRecord, ResearchClaim
from echo.research.config import ResearchConfig


def determine_research_status(
    evidence_count: int,
    independent_source_count: int,
    primary_source_present: bool,
    confidence: float,
    conflicts: list[ConflictRecord],
    config: ResearchConfig,
    claims: list[ResearchClaim] | None = None,
) -> ResearchStatus:
    if evidence_count < config.minimum_evidence_items:
        return ResearchStatus.INSUFFICIENT_EVIDENCE

    if any(conflict.severity != ConflictSeverity.POTENTIAL for conflict in conflicts):
        return ResearchStatus.CONFLICTED

    single_source_acceptable = primary_source_present or not config.require_primary_source_for_single_source_claim
    if independent_source_count < config.minimum_independent_sources:
        if not (single_source_acceptable and independent_source_count >= 1):
            return ResearchStatus.NEEDS_MORE_SOURCES

    # RealResearchBrain always supplies claims. None preserves the existing
    # low-level API for callers that already validated their claim support.
    if claims is not None and not claims:
        return ResearchStatus.INSUFFICIENT_EVIDENCE
    if claims and all(claim.status == ClaimStatus.UNVERIFIED for claim in claims):
        return ResearchStatus.LOW_CONFIDENCE

    if confidence < config.minimum_confidence:
        return ResearchStatus.LOW_CONFIDENCE

    return ResearchStatus.READY
