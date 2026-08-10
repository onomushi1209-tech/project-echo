"""DISCOVER stage: service (thin orchestration) + signal algorithm modules.

``service.discover_trends`` is unchanged since STEP 1: it just calls the
injected brain and persists results. The signal modules below
(clustering/freshness/velocity/novelty/relevance/source_quality/
cross_source) are what a source-intelligence-aware brain
(``echo.brains.RealTrendBrain``) composes -- each is independently
testable and swappable, see docs/SOURCE_INTELLIGENCE.md.
"""

from echo.trend.clustering import Cluster, cluster_source_items
from echo.trend.cross_source import cross_source_confirmation_score
from echo.trend.freshness import freshness_score
from echo.trend.novelty import novelty_score
from echo.trend.relevance import relevance_score
from echo.trend.service import discover_trends, partition_trends_by_novelty
from echo.trend.signal_config import TrendSignalConfig, VelocityWindow
from echo.trend.source_quality import aggregate_source_quality
from echo.trend.velocity import velocity_score

__all__ = [
    "Cluster",
    "TrendSignalConfig",
    "VelocityWindow",
    "aggregate_source_quality",
    "cluster_source_items",
    "cross_source_confirmation_score",
    "discover_trends",
    "freshness_score",
    "novelty_score",
    "partition_trends_by_novelty",
    "relevance_score",
    "velocity_score",
]
