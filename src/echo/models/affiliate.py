"""Offline affiliate-domain models for Project Echo Zero.

These records describe candidates and provenance. They do not create affiliate
URLs, contact a marketplace, publish content, or grant execution authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import re
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AffiliateService(str, Enum):
    RAKUTEN_ICHIBA = "rakuten_ichiba"
    RAKUYOKO = "rakuyoko"


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    FIXTURE = "fixture"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"


class EvidenceType(str, Enum):
    PRODUCT_IDENTITY = "product_identity"
    PRICE = "price"
    PRODUCT_DESTINATION = "product_destination"
    AFFILIATE_DESTINATION = "affiliate_destination"
    DISCOUNT = "discount"
    SALE_END = "sale_end"
    COUPON = "coupon"
    POINT_MULTIPLIER = "point_multiplier"
    RANKING = "ranking"
    REVIEW_COUNT = "review_count"
    REVIEW_RATING = "review_rating"
    AFFILIATE_RATE = "affiliate_rate"
    AVAILABILITY = "availability"
    SEASONALITY = "seasonality"
    TREND_RELEVANCE = "trend_relevance"
    RIGHTS = "rights"
    OTHER = "other"


class DestinationStatus(str, Enum):
    NOT_CREATED = "not_created"
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class ScoreComponent(str, Enum):
    COMMERCIAL_ATTRACTIVENESS = "commercial_attractiveness"
    URGENCY = "urgency"
    DEMAND = "demand"
    TRUST = "trust"
    AFFILIATE_ECONOMICS = "affiliate_economics"
    CONTEXTUAL_FIT = "contextual_fit"
    EVIDENCE_CONFIDENCE = "evidence_confidence"
    FRESHNESS = "freshness"


class AffiliateModel(BaseModel):
    """Common immutable/strict settings for Phase 0 domain records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProductEvidence(AffiliateModel):
    evidence_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    service: AffiliateService
    evidence_type: EvidenceType
    source_name: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    source_field: str = Field(min_length=1)
    provider_item_id: str | None = None
    observed_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: EvidenceStatus = EvidenceStatus.UNKNOWN
    value_text: str | None = None
    value_number: Decimal | None = None
    value_boolean: bool | None = None

    @model_validator(mode="after")
    def _one_value_and_valid_window(self) -> Self:
        values = (self.value_text, self.value_number, self.value_boolean)
        if sum(value is not None for value in values) != 1:
            raise ValueError("exactly one evidence value must be supplied")
        if self.value_text is not None and not self.value_text.strip():
            raise ValueError("text evidence cannot be empty")
        if self.value_number is not None and not self.value_number.is_finite():
            raise ValueError("numeric evidence must be finite")
        if self.evidence_type == EvidenceType.PRICE and self.value_number is None:
            raise ValueError("price evidence requires a numeric value")
        if self.evidence_type == EvidenceType.SALE_END and self.valid_until is None:
            raise ValueError("sale-end evidence requires an explicit end time")
        if self.evidence_type in (EvidenceType.PRODUCT_DESTINATION, EvidenceType.AFFILIATE_DESTINATION):
            if not self.provider_item_id or self.value_text is None:
                raise ValueError("destination evidence must bind a URL to a provider item")
            parsed = urlparse(self.value_text)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("destination evidence URL must be an HTTPS URL without embedded credentials")
        elif self.provider_item_id is not None:
            raise ValueError("provider_item_id is reserved for item-destination evidence")
        if self.valid_from is not None and self.valid_until is not None:
            try:
                valid_window = self.valid_from < self.valid_until
            except TypeError:
                valid_window = False
            if not valid_window:
                raise ValueError("evidence validity window must end after it starts")
        return self


