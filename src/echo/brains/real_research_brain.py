"""RealResearchBrain: a source-intelligence-aware ResearchBrain.

Coexists with ``DummyResearchBrain`` (STEP 1) -- both satisfy the same,
unchanged ``echo.core.interfaces.ResearchBrain`` Protocol, so
``echo.research.service.research_trend`` and ``echo.core.pipeline`` work
with either without modification.

Turns a TrendCandidate + the sources it was detected from into a
ResearchPacket by composing the independent ``echo.research`` modules:

    select_relevant_sources -> extract_fact_candidates ->
    group_fact_candidates -> build_claims -> packet_confidence ->
    determine_research_status -> build_summary

No LLM, no external call -- every step is deterministic (see
docs/RESEARCH_INTELLIGENCE.md). All source-registry data (reliability
tier, primary-source flag, display name) is injected at construction time
via ``source_registry_info`` -- this module never imports ``echo.source``
or ``echo.verticals``, and never hard-codes a company or product name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from echo.core.ids import IdFactory
from echo.models.enums import ReliabilityTier
from echo.models.research import ResearchPacket, SourceAssessment
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.claims import build_claims, group_fact_candidates
from echo.research.config import ResearchConfig
from echo.research.confidence import packet_confidence
from echo.research.evidence import SourceRegistryInfo
from echo.research.extraction import extract_fact_candidates
from echo.research.independence import independent_source_count
from echo.research.source_selection import select_relevant_sources
from echo.research.status import determine_research_status
from echo.research.summary import build_summary
from echo.core.reliability import reliability_score
from echo.trend.signal_config import TrendSignalConfig


@dataclass(frozen=True)
class ResearchRunStats:
    """Observability for one ``research()`` call -- read
    ``RealResearchBrain.last_run`` after calling ``research()``. Never
    includes article bodies/excerpts, only counts (see
    docs/RESEARCH_INTELLIGENCE.md "Observability")."""

    sources_considered: int
    sources_selected: int
    claims_extracted: int  # fact candidates extracted, pre-grouping
    claims_grouped: int  # final ResearchClaim count, post-grouping
    conflicts_detected: int
    primary_source_present: bool
    independent_source_count: int
    confidence: float
    candidates_clustered: int = 0
    candidates_truncated: int = 0


class RealResearchBrain:
    def __init__(
        self,
        source_registry_info: dict[str, SourceRegistryInfo],
        research_config: ResearchConfig | None = None,
        signal_config: TrendSignalConfig | None = None,
        now: datetime | None = None,
    ) -> None:
        """
        Args:
            source_registry_info: source_key -> SourceRegistryInfo
                (reliability tier, primary-source flag, display name) --
                see echo.research.evidence.SourceRegistryInfo. Injected by
                the caller (CLI) from the loaded Source Registry so this
                module never imports echo.source.
            research_config: overrides for the deterministic
                claim-grouping/confidence/status thresholds; defaults to
                ResearchConfig().
            signal_config: reused for the source-selection time window
                (TrendSignalConfig.cluster_time_window_hours) -- see
                echo.research.source_selection. Defaults to
                TrendSignalConfig().
            now: fixes "the current time" for deterministic tests; when
                None, research() uses the real clock at call time.
        """
        self._source_registry_info = source_registry_info
        self._config = research_config or ResearchConfig()
        self._signal_config = signal_config or TrendSignalConfig()
        self._fixed_now = now
        self.last_run: ResearchRunStats | None = None

    def research(self, trend: TrendCandidate, sources: list[SourceItem], ids: IdFactory) -> ResearchPacket:
        now = self._fixed_now or datetime.now(timezone.utc)

        selection = select_relevant_sources(trend, sources, self._signal_config, self._config)
        selected = selection.selected

        candidates = extract_fact_candidates(selected, self._config)
        groups = group_fact_candidates(candidates, self._config)
        claims, evidence, conflicts = build_claims(groups, self._source_registry_info, self._config, ids)

        contributing_ids = {piece.source_item_id for piece in evidence}
        contributors = [item for item in selected if item.source_id in contributing_ids]
        independent_count = independent_source_count(contributors)
        primary_source_present = any(self._is_primary(item.source_key) for item in contributors)
        tier_a_present = any(self._tier(item.source_key) == ReliabilityTier.A for item in contributors)

        confidence = packet_confidence(
            primary_source_present=primary_source_present,
            tier_a_source_present=tier_a_present,
            independent_source_count=independent_count,
            claims=claims,
            conflicts=conflicts,
            evidence_count=len(evidence),
            config=self._config,
        )

        research_status = determine_research_status(
            evidence_count=len(evidence),
            independent_source_count=independent_count,
            primary_source_present=primary_source_present,
            confidence=confidence,
            conflicts=conflicts,
            config=self._config,
            claims=claims,
        )

        source_quality = self._aggregate_source_quality(contributors)
        key_facts = self._key_facts(claims) or [trend.topic]
        summary = build_summary(
            topic=trend.topic,
            claims=claims,
            source_count=independent_count,
            primary_source_present=primary_source_present,
            conflict_count=len(conflicts),
        )
        conflicting_information = any(
            conflict.severity.value != "potential" for conflict in conflicts
        )

        self.last_run = ResearchRunStats(
            sources_considered=selection.sources_considered,
            sources_selected=selection.sources_selected,
            claims_extracted=len(candidates),
            claims_grouped=len(claims),
            conflicts_detected=len(conflicts),
            primary_source_present=primary_source_present,
            independent_source_count=independent_count,
            confidence=confidence,
            candidates_clustered=selection.candidates_clustered,
            candidates_truncated=selection.candidates_truncated,
        )

        return ResearchPacket(
            research_id=ids.research_id(),
            trend_id=trend.trend_id,
            trace_id=trend.trace_id,
            summary=summary,
            key_facts=key_facts,
            sources=[item.source_id for item in selected],
            source_quality=source_quality,
            conflicting_information=conflicting_information,
            confidence=confidence,
            claims=claims,
            evidence=evidence,
            conflicts=conflicts,
            source_assessments=self._build_source_assessments(selected, evidence),
            primary_source_present=primary_source_present,
            independent_source_count=independent_count,
            research_status=research_status,
            researched_at=now,
        )

    def _tier(self, source_key: str) -> ReliabilityTier:
        info = self._source_registry_info.get(source_key)
        return info.reliability_tier if info else ReliabilityTier.C

    def _is_primary(self, source_key: str) -> bool:
        info = self._source_registry_info.get(source_key)
        return info.is_primary_source if info else False

    def _aggregate_source_quality(self, items: list[SourceItem]) -> float:
        if not items:
            return 0.0
        distinct_keys = {item.source_key for item in items}
        scores = [reliability_score(self._tier(key)) for key in distinct_keys]
        return max(0.0, min(1.0, sum(scores) / len(scores)))

    @staticmethod
    def _key_facts(claims: list) -> list[str]:
        ranked = sorted(claims, key=lambda c: c.confidence, reverse=True)
        return [claim.text for claim in ranked[:8]]

    def _build_source_assessments(
        self, items: list[SourceItem], evidence: list
    ) -> list[SourceAssessment]:
        item_counts: dict[str, int] = {}
        for item in items:
            item_counts[item.source_key] = item_counts.get(item.source_key, 0) + 1

        evidence_counts: dict[str, int] = {}
        for piece in evidence:
            evidence_counts[piece.source_key] = evidence_counts.get(piece.source_key, 0) + 1

        assessments = []
        for source_key in sorted(item_counts):
            info = self._source_registry_info.get(source_key)
            tier = info.reliability_tier if info else ReliabilityTier.C
            assessments.append(
                SourceAssessment(
                    source_key=source_key,
                    source_name=info.name if info else source_key,
                    reliability_tier=tier,
                    reliability_score=reliability_score(tier),
                    is_primary_source=info.is_primary_source if info else False,
                    item_count=item_counts[source_key],
                    evidence_count=evidence_counts.get(source_key, 0),
                )
            )
        return assessments
