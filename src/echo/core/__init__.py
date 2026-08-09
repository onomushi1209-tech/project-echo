"""Echo Core: vertical-agnostic pipeline engine.

Nothing in this package may import from ``echo.verticals`` or reference a
specific vertical id (e.g. ``"ai"``). Vertical behavior is injected at the
edges (brains, config) -- see docs/ARCHITECTURE.md.
"""

from echo.core.ids import IdFactory
from echo.core.interfaces import (
    ComplianceBrain,
    ContentBrain,
    PipelineBrains,
    ResearchBrain,
    ScoringBrain,
    TrendBrain,
)
from echo.core.pipeline import EchoPipeline, PipelineDependencies, PipelineItemResult
from echo.core.trace import InMemorySequenceProvider, TraceIDGenerator, format_trace_id, parse_trace_id

__all__ = [
    "ComplianceBrain",
    "ContentBrain",
    "EchoPipeline",
    "IdFactory",
    "InMemorySequenceProvider",
    "PipelineBrains",
    "PipelineDependencies",
    "PipelineItemResult",
    "ResearchBrain",
    "ScoringBrain",
    "TraceIDGenerator",
    "TrendBrain",
    "format_trace_id",
    "parse_trace_id",
]
