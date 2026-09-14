"""Conflict Detection: deterministic heuristics over pairs of fact-candidate
sentences that were grouped as "about the same subject" (see
echo.research.claims).

No full natural-language understanding -- STEP 3 scope (see
docs/RESEARCH_INTELLIGENCE.md "Conflict detection"). Four heuristics, tried
in order of confidence, each returning at most one ``ConflictSignal`` per
pair so a single mismatch is never double-counted:

  1. ``status_keyword`` -- one sentence uses a word from a known
     opposite-status pair (e.g. "released" / "delayed") that the other
     doesn't, while still sharing other context.
  2. ``date`` -- both sentences mention a date-like token and the tokens
     differ.
  3. ``negation`` -- otherwise near-identical sentences where exactly one
     contains a negation marker.
  4. ``numeric`` -- both sentences contain standalone numbers and the
     numbers differ.

Status contrasts require exclusive whole-word opposites and use remaining
context to choose severity. Later heuristics require subject overlap.
When a heuristic fires but the surrounding context match is thin, it uses
``ConflictSeverity.POTENTIAL`` instead of asserting a confirmed
contradiction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from echo.core.text import jaccard_similarity, token_set
from echo.models.enums import ConflictSeverity

_SUBJECT_OVERLAP_THRESHOLD = 0.25
_STRONG_OVERLAP_THRESHOLD = 0.5

_STATUS_OPPOSITES: tuple[tuple[str, str], ...] = (
    ("released", "delayed"),
    ("release", "delay"),
    ("launched", "delayed"),
    ("launches", "delays"),
    ("launched", "postponed"),
    ("available", "unavailable"),
    ("confirmed", "denied"),
    ("confirms", "denies"),
    ("approved", "rejected"),
    ("approved", "banned"),
    ("postponed", "confirmed"),
    ("cancelled", "confirmed"),
    ("canceled", "confirmed"),
    ("global", "limited"),
    ("globally", "regionally"),
    ("expands", "restricts"),
    ("increases", "decreases"),
    ("increased", "decreased"),
)

_NEGATION_MARKERS: tuple[str, ...] = (
    " not ",
    " no longer ",
    " never ",
    "n't ",
    "cancel",
    "denies",
    "denied",
    "postpone",
)

_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass(frozen=True)
class ConflictSignal:
    conflict_type: str
    reason: str
    severity: ConflictSeverity


def detect_conflict(text_a: str, text_b: str) -> ConflictSignal | None:
    """Check one pair of sentences for a deterministic conflict signal, or
    ``None`` if none of the heuristics fire."""
    if " ".join(text_a.casefold().split()) == " ".join(text_b.casefold().split()):
        return None
    status_hit = _check_status_keywords(text_a, text_b)
    if status_hit:
        return status_hit

    tokens_a, tokens_b = token_set(text_a), token_set(text_b)
    overlap = jaccard_similarity(tokens_a, tokens_b)
    if overlap < _SUBJECT_OVERLAP_THRESHOLD:
        return None

    date_hit = _check_dates(text_a, text_b, overlap)
    if date_hit:
        return date_hit

    negation_hit = _check_negation(text_a, text_b, overlap)
    if negation_hit:
        return negation_hit

    return _check_numeric(text_a, text_b, overlap)


def _check_status_keywords(text_a: str, text_b: str) -> ConflictSignal | None:
    lowered_a, lowered_b = text_a.casefold(), text_b.casefold()
    words_a = set(re.findall(r"\b\w+\b", lowered_a))
    words_b = set(re.findall(r"\b\w+\b", lowered_b))
    for word_x, word_y in _STATUS_OPPOSITES:
        # A statement containing both sides is ambiguous, not exclusive
        # evidence for either side. Whole words avoid available/unavailable.
        sides_a, sides_b = words_a & {word_x, word_y}, words_b & {word_x, word_y}
        found = (sides_a == {word_x} and sides_b == {word_y}) or (
            sides_a == {word_y} and sides_b == {word_x}
        )
        if not found:
            continue
        remainder_a = token_set(lowered_a) - {word_x, word_y}
        remainder_b = token_set(lowered_b) - {word_x, word_y}
        remainder_overlap = jaccard_similarity(remainder_a, remainder_b)
        severity = ConflictSeverity.MAJOR if remainder_overlap >= 0.15 else ConflictSeverity.POTENTIAL
        return ConflictSignal(
            conflict_type="status_keyword",
            reason=f"opposite-status keywords: {word_x!r} vs {word_y!r}",
            severity=severity,
        )
    return None


def _check_dates(text_a: str, text_b: str, overlap: float) -> ConflictSignal | None:
    dates_a = {m.group(0).lower() for m in _DATE_RE.finditer(text_a)}
    dates_b = {m.group(0).lower() for m in _DATE_RE.finditer(text_b)}
    if not dates_a or not dates_b or dates_a == dates_b:
        return None
    severity = ConflictSeverity.MAJOR if overlap >= _STRONG_OVERLAP_THRESHOLD else ConflictSeverity.POTENTIAL
    return ConflictSignal(
        conflict_type="date",
        reason=f"differing dates mentioned: {sorted(dates_a)} vs {sorted(dates_b)}",
        severity=severity,
    )


def _check_negation(text_a: str, text_b: str, overlap: float) -> ConflictSignal | None:
    if overlap < _STRONG_OVERLAP_THRESHOLD:
        return None
    has_negation_a = _has_negation(text_a)
    has_negation_b = _has_negation(text_b)
    if has_negation_a == has_negation_b:
        return None
    return ConflictSignal(
        conflict_type="negation",
        reason="near-identical statements where only one uses a negation",
        severity=ConflictSeverity.MAJOR,
    )


def _has_negation(text: str) -> bool:
    padded = f" {text.lower()} "
    return any(marker in padded for marker in _NEGATION_MARKERS)


def _check_numeric(text_a: str, text_b: str, overlap: float) -> ConflictSignal | None:
    numbers_a = {m.group(0) for m in _NUMBER_RE.finditer(text_a)}
    numbers_b = {m.group(0) for m in _NUMBER_RE.finditer(text_b)}
    if not numbers_a or not numbers_b or numbers_a == numbers_b:
        return None
    severity = ConflictSeverity.MINOR if overlap >= _STRONG_OVERLAP_THRESHOLD else ConflictSeverity.POTENTIAL
    return ConflictSignal(
        conflict_type="numeric",
        reason=f"differing numeric values mentioned: {sorted(numbers_a)} vs {sorted(numbers_b)}",
        severity=severity,
    )
