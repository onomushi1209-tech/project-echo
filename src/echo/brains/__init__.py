"""Brain implementations: the swappable logic behind each pipeline stage.

STEP 1 shipped deterministic, offline dummy implementations only (no
external AI APIs). STEP 2 adds ``RealTrendBrain``, a source-intelligence
-aware DISCOVER-stage brain that clusters real SourceItems and scores them.
STEP 3 adds ``RealResearchBrain``, a source-intelligence-aware
RESEARCH-stage brain (claims/evidence/conflicts/confidence). Both call no
external AI API and coexist with their Dummy counterpart; each satisfies
the same Protocol as its Dummy sibling (``TrendBrain`` /
``ResearchBrain``). Each stage's brain can be swapped independently
without touching ``echo.core`` or the ``echo.<stage>`` service modules.
"""

from __future__ import annotations

from echo.brains.dummy_compliance_brain import DummyComplianceBrain
from echo.brains.dummy_content_brain import DummyContentBrain
from echo.brains.dummy_research_brain import DummyResearchBrain
from echo.brains.dummy_scoring_brain import DummyScoringBrain
from echo.brains.dummy_trend_brain import DummyTrendBrain
from echo.brains.real_research_brain import RealResearchBrain
from echo.brains.real_trend_brain import RealTrendBrain
from echo.core.interfaces import PipelineBrains


def default_brains() -> PipelineBrains:
    """The STEP 1 dummy brain set used by ``echo demo`` and tests."""
    return PipelineBrains(
        trend=DummyTrendBrain(),
        research=DummyResearchBrain(),
        scoring=DummyScoringBrain(),
        content=DummyContentBrain(),
        compliance=DummyComplianceBrain(),
    )


__all__ = [
    "DummyComplianceBrain",
    "DummyContentBrain",
    "DummyResearchBrain",
    "DummyScoringBrain",
    "DummyTrendBrain",
    "RealResearchBrain",
    "RealTrendBrain",
    "default_brains",
]
