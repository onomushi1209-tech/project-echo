from __future__ import annotations

from echo.models.enums import ClaimStatus, ConflictSeverity
from echo.models.research import ConflictRecord, ResearchClaim
from echo.research.config import ResearchConfig
from echo.research.confidence import claim_confidence, packet_confidence

CONFIG = ResearchConfig()


def _claim(status: ClaimStatus, confidence: float = 0.5) -> ResearchClaim:
    return ResearchClaim(
        claim_id=f"claim-{status.value}",
        text="Text",
        normalized_text="text",
        evidence_ids=["e1"],
        supporting_source_ids=["s1"],
        contradicting_source_ids=[],
        confidence=confidence,
        status=status,
    )


def _conflict(severity: ConflictSeverity) -> ConflictRecord:
    return ConflictRecord(
        conflict_id=f"conflict-{severity.value}",
        claim_id=None,
        evidence_id_a="e1",
        evidence_id_b="e2",
        source_key_a="s1",
        source_key_b="s2",
        conflict_type="numeric",
        reason="differing numbers",
        severity=severity,
    )


def test_claim_confidence_zero_with_no_reliabilities() -> None:
    assert claim_confidence([], independent_count=0, primary_present=False, has_conflict=False, config=CONFIG) == 0.0


def test_claim_confidence_rewards_primary_and_independence() -> None:
    low = claim_confidence([0.4], independent_count=1, primary_present=False, has_conflict=False, config=CONFIG)
    high = claim_confidence([1.0, 0.7], independent_count=2, primary_present=True, has_conflict=False, config=CONFIG)
    assert high > low


def test_claim_confidence_conflict_penalty_lowers_score() -> None:
    without_conflict = claim_confidence([1.0], independent_count=1, primary_present=True, has_conflict=False, config=CONFIG)
    with_conflict = claim_confidence([1.0], independent_count=1, primary_present=True, has_conflict=True, config=CONFIG)
    assert with_conflict < without_conflict


def test_claim_confidence_is_clamped_to_unit_range() -> None:
    score = claim_confidence([1.0, 1.0, 1.0], independent_count=10, primary_present=True, has_conflict=False, config=CONFIG)
    assert 0.0 <= score <= 1.0


def test_packet_confidence_high_case() -> None:
    claims = [_claim(ClaimStatus.CONFIRMED), _claim(ClaimStatus.CONFIRMED)]
    score = packet_confidence(
        primary_source_present=True,
        tier_a_source_present=True,
        independent_source_count=3,
        claims=claims,
        conflicts=[],
        evidence_count=5,
        config=CONFIG,
    )
    assert score > 0.8


def test_packet_confidence_low_case() -> None:
    claims = [_claim(ClaimStatus.UNVERIFIED)]
    score = packet_confidence(
        primary_source_present=False,
        tier_a_source_present=False,
        independent_source_count=1,
        claims=claims,
        conflicts=[],
        evidence_count=1,
        config=CONFIG,
    )
    assert score < 0.5


def test_packet_confidence_conflict_penalty() -> None:
    claims = [_claim(ClaimStatus.CONFLICTED)]
    base_kwargs = dict(
        primary_source_present=True,
        tier_a_source_present=True,
        independent_source_count=2,
        claims=claims,
        evidence_count=3,
        config=CONFIG,
    )
    without_conflict = packet_confidence(conflicts=[], **base_kwargs)
    with_major_conflict = packet_confidence(conflicts=[_conflict(ConflictSeverity.MAJOR)], **base_kwargs)
    with_potential_conflict = packet_confidence(conflicts=[_conflict(ConflictSeverity.POTENTIAL)], **base_kwargs)

    assert with_major_conflict < without_conflict
    assert with_potential_conflict < without_conflict
    assert with_major_conflict < with_potential_conflict  # major penalized more than potential


def test_packet_confidence_is_clamped_to_unit_range() -> None:
    claims = [_claim(ClaimStatus.CONFIRMED) for _ in range(5)]
    score = packet_confidence(
        primary_source_present=True,
        tier_a_source_present=True,
        independent_source_count=20,
        claims=claims,
        conflicts=[],
        evidence_count=20,
        config=CONFIG,
    )
    assert 0.0 <= score <= 1.0


def test_packet_confidence_empty_claims_does_not_crash() -> None:
    score = packet_confidence(
        primary_source_present=False,
        tier_a_source_present=False,
        independent_source_count=0,
        claims=[],
        conflicts=[],
        evidence_count=0,
        config=CONFIG,
    )
    assert 0.0 <= score <= 1.0
