from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from echo.models.draft import ContentDraft
from echo.models.enums import ContentType, DecisionType, RejectReason
from echo.models.performance import PerformanceSnapshot
from echo.models.review import ReviewDecision
from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate

NOW = datetime.now(timezone.utc)


def _draft(**overrides) -> ContentDraft:
    fields = dict(
        draft_id="draft-1",
        trend_id="trend-1",
        trace_id="ECHO-AI-20260809-000001",
        content_type=ContentType.EXPLAIN,
        hook="hook",
        body="body",
        sources=["src-1"],
        confidence=0.5,
        generated_at=NOW,
        vertical="ai",
    )
    fields.update(overrides)
    return ContentDraft(**fields)


def test_source_item_valid() -> None:
    item = SourceItem(
        source_id="src-1",
        url="https://example.com/a",
        source_name="Example",
        title="Title",
        published_at=NOW,
        retrieved_at=NOW,
        content="body",
        language="en",
        vertical="ai",
    )
    assert item.source_id == "src-1"
    assert str(item.url).startswith("https://example.com")


def test_source_item_rejects_invalid_url() -> None:
    with pytest.raises(ValidationError):
        SourceItem(
            source_id="src-1",
            url="not-a-url",
            source_name="Example",
            title="Title",
            published_at=NOW,
            retrieved_at=NOW,
            vertical="ai",
        )


def test_trend_candidate_score_bounds() -> None:
    with pytest.raises(ValidationError):
        TrendCandidate(
            trend_id="trend-1",
            trace_id="ECHO-AI-20260809-000001",
            topic="topic",
            detected_at=NOW,
            velocity=1.5,  # out of [0, 1]
            novelty=0.5,
            relevance=0.5,
            vertical="ai",
        )


def test_content_draft_compliance_defaults() -> None:
    draft = _draft()
    assert draft.compliance_risk_score == 0.0
    assert draft.compliance_flags == []


def test_review_decision_reject_requires_reason() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            review_id="review-1",
            draft_id="draft-1",
            trace_id="ECHO-AI-20260809-000001",
            decision=DecisionType.REJECT,
            reviewed_at=NOW,
        )


def test_review_decision_reject_with_reason_ok() -> None:
    review = ReviewDecision(
        review_id="review-1",
        draft_id="draft-1",
        trace_id="ECHO-AI-20260809-000001",
        decision=DecisionType.REJECT,
        review_reason=RejectReason.LOW_VALUE,
        reviewed_at=NOW,
    )
    assert review.review_reason == RejectReason.LOW_VALUE


def test_review_decision_approve_without_reason_ok() -> None:
    review = ReviewDecision(
        review_id="review-1",
        draft_id="draft-1",
        trace_id="ECHO-AI-20260809-000001",
        decision=DecisionType.APPROVE,
        reviewed_at=NOW,
    )
    assert review.review_reason is None


def test_performance_snapshot_rejects_negative_metrics() -> None:
    with pytest.raises(ValidationError):
        PerformanceSnapshot(
            snapshot_id="snap-1",
            post_id="post-1",
            trace_id="ECHO-AI-20260809-000001",
            captured_at=NOW,
            impressions=-1,
        )
