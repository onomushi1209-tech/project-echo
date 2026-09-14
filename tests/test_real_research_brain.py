"""End-to-end RealResearchBrain tests -- the fixture scenarios (A-F) from
the STEP 3 implementation brief, run through the full detect-free research
pipeline. All offline, synthetic (example.com) data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from echo.brains.real_research_brain import RealResearchBrain
from echo.core.ids import IdFactory
from echo.core.trace import InMemorySequenceProvider, TraceIDGenerator
from echo.models.enums import ClaimStatus, ReliabilityTier, ResearchStatus
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.research.evidence import SourceRegistryInfo
from echo.research.config import ResearchConfig

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

REGISTRY = {
    "official_blog": SourceRegistryInfo(name="Official Blog", reliability_tier=ReliabilityTier.A, is_primary_source=True),
    "news_a": SourceRegistryInfo(name="News A", reliability_tier=ReliabilityTier.B, is_primary_source=False),
    "news_b": SourceRegistryInfo(name="News B", reliability_tier=ReliabilityTier.C, is_primary_source=False),
}


def _ids() -> IdFactory:
    return IdFactory(TraceIDGenerator(vertical="ai", sequence_provider=InMemorySequenceProvider()))


def _item(source_id: str, source_key: str, title: str, minutes_ago: int = 5) -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_key=source_key,
        url=f"https://{source_key}.example.com/{source_id}",
        source_name=source_key,
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content="",
        language="en",
        vertical="ai",
    )


def _trend(sources: list[SourceItem], topic: str) -> TrendCandidate:
    return TrendCandidate(
        trend_id="trend-1", trace_id="ECHO-AI-20260809-000001", topic=topic,
        sources=[s.source_id for s in sources], detected_at=NOW,
        velocity=0.5, novelty=1.0, relevance=1.0, vertical="ai",
    )


def _brain() -> RealResearchBrain:
    return RealResearchBrain(source_registry_info=REGISTRY, now=NOW)


def test_fixture_a_three_sources_agree() -> None:
    sources = [
        _item("s1", "official_blog", "AI lab confirms new model release today", minutes_ago=5),
        _item("s2", "news_a", "AI lab has confirmed a new model release", minutes_ago=8),
        _item("s3", "news_b", "AI lab release of new model confirmed", minutes_ago=12),
    ]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.independent_source_count == 3
    assert packet.primary_source_present is True
    assert packet.research_status == ResearchStatus.READY
    assert any(c.status == ClaimStatus.CONFIRMED for c in packet.claims)
    assert packet.conflicts == []


def test_fixture_b_single_primary_source() -> None:
    sources = [_item("s1", "official_blog", "Official breaking announcement made today", minutes_ago=1)]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.independent_source_count == 1
    assert packet.primary_source_present is True
    assert packet.research_status == ResearchStatus.READY
    assert any(c.status == ClaimStatus.SINGLE_SOURCE for c in packet.claims)


def test_fixture_c_one_source_contradicts() -> None:
    sources = [
        _item("s1", "official_blog", "Product X released today", minutes_ago=5),
        _item("s2", "news_a", "Product X release delayed", minutes_ago=8),
    ]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.research_status == ResearchStatus.CONFLICTED
    assert packet.conflicting_information is True
    assert len(packet.conflicts) >= 1
    assert any(c.status == ClaimStatus.CONFLICTED for c in packet.claims)


def test_fixture_d_numeric_mismatch() -> None:
    sources = [
        _item("s1", "official_blog", "Company reports revenue of 50 million dollars", minutes_ago=5),
        _item("s2", "news_a", "Company reports revenue of 80 million dollars", minutes_ago=8),
    ]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.research_status == ResearchStatus.CONFLICTED
    assert any(c.conflict_type == "numeric" for c in packet.conflicts)


def test_fixture_e_date_mismatch() -> None:
    sources = [
        _item("s1", "official_blog", "Event scheduled for March 1", minutes_ago=5),
        _item("s2", "news_a", "Event scheduled for March 15", minutes_ago=8),
    ]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.research_status == ResearchStatus.CONFLICTED
    assert any(c.conflict_type == "date" for c in packet.conflicts)


def test_fixture_f_unrelated_news_excluded() -> None:
    relevant = _item("s1", "official_blog", "AI lab confirms new model release today", minutes_ago=5)
    unrelated = _item("s2", "news_a", "Quarterly earnings beat analyst expectations", minutes_ago=6)
    packet = _brain().research(_trend([relevant], relevant.title), [relevant, unrelated], _ids())

    assert packet.sources == ["s1"]
    assert packet.independent_source_count == 1


def test_reliability_weighting_prefers_tier_a() -> None:
    sources = [_item("s1", "official_blog", "Official breaking announcement made today", minutes_ago=1)]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())
    assert packet.source_quality == 1.0  # tier_a reliability_score


def test_no_sources_returns_empty_packet_without_crash() -> None:
    trend = TrendCandidate(
        trend_id="trend-empty", trace_id="ECHO-AI-20260809-000009", topic="Nothing found",
        sources=["missing"], detected_at=NOW, velocity=0.5, novelty=1.0, relevance=1.0, vertical="ai",
    )
    packet = _brain().research(trend, [], _ids())

    assert packet.research_status == ResearchStatus.INSUFFICIENT_EVIDENCE
    assert packet.claims == []
    assert packet.evidence == []


def test_last_run_stats_populated() -> None:
    sources = [_item("s1", "official_blog", "Official breaking announcement made today", minutes_ago=1)]
    brain = _brain()
    brain.research(_trend(sources, sources[0].title), sources, _ids())

    assert brain.last_run is not None
    assert brain.last_run.sources_selected == 1
    assert brain.last_run.independent_source_count == 1


def test_traceability_evidence_resolves_to_original_source_item() -> None:
    sources = [_item("s1", "official_blog", "Official breaking announcement made today", minutes_ago=1)]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())

    assert packet.evidence[0].source_item_id == "s1"
    assert packet.evidence[0].url == str(sources[0].url)


@pytest.mark.parametrize("primary", [True, False])
def test_noncontributing_tier_a_cannot_boost_research(primary):
    weak = _item("weak", "news_b", "OrionModel released today with advanced features")
    empty = _item("empty", "empty_a", "OrionModel released")
    registry = dict(REGISTRY, empty_a=SourceRegistryInfo(
        name="Empty source", reliability_tier=ReliabilityTier.A, is_primary_source=primary,
    ))
    brain = RealResearchBrain(source_registry_info=registry, now=NOW)
    baseline = brain.research(_trend([weak], weak.title), [weak], _ids())
    packet = brain.research(_trend([weak, empty], weak.title), [weak, empty], _ids())
    assert packet.confidence == baseline.confidence
    assert packet.source_quality == baseline.source_quality
    assert packet.independent_source_count == baseline.independent_source_count == 1
    assert packet.primary_source_present is False
    assert packet.research_status != ResearchStatus.READY
    assert [c.status for c in packet.claims] == [ClaimStatus.UNVERIFIED]
    assert next(a for a in packet.source_assessments if a.source_key == "empty_a").evidence_count == 0
    assert set(packet.sources) == {"weak", "empty"}


@pytest.mark.parametrize("allow_single", [False, True])
def test_exclusively_unverified_research_cannot_be_ready(allow_single):
    registry = {
        key: SourceRegistryInfo(name=key, reliability_tier=ReliabilityTier.C, is_primary_source=False)
        for key in ("weak_a", "weak_b")
    }
    sources = [_item("a", "weak_a", "Company reports quarterly earnings growth")]
    if not allow_single:
        sources.append(_item("b", "weak_b", "Spacecraft completes orbital docking maneuver"))
    brain = RealResearchBrain(
        source_registry_info=registry, now=NOW,
        research_config=ResearchConfig(require_primary_source_for_single_source_claim=not allow_single),
    )
    packet = brain.research(_trend(sources, sources[0].title), sources, _ids())
    assert all(c.status == ClaimStatus.UNVERIFIED for c in packet.claims)
    assert packet.research_status == ResearchStatus.LOW_CONFIDENCE


def test_empty_evidence_has_zero_contributor_statistics():
    sources = [_item("short", "official_blog", "Updates")]
    packet = _brain().research(_trend(sources, "Updates"), sources, _ids())
    assert packet.evidence == []
    assert packet.independent_source_count == 0
    assert packet.source_quality == 0
    assert packet.primary_source_present is False
    assert packet.research_status == ResearchStatus.INSUFFICIENT_EVIDENCE


def test_repeated_contributing_source_is_counted_once():
    sources = [_item(f"s{i}", "official_blog", "Orion model is available for testing today") for i in range(3)]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())
    assert len(packet.evidence) == 3
    assert packet.independent_source_count == 1
    assert packet.research_status == ResearchStatus.READY


def test_identical_unavailable_statements_agree_end_to_end():
    sources = [_item("a", "official_blog", "The Orion model is unavailable today"),
               _item("b", "news_a", "The Orion model is unavailable today")]
    packet = _brain().research(_trend(sources, sources[0].title), sources, _ids())
    assert packet.conflicts == []
    assert packet.claims[0].status == ClaimStatus.CONFIRMED
    assert packet.research_status == ResearchStatus.READY
