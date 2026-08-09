"""ID allocation for pipeline entities.

Keeps UUID/trace-ID generation out of brains and stage services so tests can
inject deterministic ID sources, and so trace IDs (which must be monotonic
per vertical/day, see echo.core.trace) always go through the shared
TraceIDGenerator rather than being invented ad hoc inside a brain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from echo.core.trace import TraceIDGenerator


def new_entity_id(prefix: str) -> str:
    """A short, storage-friendly unique id. Not a trace id -- see echo.core.trace."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class IdFactory:
    """Allocates every ID a pipeline run needs, passed into brains/services."""

    trace_generator: TraceIDGenerator

    def trace_id(self) -> str:
        return self.trace_generator.generate()

    def trend_id(self) -> str:
        return new_entity_id("trend")

    def research_id(self) -> str:
        return new_entity_id("research")

    def score_id(self) -> str:
        return new_entity_id("score")

    def draft_id(self) -> str:
        return new_entity_id("draft")

    def review_id(self) -> str:
        return new_entity_id("review")