class ValueInterpretation(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    UNSUPPORTED = "unsupported"


POSITIVE_RANK_MAX = Decimal("10")
POSITIVE_REVIEW_MIN = Decimal("4")


BUY_NOW_EVIDENCE_TYPES = frozenset({
    EvidenceType.DISCOUNT, EvidenceType.SALE_END, EvidenceType.COUPON,
    EvidenceType.POINT_MULTIPLIER, EvidenceType.RANKING, EvidenceType.REVIEW_COUNT,
    EvidenceType.REVIEW_RATING, EvidenceType.AVAILABILITY, EvidenceType.SEASONALITY,
    EvidenceType.TREND_RELEVANCE,
})


def evidence_has_eligible_provenance(evidence: ProductEvidence) -> bool:
    return evidence.status in (EvidenceStatus.VERIFIED, EvidenceStatus.FIXTURE) and all(
        value.strip() for value in (
            evidence.evidence_id, evidence.product_id, evidence.source_name,
            evidence.source_reference, evidence.source_field,
        )
    )


def interpret_evidence_value(evidence: ProductEvidence) -> tuple[ValueInterpretation, str]:
    """Small typed v0 contract; arbitrary text is never positive buying evidence."""
    kind = evidence.evidence_type
    number, boolean = evidence.value_number, evidence.value_boolean
    text = evidence.value_text.strip().casefold() if evidence.value_text is not None else None
    if kind == EvidenceType.AVAILABILITY:
        if boolean is not None:
            return (ValueInterpretation.POSITIVE if boolean else ValueInterpretation.NEGATIVE,
                    "explicit_availability_boolean")
        if text in ("available", "in_stock"):
            return ValueInterpretation.POSITIVE, "explicit_in_stock_token"
        if text in ("unavailable", "out_of_stock"):
            return ValueInterpretation.NEGATIVE, "explicit_out_of_stock_token"
        if text in ("unknown", "neutral", "not_applicable"):
            return ValueInterpretation.NEUTRAL, "neutral_availability_token"
    elif kind == EvidenceType.COUPON:
        if text in ("none", "no_coupon", "not_applicable"):
            return ValueInterpretation.NEUTRAL, "no_usable_coupon"
        # A supported coupon also needs an explicit usage deadline; freshness is checked separately.
        if evidence.valid_until is not None:
            if number is not None:
                return _positive_magnitude(number, "coupon_discount_amount")
            if text is not None and re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)%", text):
                percent = Decimal(text[:-1])
                if 0 <= percent <= 100:
                    return _positive_magnitude(percent, "coupon_discount_percent")
    elif kind == EvidenceType.SALE_END:
        if evidence.value_text is not None and evidence.valid_until is not None:
            try:
                deadline = datetime.fromisoformat(evidence.value_text)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if deadline == evidence.valid_until:
                    return ValueInterpretation.POSITIVE, "exact_supported_sale_deadline"
            except ValueError:
                pass
    elif kind in (EvidenceType.SEASONALITY, EvidenceType.TREND_RELEVANCE):
        if boolean is not None:
            return (ValueInterpretation.POSITIVE if boolean else ValueInterpretation.NEGATIVE,
                    "explicit_relevance_boolean")
        if number is not None and -1 <= number <= 1:
            return _positive_magnitude(number, "normalized_relevance")
    elif number is not None:
        if kind == EvidenceType.POINT_MULTIPLIER and number >= 0:
            return _positive_magnitude(number - 1, "points_above_one_times_baseline")
        if kind == EvidenceType.RANKING and number == number.to_integral_value() and number >= 1:
            return (ValueInterpretation.POSITIVE if number <= POSITIVE_RANK_MAX else ValueInterpretation.NEUTRAL,
                    "top_ten_ranking")
        if kind == EvidenceType.REVIEW_RATING and 0 <= number <= 5:
            return (ValueInterpretation.POSITIVE if number >= POSITIVE_REVIEW_MIN else ValueInterpretation.NEUTRAL,
                    "review_rating_at_least_four_of_five")
        if kind == EvidenceType.REVIEW_COUNT and number == number.to_integral_value():
            return _positive_magnitude(number, "positive_review_count")
        if kind == EvidenceType.DISCOUNT and -100 <= number <= 100:
            return _positive_magnitude(number, "discount_percent")
        if kind == EvidenceType.AFFILIATE_RATE and 0 <= number <= 100:
            return _positive_magnitude(number, "affiliate_rate_percent")
        if kind == EvidenceType.PRICE:
            return _positive_magnitude(number, "observed_offer_price")
    return ValueInterpretation.UNSUPPORTED, "unsupported_type_value_pair"


def _positive_magnitude(number: Decimal, basis: str) -> tuple[ValueInterpretation, str]:
    return (ValueInterpretation.POSITIVE if number > 0 else
            ValueInterpretation.NEUTRAL if number == 0 else ValueInterpretation.NEGATIVE, basis)


