"""Research Confidence Engine: deterministic, config-driven, [0, 1] only.

Two entry points, both pure functions over already-computed inputs (never
recompute clustering/extraction themselves) so each is independently
testable:

  - ``claim_confidence`` -- one ``ResearchClaim``'s confidence.
  - ``packet_confidence`` -- the overall ``ResearchPacket.confidence``,
    combining primary-source presence, source reliability, independent
    source count, claim agreement, evidence coverage, and conflict
    severity. See docs/RESEARCH_INTELLIGENCE.md "Research Confidence
    Engine" for the term-by-term rationale.

Every term is documented on ``ResearchConfidenceWeights``
(``echo.research.config``) -- there are no unlabeled magic numbers here.
"""

from __future__ import annotations

from echo.models.enums import ClaimStatus, ConflictSeverity
from echo.models.research import ConflictRecord, ResearchClaim
from echo.research.config import ResearchConfig


def claim_confidence(
    reliabilities: list[float],
    independent_count: int,
    primary_present: bool,
    has_conflict: bool,
    config: ResearchConfig,
) -> float:
    if not reliabilities:
        return 0.0
    weights = config.confidence_weights
    score = weights.base_confidence
    score += max(reliabilities) * 0.3
    score += _independent_source_bonus(independent_count, weights)
    if primary_present:
        score += weights.primary_source_bonus
    if has_conflict:
        score -= weights.conflict_penalty_major
    return max(0.0, min(1.0, score))


def packet_confidence(
    primary_source_present: bool,
    tier_a_source_present: bool,
    independent_source_count: int,
    claims: list[ResearchClaim],
    conflicts: list[ConflictRecord],
    evidence_count: int,
    config: ResearchConfig,
) -> float:
    weights = config.confidence_weights
    score = weights.base_confidence

    if primary_source_present:
        score += weights.primary_source_bonus
    if tier_a_source_present:
        score += weights.tier_a_source_bonus

    score += _independent_source_bonus(independent_source_count, weights)

    if claims:
        agreeing = sum(1 for c in claims if c.status in (ClaimStatus.CONFIRMED, ClaimStatus.SUPPORTED))
        score += weights.agreement_bonus * (agreeing / len(claims))

    if evidence_count >= config.minimum_evidence_items:
        score += weights.evidence_coverage_bonus

    for conflict in conflicts:
        score -= _conflict_penalty(conflict.severity, weights)

    return max(0.0, min(1.0, score))


def _independent_source_bonus(independent_count: int, weights) -> float:
    if independent_count <= 0:
        return 0.0
    return min(
        weights.independent_source_bonus_cap,
        (independent_count - 1) * weights.independent_source_bonus_per_source,
    )


def _conflict_penalty(severity: ConflictSeverity, weights) -> float:
    if severity == ConflictSeverity.MAJOR:
        return weights.conflict_penalty_major
    if severity == ConflictSeverity.MINOR:
        return weights.conflict_penalty_minor
    return weights.conflict_penalty_potential
