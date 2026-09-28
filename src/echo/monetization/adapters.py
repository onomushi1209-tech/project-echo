"""Provider boundaries for offline Phase 0 normalization.

There are no HTTP clients here. Rakuten fixtures mirror documented item-search
fields; Rakuyoko remains explicitly unverified wherever no official integration
contract was found.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from echo.models.affiliate import (
    AffiliateDestination,
    AffiliateOffer,
    AffiliateService,
    DestinationStatus,
    EvidenceStatus,
    EvidenceType,
    PriceQuote,
    ProductCandidate,
    ProductEvidence,
)


class CapabilityStatus(str, Enum):
    VERIFIED = "verified"
    UNKNOWN = "unknown"


class RakuyokoCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str = Field(min_length=1)
    status: CapabilityStatus
    evidence_reference: str = Field(min_length=1)
    note: str = Field(min_length=1)


class UnknownCapabilityError(ValueError):
    """Raised when an unverified external capability would be assumed."""


class RakutenItemSearchFixture(BaseModel):
    """Small fixture shape based on documented Rakuten item-search fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    item_code: str = Field(alias="itemCode", min_length=1)
    item_name: str = Field(alias="itemName", min_length=1)
    item_price: int | None = Field(default=None, alias="itemPrice", ge=1)
    item_url: str | None = Field(default=None, alias="itemUrl")
    availability: int | None = Field(default=None, ge=0, le=1)
    review_count: int | None = Field(default=None, alias="reviewCount", ge=0)
    review_average: Decimal | None = Field(default=None, alias="reviewAverage", ge=0, le=5)
    affiliate_rate: Decimal | None = Field(default=None, alias="affiliateRate", ge=0, le=100)
    point_rate: int | None = Field(default=None, alias="pointRate", ge=1)
    point_rate_start_time: str | None = Field(default=None, alias="pointRateStartTime")
    point_rate_end_time: str | None = Field(default=None, alias="pointRateEndTime")
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")


class RakutenFixtureAdapter:
    """Normalize a static, synthetic item-search record without creating a link."""

    service = AffiliateService.RAKUTEN_ICHIBA

    def normalize(self, payload: RakutenItemSearchFixture | dict, *, observed_at: datetime,
                  category: str) -> ProductCandidate:
        item = payload if isinstance(payload, RakutenItemSearchFixture) else RakutenItemSearchFixture.model_validate(payload)
        product_id = f"rakuten-{_stable_id(item.item_code)}"
        source_ref = item.item_url or f"offline-fixture:rakuten:{item.item_code}"
        evidence: list[ProductEvidence] = [ProductEvidence(
            evidence_id=f"{product_id}:identity", product_id=product_id, service=self.service,
            evidence_type=EvidenceType.PRODUCT_IDENTITY, source_name="Rakuten Ichiba Item Search fixture",
            source_reference=source_ref, source_field="itemName", observed_at=observed_at,
            status=EvidenceStatus.FIXTURE, value_text=item.item_name,
        )]
        price: PriceQuote | None = None
        if item.item_price is not None:
            evidence.append(ProductEvidence(
                evidence_id=f"{product_id}:price", product_id=product_id, service=self.service,
                evidence_type=EvidenceType.PRICE, source_name="Rakuten Ichiba Item Search fixture",
                source_reference=source_ref, source_field="itemPrice", observed_at=observed_at,
                status=EvidenceStatus.FIXTURE, value_number=Decimal(item.item_price),
            ))
            price = PriceQuote(amount=Decimal(item.item_price), currency="JPY", evidence_id=f"{product_id}:price")
        if item.availability is not None:
            evidence.append(_fixture_evidence(product_id, self.service, source_ref, "availability",
                                              EvidenceType.AVAILABILITY, observed_at,
                                              value_boolean=item.availability == 1))
        if item.review_count is not None:
            evidence.append(_fixture_evidence(product_id, self.service, source_ref, "reviewCount",
                                              EvidenceType.REVIEW_COUNT, observed_at,
                                              value_number=Decimal(item.review_count)))
        if item.review_average is not None:
            evidence.append(_fixture_evidence(product_id, self.service, source_ref, "reviewAverage",
                                              EvidenceType.REVIEW_RATING, observed_at,
                                              value_number=item.review_average))
        if item.affiliate_rate is not None:
            evidence.append(_fixture_evidence(product_id, self.service, source_ref, "affiliateRate",
                                              EvidenceType.AFFILIATE_RATE, observed_at,
                                              value_number=item.affiliate_rate))
        if item.end_time:
            end_time = _parse_api_time(item.end_time)
            evidence.append(ProductEvidence(
                evidence_id=f"{product_id}:sale_end", product_id=product_id, service=self.service,
                evidence_type=EvidenceType.SALE_END, source_name="Rakuten Ichiba Item Search fixture",
                source_reference=source_ref, source_field="endTime", observed_at=observed_at,
                valid_from=_parse_api_time(item.start_time) if item.start_time else None,
                valid_until=end_time, status=EvidenceStatus.FIXTURE, value_text=item.end_time,
            ))
        if item.point_rate is not None:
            evidence.append(ProductEvidence(
                evidence_id=f"{product_id}:pointRate", product_id=product_id, service=self.service,
                evidence_type=EvidenceType.POINT_MULTIPLIER,
                source_name="Rakuten Ichiba Item Search fixture", source_reference=source_ref,
                source_field="pointRate", observed_at=observed_at,
                valid_from=(_parse_api_time(item.point_rate_start_time)
                            if item.point_rate_start_time else None),
                valid_until=(_parse_api_time(item.point_rate_end_time)
                             if item.point_rate_end_time else None),
                status=EvidenceStatus.FIXTURE, value_number=Decimal(item.point_rate),
            ))
        offer = AffiliateOffer(
            offer_id=f"{product_id}:offer", service=self.service, provider_item_id=item.item_code,
            product_destination=AffiliateDestination(
                destination_id=f"{product_id}:product-destination", service=self.service,
                provider_item_id=item.item_code, status=DestinationStatus.UNVERIFIED,
            ),
            affiliate_destination=AffiliateDestination(
                destination_id=f"{product_id}:affiliate-destination", service=self.service,
                provider_item_id=item.item_code, status=DestinationStatus.NOT_CREATED,
            ),
            price=price,
            affiliate_rate=(item.affiliate_rate / Decimal(100)) if item.affiliate_rate is not None else None,
            available=(item.availability == 1) if item.availability is not None else None,
        )
        return ProductCandidate(
            product_id=product_id, name=item.item_name, category=category, service=self.service,
            provider_item_id=item.item_code, offer=offer, evidence=tuple(evidence),
        )


