from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.core.ids import IdFactory
from echo.core.trace import InMemorySequenceProvider, TraceIDGenerator
from echo.models.enums import ClaimStatus, ReliabilityTier
from echo.models.source import SourceItem
from echo.research.claims import build_claims, group_fact_candidates
from echo.research.config import ResearchConfig
from echo.research.evidence import SourceRegistryInfo
from echo.research.extraction import FactCandidate

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = ResearchConfig()


def _ids() -> IdFactory:
    return IdFactory(TraceIDGenerator(vertical="ai", sequence_provider=InMemorySequenceProvider()))


def _item(source_id: str, source_key: str, minutes_ago: int = 0) -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key=source_key,
        url=f"https://example.com/{source_id}",
        source_name=source_key,
        title="Title",
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content="",
        language="en",
        vertical="ai",
    )


def _candidate(text: str, source_id: str, source_key: str, minutes_ago: int = 0) -> FactCandidate:
    item = _item(source_id, source_key, minutes_ago)
    return FactCandidate(text=text, normalized_text=text.lower(), source_item=item)


def test_similar_sentences_from_different_sources_group_together() -> None:
    candidates = [
        _candidate("Research lab releases new model today", "a", "s1", minutes_ago=5),
        _candidate("Research lab has released a new model", "b", "s2", minutes_ago=8),
        _candidate("Research lab release of new model confirmed", "c", "s3", minutes_ago=10),
    ]
    groups = group_fact_candidates(candidates, CONFIG)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_dissimilar_sentences_form_separate_groups() -> None:
    candidates = [
        _candidate("Research lab releases new model today", "a", "s1"),
        _candidate("Quarterly earnings beat analyst expectations", "b", "s2"),
    ]
    groups = group_fact_candidates(candidates, CONFIG)
    assert len(groups) == 2


def test_single_candidate_forms_its_own_group() -> None:
    groups = group_fact_candidates([_candidate("Solo headline about something", "a", "s1")], CONFIG)
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_empty_input_produces_no_groups() -> None:
    assert group_fact_candidates([], CONFIG) == []


_REGISTRY = {
    "official_blog": SourceRegistryInfo(name="Official Blog", reliability_tier=ReliabilityTier.A, is_primary_source=True),
    "news_a": SourceRegistryInfo(name="News A", reliability_tier=ReliabilityTier.B, is_primary_source=False),
    "news_b": SourceRegistryInfo(name="News B", reliability_tier=ReliabilityTier.C, is_primary_source=False),
}


def test_multi_source_agreement_produces_confirmed_claim() -> None:
    candidates = [
        _candidate("Research lab releases new model today", "a", "official_blog", minutes_ago=5),
        _candidate("Research lab has released a new model", "b", "news_a", minutes_ago=8),
    ]
    groups = group_fact_candidates(candidates, CONFIG)
    claims, evidence, conflicts = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert len(claims) == 1
    assert claims[0].status == ClaimStatus.CONFIRMED
    assert set(claims[0].supporting_source_ids) == {"official_blog", "news_a"}
    assert claims[0].contradicting_source_ids == []
    assert conflicts == []
    assert len(evidence) == 2


def test_contradicting_sentences_grouped_but_flagged_conflicted() -> None:
    # The earliest-published item becomes the claim's representative
    # (matching echo.trend.clustering's "earliest = representative"
    # convention) -- official_blog published first (minutes_ago=8, further
    # back), news_a's contradicting follow-up came later (minutes_ago=5).
    candidates = [
        _candidate("Product X released today", "a", "official_blog", minutes_ago=8),
        _candidate("Product X release delayed", "b", "news_a", minutes_ago=5),
    ]
    groups = group_fact_candidates(candidates, CONFIG)
    claims, evidence, conflicts = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert len(claims) == 1  # grouped as the same subject, not two unrelated claims
    assert claims[0].status == ClaimStatus.CONFLICTED
    assert "official_blog" in claims[0].supporting_source_ids
    assert "news_a" in claims[0].contradicting_source_ids
    assert len(conflicts) == 1
    assert conflicts[0].claim_id == claims[0].claim_id


def test_single_source_from_primary_is_single_source_status() -> None:
    candidates = [_candidate("Official breaking announcement today", "a", "official_blog", minutes_ago=1)]
    groups = group_fact_candidates(candidates, CONFIG)
    claims, _, _ = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert claims[0].status == ClaimStatus.SINGLE_SOURCE


def test_single_source_from_discovery_tier_is_unverified() -> None:
    candidates = [_candidate("Minor blog mentions a rumor today", "a", "news_b", minutes_ago=1)]
    groups = group_fact_candidates(candidates, CONFIG)
    claims, _, _ = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert claims[0].status == ClaimStatus.UNVERIFIED


def test_unknown_source_key_defaults_to_lowest_trust() -> None:
    candidates = [_candidate("Unregistered source reports something today", "a", "ghost_source", minutes_ago=1)]
    groups = group_fact_candidates(candidates, CONFIG)
    claims, evidence, _ = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert claims[0].status == ClaimStatus.UNVERIFIED
    assert evidence[0].reliability_tier == ReliabilityTier.C
    assert evidence[0].is_primary_source is False


def test_evidence_excerpt_is_bounded_length() -> None:
    long_text = "Official breaking announcement today about a major event " * 10
    candidates = [_candidate(long_text.strip(), "a", "official_blog", minutes_ago=1)]
    groups = group_fact_candidates(candidates, CONFIG)
    _, evidence, _ = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert len(evidence[0].excerpt) <= CONFIG.max_excerpt_length


def test_evidence_traces_back_to_source_item_and_url() -> None:
    candidates = [_candidate("Official breaking announcement today", "src-42", "official_blog", minutes_ago=1)]
    groups = group_fact_candidates(candidates, CONFIG)
    _, evidence, _ = build_claims(groups, _REGISTRY, CONFIG, _ids())

    assert evidence[0].source_item_id == "src-42"
    assert evidence[0].url == "https://example.com/src-42"
