"""Maps ReliabilityTier -> a numeric quality weight in [0, 1].

Deliberately config/enum-driven, never keyed by company name -- see
config/sources/*.yaml for which source gets which tier.
"""

from __future__ import annotations

from echo.models.enums import ReliabilityTier

TIER_SCORES: dict[ReliabilityTier, float] = {
    ReliabilityTier.A: 1.0,  # official / primary source
    ReliabilityTier.B: 0.7,  # high-quality secondary source
    ReliabilityTier.C: 0.4,  # discovery-only source
}


def reliability_score(tier: ReliabilityTier) -> float:
    return TIER_SCORES[tier]
