"""Echo pipeline skeleton:

    DISCOVER -> RESEARCH -> SCORE -> threshold check -> CREATE -> COMPLIANCE
    -> (queued for) HUMAN REVIEW

This module only *sequences* calls into the per-stage service modules
(``echo.trend``, ``echo.research``, ``echo.scoring``, ``echo.content``,
``echo.compliance``). It knows nothing about any specific vertical or brain
implementation -- both are supplied via ``PipelineDependencies``, keeping
Echo Core decoupled from ``echo.brains`` and ``echo.verticals``.

Human Review itself (``echo.review``) is a separate, pull-based stage: this
pipeline stops once a compliance-annotated draft is persisted and visible in
the review queue (``echo.review.service.pending_queue``). It never makes a
review decision on its own -- see docs/DEVELOPMENT_RULES.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo.compliance.service import apply_compliance, check_compliance
from echo.content.service import create_draft
from echo.core.ids import IdFactory
from echo.core.interfaces import PipelineBrains
from echo.core.trace import TraceIDGenerator
from echo.models.draft import ContentDraft
from echo.models.research import ResearchPacket
from echo.models.score import OpportunityScore
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.service import research_trend
from echo.scoring.service import passes_threshold, score_trend
from echo.storage.repository import EchoRepository
from echo.trend.service import discover_trends


@dataclass
class PipelineDependencies:
    brains: PipelineBrains
    repository: EchoRepository
    trace_generator: TraceIDGenerator
    score_threshold: float = 0.5


@dataclass
class PipelineItemResult:
    """Everything the pipeline produced for one detected trend."""

    trend: TrendCandidate
    research: ResearchPacket
    score: OpportunityScore
    passed_threshold: bool
    draft: ContentDraft | None


class EchoPipeline:
    """Vertical-agnostic orchestrator for DISCOVER..COMPLIANCE."""

    def __init__(self, deps: PipelineDependencies) -> None:
        self._deps = deps

    def run(self, sources: list[SourceItem]) -> list[PipelineItemResult]:
        ids = IdFactory(self._deps.trace_generator)
        vertical = self._deps.trace_generator.vertical

        trends = discover_trends(
            self._deps.brains.trend, sources, vertical, ids, self._deps.repository
        )

        results: list[PipelineItemResult] = []
        for trend in trends:
            research = research_trend(
                self._deps.brains.research, trend, sources, ids, self._deps.repository
            )
            score = score_trend(
                self._deps.brains.scoring, trend, research, ids, self._deps.repository
            )
            passed = passes_threshold(score, self._deps.score_threshold)

            draft: ContentDraft | None = None
            if passed:
                draft = create_draft(
                    self._deps.brains.content,
                    trend,
                    research,
                    score,
                    ids,
                    self._deps.repository,
                )
                compliance_result = check_compliance(self._deps.brains.compliance, draft)
                draft = apply_compliance(draft, compliance_result, self._deps.repository)

            results.append(
                PipelineItemResult(
                    trend=trend,
                    research=research,
                    score=score,
                    passed_threshold=passed,
                    draft=draft,
                )
            )
        return results
