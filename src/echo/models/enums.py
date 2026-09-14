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


class SourceType(str, Enum):
    """How a registered source is fetched. Extensible: adding a new fetch
    mechanism (HTML, API, X, ...) means adding a member here plus one
    adapter function in echo.source.adapters -- never a Core change."""

    RSS = "rss"
    ATOM = "atom"
    JSON = "json"
    STATIC_FIXTURE = "static_fixture"


class ReliabilityTier(str, Enum):
    """Config-driven source trust tier. Never tied to a specific company
    name in code -- see config/sources/*.yaml for which source gets which
    tier."""

    A = "tier_a"  # official / primary source
    B = "tier_b"  # high-quality secondary source
    C = "tier_c"  # discovery-only source


class FetchStatus(str, Enum):
    """Outcome of one source_fetch_runs row."""

    SUCCESS = "success"
    FAILED = "failed"


# -- STEP 3: Research Intelligence -------------------------------------------


class ClaimStatus(str, Enum):
    """How well-supported a ResearchClaim is, given its evidence.

    Informational only -- see docs/RESEARCH_INTELLIGENCE.md "Claim status
    ladder" for the exact deterministic rule that assigns each value.
    """

    CONFIRMED = "confirmed"  # >=2 independent sources agree, one tier_a/primary, no conflict
    SUPPORTED = "supported"  # >=2 independent sources agree, none tier_a/primary, no conflict
    SINGLE_SOURCE = "single_source"  # exactly 1 independent source, primary or tier_a/b
    UNVERIFIED = "unverified"  # exactly 1 independent source, non-primary tier_c
    CONFLICTED = "conflicted"  # a conflict was detected among this claim's evidence


class ConflictSeverity(str, Enum):
    """How seriously a detected ConflictRecord should be weighed.

    ``POTENTIAL`` is for heuristics that flagged a plausible but ambiguous
    mismatch (see docs/RESEARCH_INTELLIGENCE.md "Conflict detection") --
    STEP 3 heuristics deliberately under-claim rather than over-claim a
    confirmed contradiction.
    """

    POTENTIAL = "potential"
    MINOR = "minor"
    MAJOR = "major"


class ResearchStatus(str, Enum):
    """The state of a ResearchPacket's research process -- not a
    publish/reject decision. COMPLIANCE and the Human Review Gate keep
    that responsibility; this is purely informational (see
    docs/DEVELOPMENT_RULES.md)."""

    READY = "ready"
    NEEDS_MORE_SOURCES = "needs_more_sources"
    CONFLICTED = "conflicted"
    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
