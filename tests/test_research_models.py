from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from echo.models.enums import ClaimStatus, ConflictSeverity, ReliabilityTier, ResearchStatus
from echo.models.research import ConflictRecord, EvidenceItem, ResearchClaim, ResearchPacket, SourceAssessment

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_step1_style_research_packet_still_validates() -> None:
    """Backward compatibility: a packet built the STEP 1 way (no STEP 3
    fields, e.g. DummyResearchBrain) must still construct successfully."""
    packet = ResearchPacket(
        research_id="research-1",
        trend_id="trend-1",
        trace_id="ECHO-AI-20260809-000001",
        summary="Stub summary",
        key_facts=["fact one"],
        sources=["s1"],
        source_quality=0.6,
        conflicting_information=False,
        confidence=0.6,
    )
    assert packet.claims == []
    assert packet.evidence == []
    assert packet.conflicts == []
    assert packet.source_assessments == []
    assert packet.primary_source_present is False
    assert packet.independent_source_count == 0
    assert packet.research_status == ResearchStatus.READY
    assert packet.researched_at is None


def test_research_packet_accepts_full_step3_fields() -> None:
    evidence = EvidenceItem(
        evidence_id="evidence-1", source_item_id="s1", source_key="official_blog",
        url="https://example.com/a", title="Title", published_at=NOW, excerpt="An excerpt.",
        is_primary_source=True, reliability_tier=ReliabilityTier.A,
    )
    claim = ResearchClaim(
        claim_id="claim-1", text="Text", normalized_text="text", evidence_ids=["evidence-1"],
        supporting_source_ids=["official_blog"], contradicting_source_ids=[], confidence=0.9,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    conflict = ConflictRecord(
        conflict_id="conflict-1", claim_id="claim-1", evidence_id_a="evidence-1", evidence_id_b="evidence-2",
        source_key_a="official_blog", source_key_b="news_a", conflict_type="numeric", reason="x",
        severity=ConflictSeverity.MINOR,
    )
    assessment = SourceAssessment(
        source_key="official_blog", source_name="Official Blog", reliability_tier=ReliabilityTier.A,
        reliability_score=1.0, is_primary_source=True, item_count=1, evidence_count=1,
    )
    packet = ResearchPacket(
        research_id="research-1", trend_id="trend-1", trace_id="ECHO-AI-20260809-000001",
        summary="Summary", sources=["s1"], source_quality=1.0, confidence=0.9,
        claims=[claim], evidence=[evidence], conflicts=[conflict], source_assessments=[assessment],
        primary_source_present=True, independent_source_count=1,
        research_status=ResearchStatus.READY, researched_at=NOW,
    )
    assert packet.claims[0].status == ClaimStatus.SINGLE_SOURCE
    assert packet.evidence[0].reliability_tier == ReliabilityTier.A
    assert packet.conflicts[0].severity == ConflictSeverity.MINOR


def test_evidence_confidence_and_score_fields_are_bounded() -> None:
    with pytest.raises(ValidationError):
        ResearchClaim(
            claim_id="c1", text="t", normalized_text="t", confidence=1.5, status=ClaimStatus.CONFIRMED
        )


def test_research_packet_independent_source_count_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        ResearchPacket(
            research_id="r1", trend_id="t1", trace_id="ECHO-AI-20260809-000001", summary="s",
            source_quality=0.5, confidence=0.5, independent_source_count=-1,
        )


def test_claim_status_enum_values() -> None:
    assert {s.value for s in ClaimStatus} == {
        "confirmed", "supported", "single_source", "unverified", "conflicted"
    }


def test_conflict_severity_enum_values() -> None:
    assert {s.value for s in ConflictSeverity} == {"potential", "minor", "major"}


def test_research_status_enum_values() -> None:
    assert {s.value for s in ResearchStatus} == {
        "ready", "needs_more_sources", "conflicted", "low_confidence", "insufficient_evidence"
    }
