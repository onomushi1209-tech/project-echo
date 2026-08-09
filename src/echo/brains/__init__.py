"""Dummy/stub brain implementations for STEP 1.

These satisfy the Protocols in ``echo.core.interfaces`` with deterministic,
offline logic -- no external AI APIs are called. Each stage's brain can be
swapped independently in later steps without touching ``echo.core`` or the
``echo.<stage>`` service modules.
"""

from __future__ import annotations

from echo.brains.dummy_compliance_brain import DummyComplianceBrain
from echo.brains.dummy_content_brain import DummyContentBrain
from echo.brains.dummy_research_brain import DummyResearchBrain
from echo.brains.dummy_scoring_brain import DummyScoringBrain
from echo.brains.dummy_trend_brain import DummyTrendBrain
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
    "default_brains",
]
