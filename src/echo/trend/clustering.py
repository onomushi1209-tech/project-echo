"""Deterministic topic/event clustering over SourceItems.

Groups items that likely describe the same event using:
  - title token-overlap (Jaccard similarity)
  - shared capitalized "entity-like" terms (a crude proper-noun heuristic,
    not NER)
  - time proximity (a candidate item must fall within
    ``cluster_time_window_hours`` of the cluster's existing items)

No embeddings/LLM by design -- STEP 2 scope (see
docs/SOURCE_INTELLIGENCE.md), which also documents how this module's
``cluster_source_items`` call signature is meant to stay stable if a
future step swaps the similarity function for an embedding-based one.

Greedy single-pass algorithm: items are processed in ``published_at``
order so results are reproducible across runs given the same input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from echo.core.text import capitalized_terms, jaccard_similarity, token_set
from echo.models.source import SourceItem
from echo.trend.signal_config import TrendSignalConfig


@dataclass
class Cluster:
    items: list[SourceItem] = field(default_factory=list)
    title_tokens: set[str] = field(default_factory=set)
    entity_terms: set[str] = field(default_factory=set)

    @property
    def representative(self) -> SourceItem:
        """Earliest item in the cluster -- used as the cluster's topic/title."""
        return min(self.items, key=lambda item: item.published_at)

    @property
    def earliest_published_at(self):
        return min(item.published_at for item in self.items)

    @property
    def latest_published_at(self):
        return max(item.published_at for item in self.items)


def cluster_source_items(items: list[SourceItem], config: TrendSignalConfig) -> list[Cluster]:
    ordered = sorted(items, key=lambda item: item.published_at)
    clusters: list[Cluster] = []

    for item in ordered:
        item_tokens = token_set(item.title)
        item_entities = capitalized_terms(item.title)

        best_cluster: Cluster | None = None
        best_score = 0.0
        for cluster in clusters:
            if not _within_time_window(item, cluster, config.cluster_time_window_hours):
                continue
            score = _similarity(item_tokens, item_entities, cluster, config)
            if score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster is not None and best_score >= config.cluster_similarity_threshold:
            best_cluster.items.append(item)
            best_cluster.title_tokens |= item_tokens
            best_cluster.entity_terms |= item_entities
        else:
            clusters.append(Cluster(items=[item], title_tokens=item_tokens, entity_terms=item_entities))

    return clusters


def _within_time_window(item: SourceItem, cluster: Cluster, window_hours: float) -> bool:
    delta_earliest = abs((item.published_at - cluster.earliest_published_at).total_seconds()) / 3600.0
    delta_latest = abs((item.published_at - cluster.latest_published_at).total_seconds()) / 3600.0
    return min(delta_earliest, delta_latest) <= window_hours


def _similarity(
    item_tokens: set[str], item_entities: set[str], cluster: Cluster, config: TrendSignalConfig
) -> float:
    title_similarity = jaccard_similarity(item_tokens, cluster.title_tokens)
    entity_similarity = (
        jaccard_similarity(item_entities, cluster.entity_terms)
        if (item_entities and cluster.entity_terms)
        else 0.0
    )
    return config.cluster_title_weight * title_similarity + config.cluster_entity_weight * entity_similarity
