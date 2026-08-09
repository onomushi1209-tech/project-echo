"""Core taxonomy enums shared across all verticals.

These enums describe system-level concepts (pipeline stages, content
classification, review outcomes). They must never contain vertical-specific
values (e.g. AI-only topics) -- vertical-specific data belongs in
``config/verticals/*.yaml`` and is loaded through ``echo.verticals``.
"""

from __future__ import annotations

from enum import Enum


class PipelineStage(str, Enum):
    """Stages of the Echo content pipeline, in execution order."""

    DISCOVER = "discover"
    RESEARCH = "research"
    SCORE = "score"
    CREATE = "create"
    COMPLIANCE = "compliance"
    HUMAN_REVIEW = "human_review"


class ContentType(str, Enum):
    """Generic content classification, independent of vertical."""

    BREAKING = "breaking"
    EXPLAIN = "explain"
    SIGNAL = "signal"
    EVERGREEN = "evergreen"


class DecisionType(str, Enum):
    """Outcome of the Human Review Gate."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    SKIP = "skip"


class RejectReason(str, Enum):
    """Reasons a draft was not approved for publishing."""

    LOW_SOURCE_CONFIDENCE = "low_source_confidence"
    DUPLICATE_TOPIC = "duplicate_topic"
    TOO_LATE = "too_late"
    LOW_RELEVANCE = "low_relevance"
    LOW_VALUE = "low_value"
    HIGH_COMPLIANCE_RISK = "high_compliance_risk"
    CLICKBAIT_ONLY = "clickbait_only"
    NO_NEW_INFORMATION = "no_new_information"
    OTHER = "other"
