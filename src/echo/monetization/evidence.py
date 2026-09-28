"""Source-neutral checks over immutable affiliate product evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from echo.models.affiliate import (
    EvidenceStatus,
    EvidenceType,
    ValueInterpretation,
    evidence_has_eligible_provenance,
    interpret_evidence_value,
    ProductCandidate,
    ProductEvidence,
    ProductEvidenceConflict,
)


def evidence_is_current(evidence: ProductEvidence, *, as_of: datetime, max_age: timedelta) -> bool:
    """Require explicit provenance/status and a comparable current validity window."""
    if not evidence_has_eligible_provenance(evidence):
        return False
    try:
        return max_age > timedelta(0) and evidence.observed_at <= as_of \
            and as_of - evidence.observed_at < max_age \
            and (evidence.valid_from is None or evidence.valid_from <= as_of) \
            and (evidence.valid_until is None or evidence.valid_until > as_of)
    except TypeError:
        return False


def _normalized_value(item: ProductEvidence) -> tuple:
    """Use only the domain's typed/token normalization; retain the source record."""
    if item.value_number is not None:
        return ("number", item.value_number)
    if item.value_boolean is not None:
        return ("boolean", item.value_boolean)
    text = item.value_text
    token = text.strip().casefold()
    if item.evidence_type == EvidenceType.AVAILABILITY:
        if token in ("available", "in_stock"):
            return ("boolean", True)
        if token in ("unavailable", "out_of_stock"):
            return ("boolean", False)
    if item.evidence_type == EvidenceType.COUPON:
        interpretation, basis = interpret_evidence_value(item)
        if basis == "coupon_discount_percent" and interpretation != ValueInterpretation.UNSUPPORTED:
            return ("coupon_percent", Decimal(token[:-1]))
        if token in ("none", "no_coupon", "not_applicable"):
            return ("coupon_absent",)
    if item.evidence_type == EvidenceType.SALE_END:
        try:
            deadline = datetime.fromisoformat(text)
            return ("deadline", deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    return ("text", text)


def _applicability_window(item: ProductEvidence, max_age: timedelta | None) -> tuple:
    start = item.valid_from if item.valid_from is not None else item.observed_at
    end = item.valid_until
    if max_age is not None:
        freshness_end = item.observed_at + max_age
        end = min(end, freshness_end) if end is not None else freshness_end
    return start, end


def _windows_overlap(left: tuple, right: tuple) -> bool:
    """Inclusive starts, exclusive ends; touching intervals do not overlap."""
    left_start, left_end = left
    right_start, right_end = right
    try:
        return (left_end is None or left_start < left_end) \
            and (right_end is None or right_start < right_end) \
            and (right_end is None or left_start < right_end) \
            and (left_end is None or right_start < left_end)
    except TypeError:
        return False


def find_conflicting_evidence(
    candidates: tuple[ProductCandidate, ...], *, as_of: datetime | None = None,
    max_age: timedelta | dict[EvidenceType, timedelta] | None = None,
) -> tuple[ProductEvidenceConflict, ...]:
    """Detect incompatible overlapping facts for one product/service/family.

    Runtime callers supply as_of and their freshness policy, so historical or
    future facts cannot poison current support. Without as_of this is a structural
    history audit using declared windows (an omitted end has no declared ceiling).
    """
    if as_of is not None and max_age is None:
        raise ValueError("current conflict evaluation requires a freshness policy")
    grouped = defaultdict(list)
    for candidate in candidates:
        for item in candidate.evidence:
            if item.status in (EvidenceStatus.VERIFIED, EvidenceStatus.FIXTURE):
                age = max_age.get(item.evidence_type, timedelta(0)) if isinstance(max_age, dict) else max_age
                if as_of is not None and not evidence_is_current(item, as_of=as_of, max_age=age):
                    continue
                key = (item.product_id, item.service, item.evidence_type)
                grouped[key].append((item, _applicability_window(item, age)))
    conflicts = []
    for (product_id, service, evidence_type), records in grouped.items():
        by_id = {}
        for item, window in records:
            if item.evidence_id in by_id and by_id[item.evidence_id][0] != item:
                raise ValueError("one evidence ID cannot identify different records for the same product/service")
            by_id[item.evidence_id] = (item, window)
        records = sorted(by_id.values(), key=lambda row: row[0].evidence_id)
        conflicting_ids = set()
        for index, (left, left_window) in enumerate(records):
            for right, right_window in records[index + 1:]:
                if _normalized_value(left) != _normalized_value(right) and _windows_overlap(left_window, right_window):
                    conflicting_ids.update((left.evidence_id, right.evidence_id))
        if conflicting_ids:
            anchor = min((item for item, _ in records if item.evidence_id in conflicting_ids),
                         key=lambda item: (item.observed_at.isoformat(), item.evidence_id))
            conflicts.append(ProductEvidenceConflict(
                product_id=product_id,
                evidence_type=evidence_type,
                observed_at=anchor.observed_at,
                evidence_ids=tuple(sorted(conflicting_ids)),
            ))
    return tuple(sorted(conflicts, key=lambda item: (item.product_id, item.evidence_type.value,
                                                     item.observed_at.isoformat(), item.evidence_ids)))
