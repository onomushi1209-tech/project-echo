"""cross_source_confirmation: how many independent registry sources are
reporting the same cluster right now.

    score = min(1.0, (distinct_source_count - 1) / (cross_source_saturation - 1))

A single contributing source gives 0.0 (nothing external has confirmed it
yet); ``cross_source_saturation`` distinct sources gives 1.0.
"""

from __future__ import annotations

from echo.models.source import SourceItem
from echo.trend.signal_config import TrendSignalConfig


def cross_source_confirmation_score(items: list[SourceItem], config: TrendSignalConfig) -> float:
    if config.cross_source_saturation <= 1:
        raise ValueError("cross_source_saturation must be > 1")
    distinct_keys = {item.source_key for item in items}
    count = len(distinct_keys)
    if count <= 1:
        return 0.0
    score = (count - 1) / (config.cross_source_saturation - 1)
    return max(0.0, min(1.0, score))
