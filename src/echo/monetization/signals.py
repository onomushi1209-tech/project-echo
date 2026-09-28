"""Evidence-backed BuyNowSignal derivation; absent/stale facts stay absent."""

from __future__ import annotations

from datetime import datetime, timedelta

from echo.models.affiliate import BuyNowSignal, EvidenceType, ProductCandidate
from echo.monetization.config import SIGNAL_EVIDENCE_TYPES
from echo.monetization.evidence import (
    ValueInterpretation, evidence_is_current, find_conflicting_evidence, interpret_evidence_value,
)


def derive_buy_now_signals(candidate: ProductCandidate, *, as_of: datetime,
                           max_age_by_type: dict[EvidenceType, int]) -> tuple[BuyNowSignal, ...]:
    signals = []
    conflicted_ids = {
        evidence_id
        for conflict in find_conflicting_evidence((candidate,), as_of=as_of,
            max_age={kind: timedelta(hours=hours) for kind, hours in max_age_by_type.items()})
        for evidence_id in conflict.evidence_ids
    }
    for evidence in candidate.evidence:
        if evidence.evidence_id in conflicted_ids:
            continue
        if evidence.evidence_type not in SIGNAL_EVIDENCE_TYPES or evidence.evidence_type not in max_age_by_type:
            continue
        if not evidence_is_current(evidence, as_of=as_of,
                                   max_age=timedelta(hours=max_age_by_type[evidence.evidence_type])):
            continue
        interpretation, basis = interpret_evidence_value(evidence)
        if interpretation != ValueInterpretation.POSITIVE:
            continue
        freshness_expiry = evidence.observed_at + timedelta(
            hours=max_age_by_type[evidence.evidence_type]
        )
        expires_at = min(evidence.valid_until, freshness_expiry) if evidence.valid_until else freshness_expiry
        signals.append(BuyNowSignal(
            signal_id=f"buy-now:{candidate.product_id}:{evidence.evidence_id}",
            product_id=candidate.product_id,
            evidence_id=evidence.evidence_id,
            evidence_type=evidence.evidence_type,
            evidence_status=evidence.status,
            observed_at=evidence.observed_at,
            expires_at=expires_at,
            supporting_evidence=evidence,
            interpretation_basis=basis,
            live_action_authorized=False,
        ))
    return tuple(sorted(signals, key=lambda item: (item.evidence_type.value, item.evidence_id)))
