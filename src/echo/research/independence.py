"""Source Independence: distinct source_key counting, never raw item count.

Two SourceItems from the same source_key (the same registered source
republishing / covering something twice) count as ONE independent source.
This is the single source of truth both claim-level and packet-level
independence counts go through -- see docs/RESEARCH_INTELLIGENCE.md
"Source independence".

Keyed purely on ``SourceItem.source_key`` (the Source Registry entry) for
STEP 3. Syndication/copied-article detection (the same underlying article
mirrored under two different registered sources) is a natural future
extension of this module without changing its call signature.
"""

from __future__ import annotations

from echo.models.source import SourceItem


def distinct_source_keys(items: list[SourceItem]) -> set[str]:
    return {item.source_key for item in items}


def independent_source_count(items: list[SourceItem]) -> int:
    return len(distinct_source_keys(items))