class PriceQuote(AffiliateModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    evidence_id: str = Field(min_length=1)


class AffiliateDestination(AffiliateModel):
    """Per-item destination identity; URL creation is deliberately absent in Phase 0."""

    destination_id: str = Field(min_length=1)
    service: AffiliateService
    provider_item_id: str = Field(min_length=1)
    status: DestinationStatus = DestinationStatus.NOT_CREATED
    destination_url: str | None = None
    verification_evidence_id: str | None = None

    @model_validator(mode="after")
    def _verified_url_only(self) -> Self:
        if self.status == DestinationStatus.VERIFIED:
            if not self.destination_url or not self.verification_evidence_id:
                raise ValueError("verified destination requires a URL and item-bound evidence")
            parsed = urlparse(self.destination_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("verified destination URL must be HTTPS")
        elif self.destination_url is not None or self.verification_evidence_id is not None:
            raise ValueError("unverified Phase 0 destination cannot carry a URL or verification evidence")
        return self


class AffiliateOffer(AffiliateModel):
    offer_id: str = Field(min_length=1)
    service: AffiliateService
    provider_item_id: str = Field(min_length=1)
    product_destination: AffiliateDestination
    affiliate_destination: AffiliateDestination
    price: PriceQuote | None = None
    affiliate_rate: Decimal | None = Field(default=None, ge=0, le=1)
    available: bool | None = None

    @model_validator(mode="after")
    def _destination_identity_matches_offer(self) -> Self:
        for destination in (self.product_destination, self.affiliate_destination):
            if destination.service != self.service or destination.provider_item_id != self.provider_item_id:
                raise ValueError("each destination must identify this offer's service and item")
        return self


class ScoreFeature(AffiliateModel):
    component: ScoreComponent
    value: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _evidence_for_positive_value(self) -> Self:
        if self.value is None and self.evidence_ids:
            raise ValueError("an unknown feature cannot cite evidence")
        if self.value is not None and self.value > 0 and not self.evidence_ids:
            raise ValueError("positive score features require evidence")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("feature evidence IDs must be unique")
        return self


class ProductCandidate(AffiliateModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    service: AffiliateService
    provider_item_id: str = Field(min_length=1)
    offer: AffiliateOffer
    evidence: tuple[ProductEvidence, ...] = ()
    score_features: tuple[ScoreFeature, ...] = ()

    @model_validator(mode="after")
    def _validate_offer_and_provenance(self) -> Self:
        if self.offer.service != self.service or self.offer.provider_item_id != self.provider_item_id:
            raise ValueError("offer identity must match its product candidate")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("product evidence IDs must be unique")
        if any(item.product_id != self.product_id or item.service != self.service for item in self.evidence):
            raise ValueError("evidence must belong to this product and service")
        if self.offer.price is not None:
            price_evidence = evidence_by_id.get(self.offer.price.evidence_id)
            if price_evidence is None or price_evidence.evidence_type != EvidenceType.PRICE:
                raise ValueError("price quote must reference this product's price evidence")
            if price_evidence.value_number != self.offer.price.amount:
                raise ValueError("price quote must match its evidence value")
        for destination, evidence_type in (
            (self.offer.product_destination, EvidenceType.PRODUCT_DESTINATION),
            (self.offer.affiliate_destination, EvidenceType.AFFILIATE_DESTINATION),
        ):
            if destination.status != DestinationStatus.VERIFIED:
                continue
            destination_evidence = evidence_by_id.get(destination.verification_evidence_id)
            if (
                destination_evidence is None
                or destination_evidence.evidence_type != evidence_type
                or destination_evidence.service != self.service
                or destination_evidence.provider_item_id != self.provider_item_id
                or destination_evidence.value_text != destination.destination_url
            ):
                raise ValueError("verified destination must match this service/item's exact URL evidence")
        feature_components = [item.component for item in self.score_features]
        if len(set(feature_components)) != len(feature_components):
            raise ValueError("score feature components must be unique")
        return self


class ProductEvidenceConflict(AffiliateModel):
    product_id: str = Field(min_length=1)
    evidence_type: EvidenceType
    observed_at: datetime
    evidence_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _at_least_two_distinct_records(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("conflict evidence IDs must be distinct")
        return self


class BuyNowSignal(AffiliateModel):
    signal_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    evidence_type: EvidenceType
    evidence_status: EvidenceStatus
    observed_at: datetime
    expires_at: datetime
    supporting_evidence: ProductEvidence
    normalized_interpretation: Literal["positive"] = "positive"
    interpretation_basis: str = Field(min_length=1)
    live_action_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _retain_original_evidence(self) -> Self:
        evidence = self.supporting_evidence
        if (evidence.evidence_id != self.evidence_id or evidence.product_id != self.product_id
                or evidence.evidence_type != self.evidence_type or evidence.status != self.evidence_status
                or evidence.observed_at != self.observed_at):
            raise ValueError("signal provenance must match its original evidence")
        interpretation, basis = interpret_evidence_value(evidence)
        if (evidence.evidence_type not in BUY_NOW_EVIDENCE_TYPES
                or not evidence_has_eligible_provenance(evidence)
                or interpretation != ValueInterpretation.POSITIVE
                or self.interpretation_basis != basis):
            raise ValueError("positive BuyNow signals require eligible positive typed evidence")
        try:
            effective_start = evidence.valid_from if evidence.valid_from is not None else self.observed_at
            valid_expiry = self.expires_at > self.observed_at and self.expires_at > effective_start and (
                evidence.valid_until is None or self.expires_at <= evidence.valid_until
            )
        except TypeError:
            valid_expiry = False
        if not valid_expiry:
            raise ValueError("signal expiry must bound the original evidence validity")
        return self


class ScoreWeight(AffiliateModel):
    component: ScoreComponent
    weight: Decimal = Field(ge=0, le=1)


class OpportunityScoreConfig(AffiliateModel):
    formula_version: str = Field(min_length=1)
    weights: tuple[ScoreWeight, ...]

    @model_validator(mode="after")
    def _complete_normalized_weights(self) -> Self:
        components = [item.component for item in self.weights]
        if set(components) != set(ScoreComponent) or len(components) != len(ScoreComponent):
            raise ValueError("weights must define every Opportunity Score v0 component exactly once")
        if sum((item.weight for item in self.weights), Decimal("0")) != Decimal("1"):
            raise ValueError("score weights must sum exactly to 1")
        return self

    @property
    def weight_by_component(self) -> dict[ScoreComponent, Decimal]:
        """Return a fresh lookup so the frozen configuration stays immutable."""
        return {item.component: item.weight for item in self.weights}


class ScoreContribution(AffiliateModel):
    component: ScoreComponent
    value: Decimal = Field(ge=0, le=1)
    weight: Decimal = Field(ge=0, le=1)
    weighted_value: Decimal = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...] = ()
    evidence_types: tuple[EvidenceType, ...] = ()
    validation_basis: str = Field(min_length=1)


class AffiliateOpportunityScore(AffiliateModel):
    product_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    final_score: Decimal = Field(ge=0, le=1)
    components: tuple[ScoreContribution, ...]

    @model_validator(mode="after")
    def _complete_explanation(self) -> Self:
        components = [item.component for item in self.components]
        if set(components) != set(ScoreComponent) or len(components) != len(ScoreComponent):
            raise ValueError("score breakdown must explain every component exactly once")
        if sum((item.weighted_value for item in self.components), Decimal("0")) != self.final_score:
            raise ValueError("final score must equal the sum of weighted components")
        return self


class ProductSetItem(AffiliateModel):
    product_id: str = Field(min_length=1)
    slide_order: int = Field(ge=1)
    featured: bool = False


class ProductSet(AffiliateModel):
    product_set_id: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    shared_scene_id: str = Field(min_length=1)
    items: tuple[ProductSetItem, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _unique_products_and_order(self) -> Self:
        product_ids = [item.product_id for item in self.items]
        slide_orders = [item.slide_order for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("a product set cannot repeat a product")
        if len(set(slide_orders)) != len(slide_orders):
            raise ValueError("product set slide order must be unique")
        return self


def product_set_product_ids(product_set: ProductSet) -> tuple[str, ...]:
    """Return product IDs in deterministic carousel order."""
    return tuple(item.product_id for item in sorted(product_set.items, key=lambda item: item.slide_order))
