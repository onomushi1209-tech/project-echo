"""Fact/Claim Extraction: SourceItem.title/content -> deterministic
FactCandidate sentences.

No LLM, no free-text generation -- this is deterministic sentence
splitting + normalization, exactly as documented in
docs/RESEARCH_INTELLIGENCE.md "LLM-free design". A future step can replace
this module with an LLM-based extractor without touching any other
``echo.research`` module: every caller only depends on
``extract_fact_candidates``'s signature (``list[SourceItem], ResearchConfig
-> list[FactCandidate]``), never on how sentences were produced.

Excludes: empty content, sentences shorter than
``ResearchConfig.min_sentence_length``, navigation-like fragments (fewer
than 3 meaningful words unless Japanese useful-text checks pass), and
sentences that exactly duplicate another sentence from
the *same* SourceItem (e.g. the title repeated verbatim in the summary).
Cross-source repetition is intentionally kept -- that's what
``echo.research.claims`` groups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from echo.core.text import japanese_runs, normalize_text
from echo.models.source import SourceItem
from echo.research.config import ResearchConfig

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])\s*")


@dataclass(frozen=True)
class FactCandidate:
    """One deterministically-extracted sentence, still tied to the
    SourceItem it came from -- the raw material ``echo.research.claims``
    groups into ``ResearchClaim``s and ``echo.research.confidence``/
    ``conflicts`` reason about."""

    text: str
    normalized_text: str
    source_item: SourceItem


def extract_fact_candidates(
    source_items: list[SourceItem], config: ResearchConfig
) -> list[FactCandidate]:
    candidates: list[FactCandidate] = []
    for item in source_items:
        seen_normalized: set[str] = set()
        for raw_sentence in _sentences(item):
            sentence = raw_sentence.strip()
            if not _is_usable(sentence, config):
                continue
            normalized = normalize_text(sentence)
            if not normalized or normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            candidates.append(FactCandidate(text=sentence, normalized_text=normalized, source_item=item))
    return candidates


def _sentences(item: SourceItem) -> list[str]:
    pieces = [item.title]
    if item.content:
        pieces.extend(_SENTENCE_SPLIT_RE.split(item.content))
    return pieces


def _is_usable(sentence: str, config: ResearchConfig) -> bool:
    if not sentence:
        return False
    if len(sentence) < config.min_sentence_length:
        return False
    useful = [char for char in normalize_text(sentence) if char.isalnum()]
    if not useful:
        return False
    japanese_count = sum(len(run) for run in japanese_runs(sentence))
    words = [word for word in sentence.split() if any(char.isalnum() for char in word)]
    english_words = sum(bool(re.search(r"[A-Za-z0-9]", word)) for word in words)
    # An English sentence may contain a short Japanese product name. Keep
    # its meaningful word route; whitespace/symbol padding is not a word.
    if len(words) >= 3 and (not japanese_count or english_words >= 3):
        return True
    if japanese_count:
        return (
            japanese_count >= 6
            and len(useful) >= config.min_sentence_length
            and len(set(useful)) >= 3
        )
    return False
