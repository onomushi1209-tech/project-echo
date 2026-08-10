"""relevance: how well a candidate matches the vertical's topics.

Deterministic keyword matching against ``VerticalConfig.topic_keywords``
-- entirely config-driven. This module never contains a vertical-specific
word (no "OpenAI", "Claude", "LLM", ...); those live only in
``config/verticals/<id>.yaml`` (see docs/DEVELOPMENT_RULES.md rule 2).

Matching is case-insensitive; single-word alphanumeric keywords match on
word boundaries (so "ai" doesn't match inside "again"), multi-word /
punctuated keywords (e.g. "large language model") match as a substring.
score = min(1.0, matched_keyword_count / relevance_saturation_matches).
"""

from __future__ import annotations

import re

from echo.trend.signal_config import TrendSignalConfig

_ALNUM_RE = re.compile(r"[a-z0-9]+")


def relevance_score(
    text: str,
    topic_keywords: dict[str, list[str]],
    config: TrendSignalConfig,
) -> tuple[float, list[str]]:
    """Returns (score, matched_topic_ids) -- matched_topic_ids is sorted
    for determinism."""
    if config.relevance_saturation_matches <= 0:
        raise ValueError("relevance_saturation_matches must be > 0")
    if not topic_keywords:
        return 0.0, []

    lowered = text.lower()
    matched_topics: set[str] = set()
    match_count = 0
    for topic, keywords in topic_keywords.items():
        for keyword in keywords:
            if _contains_keyword(lowered, keyword.lower()):
                match_count += 1
                matched_topics.add(topic)

    score = max(0.0, min(1.0, match_count / config.relevance_saturation_matches))
    return score, sorted(matched_topics)


def _contains_keyword(haystack_lower: str, keyword_lower: str) -> bool:
    if not keyword_lower:
        return False
    if _ALNUM_RE.fullmatch(keyword_lower):
        return re.search(rf"\b{re.escape(keyword_lower)}\b", haystack_lower) is not None
    return keyword_lower in haystack_lower
