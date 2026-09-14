"""Evidence construction: FactCandidate -> EvidenceItem.

``SourceRegistryInfo`` carries the handful of Source Registry facts
(``echo.source.config.SourceConfig.reliability_tier`` /
``primary_source`` / ``name``) evidence-building needs. It is injected by
the caller (``echo.brains.RealResearchBrain``, built from the CLI's loaded
Source Registry) -- this module never imports ``echo.source`` or
hard-codes a source's identity, per docs/DEVELOPMENT_RULES.md rule 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo.core.ids import IdFactory
from echo.models.enums import ReliabilityTier
from echo.models.research import EvidenceItem
from echo.research.config import ResearchConfig
from echo.research.extraction import FactCandidate


@dataclass(frozen=True)
class SourceRegistryInfo:
    name: str
    reliability_tier: ReliabilityTier
    is_primary_source: bool


def build_evidence_item(
    candidate: FactCandidate,
    registry_info: SourceRegistryInfo | None,
    config: ResearchConfig,
    ids: IdFactory,
) -> EvidenceItem:
    """Never carries a full article body -- ``excerpt`` is bounded to
    ``config.max_excerpt_length`` characters. ``registry_info=None`` (a
    source_key with no matching Source Registry entry) degrades safely to
    the lowest trust assumption rather than failing."""
    item = candidate.source_item
    return EvidenceItem(
        evidence_id=ids.evidence_id(),
        source_item_id=item.source_id,
        source_key=item.source_key,
        url=str(item.url),
        title=item.title,
        published_at=item.published_at,
        excerpt=candidate.text[: config.max_excerpt_length],
        is_primary_source=registry_info.is_primary_source if registry_info else False,
        reliability_tier=registry_info.reliability_tier if registry_info else ReliabilityTier.C,
    )
