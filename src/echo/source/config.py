"""SourceConfig: the schema every ``config/sources/*.yaml`` entry must satisfy.

This is the Source Registry's contract. Nothing outside ``echo.source``
(and the CLI, which loads it) should need to know how source config is
stored -- callers get validated ``SourceConfig`` objects.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, PositiveInt

from echo.models.enums import ReliabilityTier, SourceType


class SourceConfig(BaseModel):
    """One registered information source for a vertical."""

    id: str = Field(min_length=1, description="Stable registry key, e.g. 'nvidia_blog'")
    name: str = Field(min_length=1, description="Human-readable display name")
    url: HttpUrl
    source_type: SourceType
    enabled: bool = True
    vertical: str = Field(min_length=1)
    reliability_tier: ReliabilityTier
    language: str = Field(default="en", min_length=2, max_length=8)
    polling_interval: int = Field(gt=0, default=60, description="Minutes between polls")
    primary_source: bool = Field(
        default=False, description="Official/first-party source for its organization"
    )

    # Ingestion upper bounds (per-source override, config-driven -- see
    # docs/SOURCE_INTELLIGENCE.md "Ingestion upper bounds"). Applied at the
    # normalize/ingest boundary (echo.source.ingest), never in a parser.
    # None disables the respective bound for that source.
    max_items_per_fetch: PositiveInt | None = Field(
        default=200,
        description=(
            "Cap on items accepted from one fetch, applied after "
            "normalization and the age bound, keeping the newest "
            "(by published_at) items. None disables the cap."
        ),
    )
    max_item_age_hours: PositiveInt | None = Field(
        default=168,
        description=(
            "Items older than this many hours (by published_at, falling "
            "back to retrieved_at when published_at is missing/malformed "
            "-- see echo.source.normalize) are dropped. None disables the "
            "bound."
        ),
    )
