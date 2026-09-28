"""Explainable deterministic Affiliate Opportunity Score v0."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from echo.models.affiliate import (
    AffiliateOpportunityScore,
    EvidenceStatus,
    EvidenceType,
    OpportunityScoreConfig,
    ProductCandidate,
    ScoreComponent,
    ScoreContribution,
)
from echo.monetization.evidence import (
    ValueInterpretation, evidence_is_current, find_conflicting_evidence, interpret_evidence_value,
)


# Values for these six components remain normalized assessments, never commercial predictions.
COMPONENT_EVIDENCE = {
    ScoreComponent.COMMERCIAL_ATTRACTIVENESS: frozenset({
        EvidenceType.PRICE, EvidenceType.DISCOUNT, EvidenceType.COUPON, EvidenceType.POINT_MULTIPLIER,
    }),
    ScoreComponent.URGENCY: frozenset({
        EvidenceType.SALE_END, EvidenceType.DISCOUNT, EvidenceType.COUPON, EvidenceType.POINT_MULTIPLIER,
    }),
    ScoreComponent.DEMAND: frozenset({EvidenceType.RANKING, EvidenceType.REVIEW_COUNT, EvidenceType.TREND_RELEVANCE}),
    ScoreComponent.TRUST: frozenset({EvidenceType.REVIEW_COUNT, EvidenceType.REVIEW_RATING}),
    ScoreComponent.AFFILIATE_ECONOMICS: frozenset({EvidenceType.AFFILIATE_RATE}),
    ScoreComponent.CONTEXTUAL_FIT: frozenset({EvidenceType.PRODUCT_IDENTITY, EvidenceType.SEASONALITY}),
}
CONFIDENCE_COMPONENTS = tuple(component for component in COMPONENT_EVIDENCE
                              if component != ScoreComponent.CONTEXTUAL_FIT)


def _support_reason(candidate, component, records, conflicted_records, as_of, max_age) -> str:
    """The entire feature is zeroed if even one cited row is ineligible."""
    if not records:
        return "missing_evidence"
    for record in records:
        if record is None:
            return "missing_evidence"
        if (record.evidence_type, record.evidence_id) in conflicted_records:
            return "conflicted_evidence"
        if record.evidence_type not in COMPONENT_EVIDENCE[component]:
            return "unsupported_component_evidence_type"
        if not evidence_is_current(record, as_of=as_of, max_age=max_age):
            return "ineligible_status_provenance_or_time"
        if record.evidence_type == EvidenceType.PRODUCT_IDENTITY:
            if record.value_text != candidate.name:
                return "identity_name_mismatch"
        else:
            interpretation, _ = interpret_evidence_value(record)
            if interpretation != ValueInterpretation.POSITIVE:
                return "unsupported_or_nonpositive_value"
        if record.evidence_type == EvidenceType.PRICE and (
            candidate.offer.price is None or record.evidence_id != candidate.offer.price.evidence_id
            or record.value_number != candidate.offer.price.amount
        ):
            return "offer_price_linkage_mismatch"
        if record.evidence_type == EvidenceType.AFFILIATE_RATE and (
            candidate.offer.affiliate_rate is None or record.value_number / Decimal("100") != candidate.offer.affiliate_rate
        ):
            return "offer_affiliate_rate_linkage_mismatch"
    return "eligible_normalized_component_assessment"


def score_candidate(candidate: ProductCandidate, config: OpportunityScoreConfig, *, as_of: datetime,
                    max_evidence_age: timedelta,
                    evidence_candidates: tuple[ProductCandidate, ...] = ()) -> AffiliateOpportunityScore:
    """Validate six assessments; derive confidence/freshness from their actual support.

    An invalid feature contributes zero, with a reason. Weights are never renormalized.
    Fixture facts may support offline assessments but never evidence confidence.
    Include known sibling offers in evidence_candidates for cross-offer conflicts;
    the scored candidate is always included, even if the supplied context omits it.
    """
    evidence = {item.evidence_id: item for item in candidate.evidence}
    features = {item.component: item for item in candidate.score_features}
    relevant_candidates = (candidate, *(item for item in evidence_candidates
        if item.product_id == candidate.product_id and item.service == candidate.service))
    conflicted_records = {(conflict.evidence_type, evidence_id) for conflict in find_conflicting_evidence(
        relevant_candidates, as_of=as_of, max_age=max_evidence_age)
                      for evidence_id in conflict.evidence_ids}
    supported = {}
    evaluated = {}
    weights = config.weight_by_component
    for component in COMPONENT_EVIDENCE:
        feature = features.get(component)
        value = Decimal("0")
        evidence_ids = tuple(sorted(feature.evidence_ids)) if feature is not None else ()
        records = tuple(evidence.get(evidence_id) for evidence_id in evidence_ids)
        reason = "missing_or_nonpositive_assessment"
        if feature is not None and feature.value is not None and feature.value > 0:
            reason = _support_reason(candidate, component, records, conflicted_records, as_of, max_evidence_age)
            if reason == "eligible_normalized_component_assessment":
                value = feature.value
                if weights[component] > 0:
                    supported[component] = records
        evaluated[component] = (value, evidence_ids, reason)

    verified_components = {
        component: supported[component] for component in CONFIDENCE_COMPONENTS
        if component in supported and all(record.status == EvidenceStatus.VERIFIED for record in supported[component])
    }
    confidence_ids = tuple(sorted({record.evidence_id for records in verified_components.values() for record in records}))
    confidence = Decimal(len(verified_components)) / Decimal(len(CONFIDENCE_COMPONENTS))
    evaluated[ScoreComponent.EVIDENCE_CONFIDENCE] = (
        confidence, confidence_ids,
        f"derived_verified_factual_component_coverage:{len(verified_components)}/{len(CONFIDENCE_COMPONENTS)}",
    )
    freshness_ids = tuple(sorted({record.evidence_id for records in supported.values() for record in records
                                  if record.evidence_type != EvidenceType.PRODUCT_IDENTITY}))
    freshness = Decimal("0")
    if freshness_ids:
        oldest_age = max(as_of - evidence[evidence_id].observed_at for evidence_id in freshness_ids)
        freshness = Decimal("1") - Decimal(str(oldest_age.total_seconds())) / Decimal(str(max_evidence_age.total_seconds()))
    evaluated[ScoreComponent.FRESHNESS] = (freshness, freshness_ids, "derived_oldest_contributing_nonidentity_evidence_age")

    contributions = []
    for component in ScoreComponent:
        value, evidence_ids, reason = evaluated[component]
        contributions.append(ScoreContribution(
            component=component, value=value, weight=weights[component], weighted_value=value * weights[component],
            evidence_ids=evidence_ids,
            evidence_types=tuple(sorted({evidence[evidence_id].evidence_type for evidence_id in evidence_ids
                                         if evidence_id in evidence}, key=lambda item: item.value)),
            validation_basis=reason,
        ))
    total = sum((item.weighted_value for item in contributions), Decimal("0"))
    return AffiliateOpportunityScore(
        product_id=candidate.product_id,
        formula_version=config.formula_version,
        final_score=total,
        components=tuple(contributions),
    )


def rank_candidates(candidates: tuple[ProductCandidate, ...],
                    scores: tuple[AffiliateOpportunityScore, ...]) -> tuple[ProductCandidate, ...]:
    score_by_id = {item.product_id: item.final_score for item in scores}
    if len(score_by_id) != len(scores) or set(score_by_id) != {item.product_id for item in candidates}:
        raise ValueError("each candidate must have exactly one score")
    return tuple(sorted(candidates, key=lambda item: (-score_by_id[item.product_id], item.product_id)))
