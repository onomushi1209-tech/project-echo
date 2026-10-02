"""Bounded source-neutral acquisition of current offers for ranked products."""

from datetime import datetime, timedelta
from typing import Callable

from echo.models.affiliate import EvidenceType
from echo.models.discovery import (
    DiscoveryIdentityMismatch, DiscoveryPage, DiscoveryQuery, DiscoverySource,
    HydrationOutcome, HydrationReport, ProviderObservation,
)
from echo.monetization.config import AffiliatePhase0Config, DiscoveryPolicy
from echo.monetization.evidence import evidence_is_current


def current_offer(observation: ProviderObservation, *, as_of: datetime, config: AffiliatePhase0Config) -> bool:
    candidate = observation.candidate
    price = candidate.offer.price
    return price is not None and candidate.offer.available is True and any(
        e.evidence_id == price.evidence_id and e.evidence_type == EvidenceType.PRICE
        and evidence_is_current(e, as_of=as_of, max_age=timedelta(hours=config.compliance.max_price_age_hours))
        for e in candidate.evidence
    ) and any(
        e.evidence_type == EvidenceType.AVAILABILITY and e.value_boolean is True
        and evidence_is_current(e, as_of=as_of, max_age=timedelta(hours=config.buy_now.max_age_by_type[EvidenceType.AVAILABILITY]))
        for e in candidate.evidence
    )


def hydrate_ranked(observations: tuple[ProviderObservation, ...], fetch: Callable[[DiscoveryQuery], DiscoveryPage],
                   *, as_of: datetime, policy: DiscoveryPolicy, config: AffiliatePhase0Config):
    if not policy.ranking_hydration_enabled:
        return (), HydrationReport()
    current_search = {
        (o.candidate.service, o.candidate.provider_item_id) for o in observations
        if o.source == DiscoverySource.SEARCH and current_offer(o, as_of=as_of, config=config)
    }
    ranked = {}
    skipped = set()
    for observation in observations:
        if observation.source != DiscoverySource.RANKING:
            continue
        key = (observation.candidate.service, observation.candidate.provider_item_id)
        if key in current_search:
            skipped.add(key)
            continue
        if current_offer(observation, as_of=as_of, config=config):
            continue
        ranks = [e for e in observation.candidate.evidence if e.evidence_type == EvidenceType.RANKING
                 and e.value_number is not None and evidence_is_current(e, as_of=as_of,
                     max_age=timedelta(hours=config.scoring_max_evidence_age_hours))]
        if not ranks:
            continue
        order = (min(e.value_number for e in ranks), key[0].value, key[1], observation.query.model_dump_json())
        if key not in ranked or order < ranked[key][0]:
            ranked[key] = (order, observation)
    selected = sorted(ranked.values(), key=lambda row: row[0])[:policy.ranking_hydration_top_k]
    hydrated = []
    outcomes = []
    for _, original in selected:
        # Fixed preselection: failures never trigger replacement/crawling.
        item = original.candidate.provider_item_id
        query = DiscoveryQuery(provider_item_id=item, limit=1, page=1, available_only=False,
            category=original.query.category, lifestyle_context=original.query.lifestyle_context,
            complementary_role=original.query.complementary_role)
        try:
            page = fetch(query)
        except DiscoveryIdentityMismatch:
            outcomes.append(HydrationOutcome(provider_item_id=item, status="identity_mismatch"))
            continue
        if page.not_found or not page.observations:
            outcomes.append(HydrationOutcome(provider_item_id=item, status="not_found"))
            continue
        if len(page.observations) != 1 or any(o.candidate.provider_item_id != item
                or o.candidate.service != original.candidate.service or o.source != DiscoverySource.SEARCH
                for o in page.observations):
            outcomes.append(HydrationOutcome(provider_item_id=item, status="identity_mismatch"))
            continue
        hydrated.extend(page.observations)
        offer = page.observations[0].candidate.offer
        status = ("out_of_stock" if offer.available is False else "availability_unknown" if offer.available is None
                  else "missing_exact_price" if offer.price is None else "success")
        outcomes.append(HydrationOutcome(provider_item_id=item, status=status,
            affiliate_destination_present=bool(page.observations[0].returned_affiliate_url)))
    return tuple(hydrated), HydrationReport(selected_count=len(selected), requests=len(outcomes),
        skipped_current_search=len(skipped), outcomes=tuple(outcomes))
