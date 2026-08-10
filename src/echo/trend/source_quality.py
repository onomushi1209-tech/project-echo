"""source_quality: aggregate reliability of the sources backing a cluster.

Deterministic mean of the reliability score (see
``echo.source.reliability``) across the *distinct* ``source_key`` values
contributing to a cluster. Using distinct sources (not per-item) means one
prolific low-tier source republishing the same story several times can't
drown out a single tier-A confirmation.
"""

from __future__ import annotations

from echo.models.source import SourceItem


def aggregate_source_quality(items: list[SourceItem], source_reliability: dict[str, float]) -> float:
    if not items:
        return 0.0
    distinct_keys = {item.source_key for item in items}
    scores = [source_reliability.get(key, 0.0) for key in distinct_keys]
    if not scores:
        return 0.0
    return max(0.0, min(1.0, sum(scores) / len(scores)))
