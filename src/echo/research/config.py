"""ResearchConfig: tunable parameters for every echo.research module.

Mirrors ``echo.trend.signal_config.TrendSignalConfig`` -- a single,
documented source of truth so claim-grouping/conflict/confidence
thresholds aren't scattered as magic numbers across modules. Defaults are
deliberately conservative starting points for STEP 3. Override via the
constructor, or via ``echo.config.settings.Settings.research_config()``
for the handful of knobs exposed through environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class ResearchConfidenceWeights:
    """Additive/subtractive terms echo.research.confidence combines into
    ResearchPacket.confidence -- each independently documented and
    testable. Never mixes a 0-100 scale in; everything is [0, 1]."""

    base_confidence: float = 0.30
    primary_source_bonus: float = 0.25
    tier_a_source_bonus: float = 0.15
    independent_source_bonus_per_source: float = 0.10
    independent_source_bonus_cap: float = 0.30
    agreement_bonus: float = 0.15  # most claims CONFIRMED/SUPPORTED, none CONFLICTED
    evidence_coverage_bonus: float = 0.10
    conflict_penalty_potential: float = 0.05
    conflict_penalty_minor: float = 0.15
    conflict_penalty_major: float = 0.35


@dataclass(frozen=True)
class ResearchConfig:
    # Source selection / performance safeguard (see echo.research.source_selection
    # and docs/RESEARCH_INTELLIGENCE.md "Performance safeguards"). Reuses
    # TrendSignalConfig.cluster_time_window_hours for the candidate-pool
    # time bound rather than duplicating that knob.
    max_research_sources: int = 20

    # Fact/claim extraction (see echo.research.extraction)
    min_sentence_length: int = 20  # chars; shorter is nav text/fragments
    max_excerpt_length: int = 240  # chars; evidence excerpts are bounded, never full articles

    # Claim grouping (see echo.research.claims)
    claim_grouping_similarity_threshold: float = 0.45

    # Minimum evidence rules / research status (see echo.research.status).
    # Conservative defaults -- see docs/RESEARCH_INTELLIGENCE.md "Minimum
    # evidence rules" for why a single primary source is not auto-rejected.
    minimum_evidence_items: int = 1
    minimum_independent_sources: int = 2
    minimum_confidence: float = 0.4
    require_primary_source_for_single_source_claim: bool = True

    confidence_weights: ResearchConfidenceWeights = field(default_factory=ResearchConfidenceWeights)
    max_research_candidates: int = 200  # appended for positional compatibility; cap BEFORE clustering

    def __post_init__(self) -> None:
        for name in (
            "max_research_sources", "max_research_candidates", "min_sentence_length",
            "max_excerpt_length", "minimum_evidence_items", "minimum_independent_sources",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("claim_grouping_similarity_threshold", "minimum_confidence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and within [0, 1]")
