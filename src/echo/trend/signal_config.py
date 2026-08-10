"""TrendSignalConfig: tunable parameters for every echo.trend signal module.

A single, documented source of truth so freshness/velocity/novelty/
relevance/clustering thresholds aren't scattered as magic numbers across
modules. Defaults are deliberately conservative starting points for
STEP 2. Override via the constructor, or via
``echo.config.settings.Settings.trend_signal_config()`` for the handful of
knobs exposed through environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VelocityWindow:
    hours: float
    weight: float


DEFAULT_VELOCITY_WINDOWS: tuple[VelocityWindow, ...] = (
    VelocityWindow(hours=0.25, weight=4.0),  # last 15 minutes
    VelocityWindow(hours=1.0, weight=2.0),  # last 1 hour
    VelocityWindow(hours=6.0, weight=1.0),  # last 6 hours
    VelocityWindow(hours=24.0, weight=0.4),  # last 24 hours
)


@dataclass(frozen=True)
class TrendSignalConfig:
    # freshness: exponential decay half-life (see echo.trend.freshness)
    freshness_half_life_hours: float = 6.0

    # velocity: recency-weighted windowed item counts (see echo.trend.velocity)
    velocity_windows: tuple[VelocityWindow, ...] = DEFAULT_VELOCITY_WINDOWS
    velocity_saturation: float = 6.0  # weighted count that maps to score 1.0

    # novelty: compare against recently detected trends (see echo.trend.novelty)
    novelty_lookback_hours: float = 72.0
    novelty_similarity_threshold: float = 0.6  # token-Jaccard at/above this counts as "same topic"

    # relevance: keyword matching against VerticalConfig.topic_keywords (see echo.trend.relevance)
    relevance_saturation_matches: int = 3  # matched-keyword count that maps to score 1.0

    # clustering (see echo.trend.clustering)
    cluster_time_window_hours: float = 12.0
    cluster_similarity_threshold: float = 0.35
    cluster_title_weight: float = 0.7
    cluster_entity_weight: float = 0.3

    # cross-source confirmation (see echo.trend.cross_source)
    cross_source_saturation: int = 4  # distinct source_key count that maps to score 1.0

    # Pre-Commit Hardening: a TrendCandidate with novelty below this is a
    # near-exact repeat of an already-persisted trend (see echo.trend.novelty)
    # and is not written to the `trends` table -- see
    # echo.trend.service.partition_trends_by_novelty and
    # docs/SOURCE_INTELLIGENCE.md "Trend persistence guard".
    trend_persistence_novelty_threshold: float = 0.10
