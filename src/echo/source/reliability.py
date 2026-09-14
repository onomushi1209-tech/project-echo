"""Maps ReliabilityTier -> a numeric quality weight in [0, 1].

Deliberately config/enum-driven, never keyed by company name -- see
config/sources/*.yaml for which source gets which tier.
"""

from __future__ import annotations

from echo.core.reliability import TIER_SCORES, reliability_score

# Preserve the STEP 2 public imports; research uses the neutral core helper.
__all__ = ["TIER_SCORES", "reliability_score"]
