"""Source & Trend Intelligence: acquisition layer.

    Source Registry -> Fetch -> Normalize -> Deduplicate -> (persisted SourceItems)

This package owns everything up to a clean, deduplicated SourceItem in
storage. Turning those SourceItems into TrendCandidates (clustering,
signal scoring) is ``echo.trend`` + ``echo.brains.RealTrendBrain`` --
see docs/SOURCE_INTELLIGENCE.md.

Nothing here hard-codes a specific vertical or company name; source
identity/reliability/enablement all come from ``config/sources/*.yaml``
via ``echo.source.registry``.
"""

from echo.source.config import SourceConfig
from echo.source.ingest import IngestReport, SourceIngestReport, ingest_sources
from echo.source.registry import (
    SourceRegistryError,
    SourceRegistryNotFoundError,
    enabled_sources,
    load_source_registry,
)

__all__ = [
    "IngestReport",
    "SourceConfig",
    "SourceIngestReport",
    "SourceRegistryError",
    "SourceRegistryNotFoundError",
    "enabled_sources",
    "ingest_sources",
    "load_source_registry",
]