class RakuyokoBoundaryAdapter:
    """Represent only official customer-facing facts; integration stays unknown."""

    service = AffiliateService.RAKUYOKO
    GUIDE = "https://rakuyoko.rakuten.co.jp/guide/"
    capabilities = (
        RakuyokoCapability(
            capability="customer_facing_storefront", status=CapabilityStatus.VERIFIED,
            evidence_reference=GUIDE,
            note="Official guide describes an online store and product categories.",
        ),
        RakuyokoCapability(
            capability="app_customer_notifications", status=CapabilityStatus.VERIFIED,
            evidence_reference=GUIDE,
            note="Official guide describes customer notices for sales, coupons, and delivery status.",
        ),
        RakuyokoCapability(
            capability="external_product_search_api", status=CapabilityStatus.UNKNOWN,
            evidence_reference=GUIDE,
            note="No official external search/API contract was identified in the reviewed public materials.",
        ),
        RakuyokoCapability(
            capability="affiliate_destination", status=CapabilityStatus.UNKNOWN,
            evidence_reference=GUIDE,
            note="No official affiliate-link or attribution contract was identified in the reviewed public materials.",
        ),
        RakuyokoCapability(
            capability="bundle_content_or_workflow_assistance", status=CapabilityStatus.UNKNOWN,
            evidence_reference=GUIDE,
            note="No official external bundle/content-preparation workflow was identified in the reviewed public materials.",
        ),
    )

    def require_verified(self, capability: str) -> None:
        match = next((item for item in self.capabilities if item.capability == capability), None)
        if match is None or match.status != CapabilityStatus.VERIFIED:
            raise UnknownCapabilityError(f"Rakuyoko capability is unknown/unverified: {capability}")

    def normalize_fixture(self, *, provider_item_id: str, product_name: str,
                          observed_at: datetime) -> ProductCandidate:
        """Build an identity-only unverified fixture; never imply API or affiliate support."""
        product_id = f"rakuyoko-{_stable_id(provider_item_id)}"
        evidence = ProductEvidence(
            evidence_id=f"{product_id}:identity", product_id=product_id, service=self.service,
            evidence_type=EvidenceType.PRODUCT_IDENTITY, source_name="Unverified Rakuyoko boundary fixture",
            source_reference=f"offline-fixture:rakuyoko:{provider_item_id}", source_field="product_name",
            observed_at=observed_at, status=EvidenceStatus.UNKNOWN, value_text=product_name,
        )
        offer = AffiliateOffer(
            offer_id=f"{product_id}:offer", service=self.service, provider_item_id=provider_item_id,
            product_destination=AffiliateDestination(
                destination_id=f"{product_id}:product-destination", service=self.service,
                provider_item_id=provider_item_id, status=DestinationStatus.UNKNOWN,
            ),
            affiliate_destination=AffiliateDestination(
                destination_id=f"{product_id}:affiliate-destination", service=self.service,
                provider_item_id=provider_item_id, status=DestinationStatus.UNKNOWN,
            ),
        )
        return ProductCandidate(
            product_id=product_id, name=product_name, category="unverified", service=self.service,
            provider_item_id=provider_item_id, offer=offer, evidence=(evidence,),
        )


def _fixture_evidence(product_id: str, service: AffiliateService, source_ref: str, source_field: str,
                      evidence_type: EvidenceType, observed_at: datetime, *,
                      value_number: Decimal | None = None, value_boolean: bool | None = None) -> ProductEvidence:
    return ProductEvidence(
        evidence_id=f"{product_id}:{source_field}", product_id=product_id, service=service,
        evidence_type=evidence_type, source_name="Rakuten Ichiba Item Search fixture",
        source_reference=source_ref, source_field=source_field, observed_at=observed_at,
        status=EvidenceStatus.FIXTURE, value_number=value_number, value_boolean=value_boolean,
    )


def _parse_api_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("/", "-").replace(" ", "T"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _stable_id(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
