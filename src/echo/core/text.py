"""Deterministic text utilities shared across STEP 2 modules.

Pure, stdlib-only functions so ``echo.source.dedup`` and
``echo.trend.clustering`` / ``echo.trend.relevance`` all tokenize text
identically without importing from one another. No ML/embeddings --
STEP 2 uses token-overlap techniques only, by design (see
docs/SOURCE_INTELLIGENCE.md).
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_JAPANESE_RUN_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fc\u3400-\u4dbf\u4e00-\u9fff]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "of", "in", "on", "for", "to", "with",
        "is", "are", "was", "were", "be", "been", "by", "at", "as", "it", "its",
        "this", "that", "these", "those", "from", "into", "new", "how", "what",
        "why", "will", "can", "could", "may", "might", "not", "no",
    }
)


def tokenize(text: str) -> list[str]:
    """ASCII tokens (length > 2, stopwords removed) plus Japanese bigrams.

    Deterministic: ASCII tokens retain input order, followed by Japanese
    run bigrams in their input order. Plain ASCII behavior is unchanged.
    """
    text = unicodedata.normalize("NFKC", text)
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]
    # Keep the ASCII branch unchanged. Japanese uses character bigrams:
    # deterministic overlap without a tokenizer dependency or empty sets.
    for run in japanese_runs(text):
        tokens.extend([run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
    return tokens


def japanese_runs(text: str) -> list[str]:
    """Japanese/CJK runs, with fullwidth/halfwidth forms normalized."""
    return _JAPANESE_RUN_RE.findall(unicodedata.normalize("NFKC", text))


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace -- generic free-text
    normalization shared by ``echo.source.dedup`` (as ``normalize_title``,
    kept for backward compatibility) and ``echo.research.extraction``."""
    lowered = unicodedata.normalize("NFKC", text).lower()
    no_punctuation = _PUNCT_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", no_punctuation).strip()


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
