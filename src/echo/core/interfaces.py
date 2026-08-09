"""Brain interfaces: the swappable logic behind each pipeline stage.

Echo Core depends only on these ``Protocol`` definitions, never on concrete
implementations. ``echo.brains`` ships dummy/stub implementations for
STEP 1; future steps can swap in real LLM-backed or vertical-specific
brains without touching ``echo.core`` or the ``echo.<stage>`` services.

Every method receives an ``IdFactory`` rather than inventing IDs itself, so
ID generation (and trace-id sequencing in particular) stays centralized and
testable -- see ``echo.core.ids`` and ``echo.core.trace``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from echo.core.ids import IdFactory
from echo.models.compliance import ComplianceResult
from echo.models.draft import ContentDraft
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate


class TrendBrain(Protocol):
    """DISCOVER stage: turns raw SourceItems into TrendCandidates."""

    def detect(
        self, sources: list[SourceItem], vertical: str, ids: IdFactory
    ) -> list[TrendCandidate]: ...


class ResearchBrain(Protocol):
    """RESEARCH stage: builds a ResearchPacket for a TrendCandidate."""

    def research(
        self, trend: TrendCandidate, sources: list[SourceItem], ids: IdFactory
    ) -> ResearchPacket: ...


class ScoringBrain(Protocol):
    """SCORE stage: scores a trend/research pair for opportunity."""

    def score(
        self, trend: TrendCandidate, research: ResearchPacket, ids: IdFactory
    ) -> OpportunityScore: ...


class ContentBrain(Protocol):
    """CREATE stage: drafts content from trend/research/score."""

    def draft(
        self,
        trend: TrendCandidate,
        research: ResearchPacket,
        score: OpportunityScore,
        ids: IdFactory,
    ) -> ContentDraft: ...


class ComplianceBrain(Protocol):
    """COMPLIANCE stage: flags risk in a drafted piece of content.

    Informational only -- never mutates the review outcome directly. The
    pipeline folds the result into ContentDraft.compliance_* fields so the
    Human Review Gate always makes the final call.
    """

    def check(self, draft: ContentDraft) -> ComplianceResult: ...


@dataclass(frozen=True)
class PipelineBrains:
    """The full set of brains one pipeline run needs, one per stage.

    Concrete implementations (e.g. ``echo.brains.default_brains()``) build
    this; ``echo.core.pipeline`` only ever depends on the Protocols above.
    """

    trend: TrendBrain
    research: ResearchBrain
    scoring: ScoringBrain
    content: ContentBrain
    compliance: ComplianceBrain
