"""Deterministic text utilities shared across STEP 2 modules.

Pure, stdlib-only functions so ``echo.source.dedup`` and
``echo.trend.clustering`` / ``echo.trend.relevance`` all tokenize text
identically without importing from one another. No ML/embeddings --
STEP 2 uses token-overlap techniques only, by design (see
docs/SOURCE_INTELLIGENCE.md).
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "of", "in", "on", "for", "to", "with",
        "is", "are", "was", "were", "be", "been", "by", "at", "as", "it", "its",
        "this", "that", "these", "those", "from", "into", "new", "how", "what",
        "why", "will", "can", "could", "may", "might", "not", "no",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, length > 2, stopwords removed.

    Deterministic: same input always produces the same output, in the
    order tokens appear in ``text``.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """|intersection| / |union|, in [0, 1]. Two empty sets are defined as
    identical (1.0); one empty and one non-empty are defined as disjoint
    (0.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def capitalized_terms(text: str) -> set[str]:
    """Crude proper-noun-ish extraction: capitalized words, excluding the
    first word (sentence-starter capitalization isn't a signal) and
    all-caps acronyms shorter than 3 chars. Used as a lightweight
    'entity-like important terms' signal for clustering -- not NER."""
    words = text.split()
    terms: set[str] = set()
    for index, word in enumerate(words):
        stripped = re.sub(r"[^A-Za-z0-9]", "", word)
        if index == 0 or len(stripped) < 3:
            continue
        if stripped[0].isupper():
            terms.add(stripped.lower())
    return terms
