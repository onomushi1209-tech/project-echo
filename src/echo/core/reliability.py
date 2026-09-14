"""Shared, source-independent mapping from reliability tier to quality."""

from echo.models.enums import ReliabilityTier

TIER_SCORES: dict[ReliabilityTier, float] = {
    ReliabilityTier.A: 1.0,
    ReliabilityTier.B: 0.7,
    ReliabilityTier.C: 0.4,
}


def reliability_score(tier: ReliabilityTier) -> float:
    return TIER_SCORES[tier]
