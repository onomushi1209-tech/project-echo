"""novelty: how much a candidate differs from recently detected trends.

Compares the candidate's topic tokens against every TrendCandidate
detected within ``novelty_lookback_hours``. If the most similar prior
trend is at/above ``novelty_similarity_threshold`` (token-Jaccard),
novelty drops proportionally to that similarity -- a near-exact repeat
(same topic, same headline, no new information) drives novelty toward 0;
a borderline match only dents it.

This is the deterministic *signal* a human reviewer's DUPLICATE_TOPIC /
NO_NEW_INFORMATION judgement (see ``echo.models.enums.RejectReason``) can
be informed by. STEP 2 only computes the signal -- it never assigns a
RejectReason itself; that decision stays with the Human Review Gate (see
docs/DEVELOPMENT_RULES.md).
"""

from __future__ import annotations

from datetime import datetime

from echo.core.text import jaccard_similarity, token_set
from echo.models.trend import TrendCandidate
from echo.trend.signal_config import TrendSignalConfig


def novelty_score(
    candidate_topic: str,
    recent_trends: list[TrendCandidate],
    now: datetime,
    config: TrendSignalConfig,
) -> float:
    candidate_tokens = token_set(candidate_topic)
    if not candidate_tokens:
        return 1.0

    max_similarity = 0.0
    for trend in recent_trends:
        age_hours = (now - trend.detected_at).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > config.novelty_lookback_hours:
            continue
        similarity = jaccard_similarity(candidate_tokens, token_set(trend.topic))
        max_similarity = max(max_similarity, similarity)

    if max_similarity < config.novelty_similarity_threshold:
        return 1.0

    # Linearly map [threshold, 1.0] similarity -> [0.5, 0.0] novelty: a
    # borderline match only dents novelty, a near-exact repeat drives it to 0.
    span = 1.0 - config.novelty_similarity_threshold
    if span <= 0:
        return 0.0
    over_threshold = (max_similarity - config.novelty_similarity_threshold) / span
    return max(0.0, 0.5 * (1.0 - over_threshold))
