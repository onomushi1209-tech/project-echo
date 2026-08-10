"""RealTrendBrain: a source-intelligence-aware TrendBrain.

Coexists with ``DummyTrendBrain`` (STEP 1) -- both satisfy the same,
unchanged ``echo.core.interfaces.TrendBrain`` Protocol, so
``echo.trend.service.discover_trends`` and ``echo.core.pipeline`` work
with either without modification.

Clusters incoming SourceItems into events (``echo.trend.clustering``) and
scores each cluster with the STEP 2 signal modules (freshness/velocity/
novelty/relevance/source_quality/cross_source). All vertical- and
source-specific data (topic keywords, source reliability, recently
detected trends for novelty comparison) is injected at construction time
-- this module never imports ``echo.verticals`` or ``echo.storage``, and
never hard-codes a company or product name.
"""

from __future__ import annotations

from datetime import datetime, timezone

from echo.core.ids import IdFactory
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.trend.clustering import cluster_source_items
from echo.trend.cross_source import cross_source_confirmation_score
from echo.trend.freshness import freshness_score
from echo.trend.novelty import novelty_score
from echo.trend.relevance import relevance_score
from echo.trend.signal_config import TrendSignalConfig
from echo.trend.source_quality import aggregate_source_quality
from echo.trend.velocity import velocity_score


class RealTrendBrain:
    def __init__(
        self,
        topic_keywords: dict[str, list[str]],
        source_reliability: dict[str, float],
        recent_trends: list[TrendCandidate],
        signal_config: TrendSignalConfig | None = None,
        now: datetime | None = None,
    ) -> None:
        """
        Args:
            topic_keywords: VerticalConfig.topic_keywords for the target
                vertical -- drives relevance scoring.
            source_reliability: source_key -> reliability score in [0, 1]
                (see echo.source.reliability.reliability_score), drives
                source_quality.
            recent_trends: previously detected TrendCandidates to compare
                against for novelty. Callers typically pass a fixed
                snapshot from EchoRepository.list_trends() taken once
                before detect() runs.
            signal_config: overrides for the deterministic scoring
                thresholds; defaults to TrendSignalConfig().
            now: fixes "the current time" for deterministic tests; when
                None, detect() uses the real clock at call time.
        """
        self._topic_keywords = topic_keywords
        self._source_reliability = source_reliability
        self._recent_trends = recent_trends
        self._config = signal_config or TrendSignalConfig()
        self._fixed_now = now

    def detect(self, sources: list[SourceItem], vertical: str, ids: IdFactory) -> list[TrendCandidate]:
        if not sources:
            return []

        now = self._fixed_now or datetime.now(timezone.utc)
        clusters = cluster_source_items(sources, self._config)

        candidates: list[TrendCandidate] = []
        for cluster in clusters:
            representative = cluster.representative
            topic = representative.title
            combined_text = " ".join([topic, *(item.content for item in cluster.items)])

            relevance, matched_topics = relevance_score(combined_text, self._topic_keywords, self._config)
            keywords = sorted(set(sorted(cluster.title_tokens)[:8]) | set(matched_topics))

            candidates.append(
                TrendCandidate(
                    trend_id=ids.trend_id(),
                    trace_id=ids.trace_id(),
                    topic=topic,
                    keywords=keywords,
                    sources=[item.source_id for item in cluster.items],
                    detected_at=now,
                    velocity=velocity_score(cluster.items, now, self._config),
                    novelty=novelty_score(topic, self._recent_trends, now, self._config),
                    relevance=relevance,
                    vertical=vertical,
                    freshness=freshness_score(
                        representative.published_at, now, self._config.freshness_half_life_hours
                    ),
                    source_quality=aggregate_source_quality(cluster.items, self._source_reliability),
                    source_count=len(cluster.items),
                    cross_source_confirmation=cross_source_confirmation_score(cluster.items, self._config),
                )
            )
        return candidates
