"""freshness: how recent a trend's representative item is.

Deterministic exponential decay: freshness halves every
``half_life_hours``. An item published right now scores ~1.0; one
half-life old scores 0.5; two half-lives old scores 0.25; and so on,
clamped to [0, 1]. A future ``published_at`` (clock skew) is treated as
age 0 rather than producing a score above 1.0.
"""

from __future__ import annotations

from datetime import datetime


def freshness_score(published_at: datetime, now: datetime, half_life_hours: float) -> float:
    if half_life_hours <= 0:
        raise ValueError("half_life_hours must be > 0")
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
    score = 0.5 ** (age_hours / half_life_hours)
    return max(0.0, min(1.0, score))
