"""URL canonicalization and deduplication.

Deterministic and testable by design (per STEP 2 scope): no ML/embeddings.
Exact duplicates are caught by canonical URL or content fingerprint
equality; near duplicates by title token-overlap (Jaccard similarity)
against a configurable threshold.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from echo.core.text import jaccard_similarity, token_set
from echo.models.source import SourceItem

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {
    "gclid", "fbclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "spm", "icid", "cmp", "yclid", "msclkid",
}
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8


def canonicalize_url(url: str) -> str:
    """Lowercase scheme/host, drop default ports and fragment, strip known
    tracking params, sort remaining query params -- so trivially different
    URLs pointing at the same article compare equal."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_param(k)
    )
    query = urlencode(query_pairs)

    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    lowered = title.lower()
    no_punctuation = _PUNCT_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", no_punctuation).strip()


def content_fingerprint(title: str, content: str) -> str:
    """Deterministic sha256 fingerprint over normalized title + a content
    prefix. Two items with the same fingerprint are exact duplicates even
    if their URLs differ (e.g. syndicated/mirrored articles)."""
    basis = normalize_title(title) + "|" + normalize_title(content)[:500]
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


class DedupDecision(str, Enum):
    KEEP = "keep"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"


@dataclass(frozen=True)
class DedupOutcome:
    decision: DedupDecision
    canonical_url: str
    fingerprint: str
    reason: str | None = None


class Deduplicator:
    """Stateful de-duplicator, seedable with previously-seen state so
    cross-run duplicates (not just within-batch ones) are caught too."""

    def __init__(
        self,
        seen_canonical_urls: set[str] | None = None,
        seen_fingerprints: set[str] | None = None,
        seen_title_tokens: list[set[str]] | None = None,
        near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
    ) -> None:
        self._seen_urls: set[str] = set(seen_canonical_urls or ())
        self._seen_fingerprints: set[str] = set(seen_fingerprints or ())
        self._seen_title_tokens: list[set[str]] = list(seen_title_tokens or ())
        self._threshold = near_duplicate_threshold

    def evaluate(self, item: SourceItem) -> DedupOutcome:
        canonical = canonicalize_url(str(item.url))
        fingerprint = content_fingerprint(item.title, item.content)

        if canonical in self._seen_urls:
            return DedupOutcome(DedupDecision.EXACT_DUPLICATE, canonical, fingerprint, "canonical_url already seen")
        if fingerprint in self._seen_fingerprints:
            return DedupOutcome(
                DedupDecision.EXACT_DUPLICATE, canonical, fingerprint, "content fingerprint already seen"
            )

        title_tokens = token_set(item.title)
        for prior_tokens in self._seen_title_tokens:
            if jaccard_similarity(title_tokens, prior_tokens) >= self._threshold:
                return DedupOutcome(
                    DedupDecision.NEAR_DUPLICATE, canonical, fingerprint, "title token overlap >= threshold"
                )

        return DedupOutcome(DedupDecision.KEEP, canonical, fingerprint)

    def record(self, item: SourceItem, outcome: DedupOutcome) -> None:
        self._seen_urls.add(outcome.canonical_url)
        self._seen_fingerprints.add(outcome.fingerprint)
        self._seen_title_tokens.append(token_set(item.title))

    def process(self, item: SourceItem) -> DedupOutcome:
        """Evaluate and, on KEEP, record in one call -- the common case."""
        outcome = self.evaluate(item)
        if outcome.decision == DedupDecision.KEEP:
            self.record(item, outcome)
        return outcome


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_PARAM_NAMES or any(lowered.startswith(p) for p in _TRACKING_PARAM_PREFIXES)
