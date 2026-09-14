from __future__ import annotations

from echo.models.enums import ConflictSeverity, ResearchStatus
from echo.models.research import ConflictRecord
from echo.research.config import ResearchConfig
from echo.research.status import determine_research_status

CONFIG = ResearchConfig()  # minimum_evidence_items=1, minimum_independent_sources=2, minimum_confidence=0.4


def _conflict(severity: ConflictSeverity) -> ConflictRecord:
    return ConflictRecord(
        conflict_id="c1", claim_id=None, evidence_id_a="e1", evidence_id_b="e2",
        source_key_a="s1", source_key_b="s2", conflict_type="numeric", reason="x", severity=severity,
    )


def test_insufficient_evidence_when_no_evidence() -> None:
    status = determine_research_status(
        evidence_count=0, independent_source_count=0, primary_source_present=False,
        confidence=0.5, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.INSUFFICIENT_EVIDENCE


def test_conflicted_when_a_confirmed_conflict_exists() -> None:
    status = determine_research_status(
        evidence_count=3, independent_source_count=2, primary_source_present=True,
        confidence=0.9, conflicts=[_conflict(ConflictSeverity.MAJOR)], config=CONFIG,
    )
    assert status == ResearchStatus.CONFLICTED


def test_potential_conflict_alone_does_not_force_conflicted() -> None:
    status = determine_research_status(
        evidence_count=3, independent_source_count=2, primary_source_present=True,
        confidence=0.9, conflicts=[_conflict(ConflictSeverity.POTENTIAL)], config=CONFIG,
    )
    assert status != ResearchStatus.CONFLICTED


def test_needs_more_sources_below_minimum_without_primary() -> None:
    status = determine_research_status(
        evidence_count=1, independent_source_count=1, primary_source_present=False,
        confidence=0.9, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.NEEDS_MORE_SOURCES


def test_single_primary_source_bypasses_needs_more_sources() -> None:
    """The explicit requirement: a lone official primary source must not be
    auto-rejected -- see docs/RESEARCH_INTELLIGENCE.md 'Minimum evidence
    rules'."""
    status = determine_research_status(
        evidence_count=1, independent_source_count=1, primary_source_present=True,
        confidence=0.9, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.READY


def test_low_confidence_when_below_threshold() -> None:
    status = determine_research_status(
        evidence_count=3, independent_source_count=2, primary_source_present=True,
        confidence=0.1, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.LOW_CONFIDENCE


def test_ready_when_all_thresholds_met() -> None:
    status = determine_research_status(
        evidence_count=3, independent_source_count=2, primary_source_present=True,
        confidence=0.9, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.READY


def test_multiple_independent_sources_without_primary_can_be_ready() -> None:
    status = determine_research_status(
        evidence_count=3, independent_source_count=3, primary_source_present=False,
        confidence=0.9, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.READY


def test_evidence_floor_checked_before_everything_else() -> None:
    status = determine_research_status(
        evidence_count=0, independent_source_count=5, primary_source_present=True,
        confidence=0.99, conflicts=[], config=CONFIG,
    )
    assert status == ResearchStatus.INSUFFICIENT_EVIDENCE


def test_require_primary_source_flag_disabled_allows_any_single_source() -> None:
    lenient_config = ResearchConfig(require_primary_source_for_single_source_claim=False)
    status = determine_research_status(
        evidence_count=1, independent_source_count=1, primary_source_present=False,
        confidence=0.9, conflicts=[], config=lenient_config,
    )
    assert status == ResearchStatus.READY
