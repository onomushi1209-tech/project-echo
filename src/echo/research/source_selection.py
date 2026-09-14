"""Relevant Source Collection: TrendCandidate.sources -> a bounded list of
SourceItems to research.

Deliberately does not trust ``TrendCandidate.sources`` alone -- SourceItems
ingested *after* the trend was detected may describe the same event and
should be pulled in too. Re-derives "same event" membership with
``echo.trend.clustering.cluster_source_items`` (STEP 2's own clustering
module, reused rather than copied -- see docs/RESEARCH_INTELLIGENCE.md).

Performance safeguard: narrow the supplied history to the trend time window,
then bound clustering input by direct-anchor priority, recency and stable ID.
The history scan/ranking still scales with input; clustering input is capped.
The final source cap is separate. See docs/RESEARCH_INTELLIGENCE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import nsmallest

from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.config import ResearchConfig
from echo.trend.clustering import cluster_source_items
from echo.trend.signal_config import TrendSignalConfig


@dataclass(frozen=True)
class SourceSelectionResult:
    selected: list[SourceItem]
    sources_considered: int
    sources_selected: int
    candidates_clustered: int = 0
    candidates_truncated: int = 0


def select_relevant_sources(
    trend: TrendCandidate,
    all_items: list[SourceItem],
    signal_config: TrendSignalConfig,
    research_config: ResearchConfig,
) -> SourceSelectionResult:
    """Return the SourceItems relevant to ``trend``, newest-first, capped
    at ``research_config.max_research_sources``."""
    direct_ids = set(trend.sources)
    direct_matches = [item for item in all_items if item.source_id in direct_ids]

    if not direct_matches:
        return SourceSelectionResult(selected=[], sources_considered=0, sources_selected=0)

    window_hours = signal_config.cluster_time_window_hours
    earliest = min(item.published_at for item in direct_matches)
    latest = max(item.published_at for item in direct_matches)

    candidate_pool = [
        item
        for item in all_items
        if item.source_id in direct_ids
        or _within_hours(item.published_at, earliest, window_hours)
        or _within_hours(item.published_at, latest, window_hours)
    ]

    # Preserve direct-trend anchors before expansion candidates, then prefer
    # recency. Stable IDs break timestamp ties regardless of input order.
    bounded_pool = nsmallest(
        research_config.max_research_candidates, candidate_pool,
        key=lambda item: (item.source_id not in direct_ids, -item.published_at.timestamp(), item.source_id),
    )
    clusters = cluster_source_items(bounded_pool, signal_config)

    selected_by_id: dict[str, SourceItem] = {}
    for cluster in clusters:
        cluster_ids = {item.source_id for item in cluster.items}
        if cluster_ids & direct_ids:
            for item in cluster.items:
                selected_by_id[item.source_id] = item

    # Keep bounded direct anchors even if the clustering implementation
    # changes; never reintroduce candidates excluded by the precluster cap.
    for item in bounded_pool:
        if item.source_id in direct_ids:
            selected_by_id[item.source_id] = item

    ordered = sorted(selected_by_id.values(), key=lambda item: (-item.published_at.timestamp(), item.source_id))
    capped = ordered[: research_config.max_research_sources]

    return SourceSelectionResult(
        selected=capped,
        sources_considered=len(candidate_pool),
        sources_selected=len(capped),
        candidates_clustered=len(bounded_pool),
        candidates_truncated=len(candidate_pool) - len(bounded_pool),
    )


def _within_hours(when, anchor, window_hours: float) -> bool:
    return abs((when - anchor).total_seconds()) / 3600.0 <= window_hours
