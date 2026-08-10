"""velocity: how fast a topic is accumulating coverage right now.

Deliberately time-windowed rather than a raw item count, so a topic with
many *old* articles does not register as high-velocity just because it
has volume: each configured window (see
``TrendSignalConfig.velocity_windows``, e.g. 15m/1h/6h/24h) has a recency
weight, and an item only contributes the weight of the *tightest* window
it still falls within. An item older than every window contributes 0.

    score = min(1.0, weighted_count / velocity_saturation)
"""

from __future__ import annotations

from datetime import datetime

from echo.models.source import SourceItem
from echo.trend.signal_config import TrendSignalConfig


def velocity_score(items: list[SourceItem], now: datetime, config: TrendSignalConfig) -> float:
    if not items:
        return 0.0
    if config.velocity_saturation <= 0:
        raise ValueError("velocity_saturation must be > 0")

    weighted_count = sum(_weight_for_age(_age_hours(item, now), config) for item in items)
    return max(0.0, min(1.0, weighted_count / config.velocity_saturation))


def _age_hours(item: SourceItem, now: datetime) -> float:
    return max(0.0, (now - item.published_at).total_seconds() / 3600.0)


def _weight_for_age(age_hours: float, config: TrendSignalConfig) -> float:
    # Windows are configured tightest-first; use the first (smallest) one the item still fits in.
    for window in config.velocity_windows:
        if age_hours <= window.hours:
            return window.weight
    return 0.0
