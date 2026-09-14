"""RESEARCH stage: service (thin orchestration) + Research Intelligence
algorithm modules.

``service.research_trend`` is unchanged since STEP 1: it just calls the
injected brain and persists results. The modules below (source_selection/
extraction/independence/evidence/claims/conflicts/confidence/status/
summary) are what a source-intelligence-aware brain
(``echo.brains.RealResearchBrain``) composes -- each is independently
testable and swappable, see docs/RESEARCH_INTELLIGENCE.md.
"""

from echo.research.claims import build_claims, group_fact_candidates
from echo.research.config import ResearchConfidenceWeights, ResearchConfig
from echo.research.confidence import claim_confidence, packet_confidence
from echo.research.conflicts import ConflictSignal, detect_conflict
from echo.research.evidence import SourceRegistryInfo, build_evidence_item
from echo.research.extraction import FactCandidate, extract_fact_candidates
from echo.research.independence import distinct_source_keys, independent_source_count
from echo.research.service import research_trend
from echo.research.source_selection import SourceSelectionResult, select_relevant_sources
from echo.research.status import determine_research_status
from echo.research.summary import build_summary

__all__ = [
    "ConflictSignal",
    "FactCandidate",
    "ResearchConfidenceWeights",
    "ResearchConfig",
    "SourceRegistryInfo",
    "SourceSelectionResult",
    "build_claims",
    "build_evidence_item",
    "build_summary",
    "claim_confidence",
    "detect_conflict",
    "determine_research_status",
    "distinct_source_keys",
    "extract_fact_candidates",
    "group_fact_candidates",
    "independent_source_count",
    "packet_confidence",
    "research_trend",
    "select_relevant_sources",
]
