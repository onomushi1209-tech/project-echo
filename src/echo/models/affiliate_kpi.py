"""Attribution-aware, nullable KPI observations for future affiliate learning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from echo.models.affiliate import AffiliateModel, AffiliateService
from echo.models.affiliate_visual import SocialPlatform


class AffiliateAttribution(AffiliateModel):
    source_service: AffiliateService
    platform: SocialPlatform | None = None
    account_id: str | None = None
    post_id: str | None = None
    proposal_id: str | None = None
    product_id: str | None = None
    product_set_id: str | None = None
    creative_format: str | None = None
    time_slot: str | None = None


class AffiliateKPIObservation(AffiliateModel):
    observation_id: str = Field(min_length=1)
    observed_at: datetime
    attribution: AffiliateAttribution
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    impressions: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    orders: int | None = Field(default=None, ge=0)
    gross_affiliate_revenue: Decimal | None = Field(default=None, ge=0)
    confirmed_revenue: Decimal | None = Field(default=None, ge=0)
    rejected_or_cancelled_revenue: Decimal | None = Field(default=None, ge=0)
    actual_costs: Decimal | None = Field(default=None, ge=0)


class AffiliateKPIMetrics(AffiliateModel):
    observation_id: str = Field(min_length=1)
    ctr: Decimal | None = Field(default=None, ge=0)
    cvr: Decimal | None = Field(default=None, ge=0)
    epc: Decimal | None = Field(default=None, ge=0)
    revenue_per_1000_impressions: Decimal | None = Field(default=None, ge=0)
    profit: Decimal | None = None
