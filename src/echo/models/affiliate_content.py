"""Typed content metadata attached to the existing SocialProposal contract."""

from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import Field, model_validator

from echo.models.affiliate import AffiliateModel, AffiliateService


class ContextHeadline(str, Enum):
    DESK = "机まわりに。"
    LIFESTYLE = "暮らしのひとこま。"


class ContentProduct(AffiliateModel):
    product_id: str = Field(min_length=1)
    service: AffiliateService
    provider_item_id: str = Field(min_length=1, repr=False)
    canonical_product_name: str = Field(min_length=1)
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_evidence_id: str = Field(min_length=1)
    identity_evidence_id: str = Field(min_length=1)
    affiliate_destination_reference: str = Field(min_length=1, repr=False)
    claim_evidence_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _exact_fact_inventory(self) -> Self:
        if len(self.claim_evidence_ids) != 2 or set(self.claim_evidence_ids) != {self.identity_evidence_id, self.price_evidence_id}:
            raise ValueError("content initially renders exactly identity and current price")
        return self


class ContentProposalDetails(AffiliateModel):
    products: tuple[ContentProduct, ...] = Field(min_length=1)
    headline: ContextHeadline
    disclosure: Literal["PR"] = "PR"
    human_approval_required: Literal[True] = True
    can_publish: Literal[False] = False

    @model_validator(mode="after")
    def _unique_products(self) -> Self:
        if len({p.product_id for p in self.products}) != len(self.products):
            raise ValueError("content products must be unique")
        return self

    @property
    def body_copy(self) -> str:
        service_labels = {AffiliateService.RAKUTEN_ICHIBA: "楽天市場", AffiliateService.RAKUYOKO: "ラクヨコ"}
        facts = "\n\n".join(f"{p.canonical_product_name}\n価格: {p.price} {p.currency}\n{service_labels[p.service]}の商品（アフィリエイト）\n[destination:{p.affiliate_destination_reference}]" for p in self.products)
        return f"{self.headline.value}\n\n{facts}"

    @property
    def x_caption(self) -> str:
        return "PR " + self.body_copy


class WebServiceCredit(AffiliateModel):
    required: Literal[True] = True
    surface_status: Literal["unresolved_for_social_only"] = "unresolved_for_social_only"
    policy_reference: Literal["https://webservice.rakuten.co.jp/guide/credit"] = "https://webservice.rakuten.co.jp/guide/credit"

    @property
    def resolved(self) -> bool:
        return False  # No invented compliant social placement in Stage 6A.
