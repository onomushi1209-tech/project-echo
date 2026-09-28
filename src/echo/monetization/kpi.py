"""Null-preserving affiliate KPI calculations."""

from __future__ import annotations

from decimal import Decimal

from echo.models.affiliate_kpi import AffiliateKPIObservation, AffiliateKPIMetrics


def calculate_kpis(observation: AffiliateKPIObservation) -> AffiliateKPIMetrics:
    """Calculate ratios only when both the source metric and denominator exist."""
    ctr = _ratio(observation.clicks, observation.impressions)
    cvr = _ratio(observation.orders, observation.clicks)
    epc = _amount_ratio(observation.confirmed_revenue, observation.clicks)
    revenue_per_1000 = _amount_ratio(
        observation.confirmed_revenue, observation.impressions, multiplier=Decimal("1000")
    )
    profit = None
    if observation.confirmed_revenue is not None and observation.actual_costs is not None:
        profit = observation.confirmed_revenue - observation.actual_costs
    return AffiliateKPIMetrics(
        observation_id=observation.observation_id,
        ctr=ctr,
        cvr=cvr,
        epc=epc,
        revenue_per_1000_impressions=revenue_per_1000,
        profit=profit,
    )


def _ratio(numerator: int | None, denominator: int | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _amount_ratio(amount: Decimal | None, denominator: int | None, *,
                  multiplier: Decimal = Decimal("1")) -> Decimal | None:
    if amount is None or denominator is None or denominator == 0:
        return None
    return amount * multiplier / Decimal(denominator)
