"""Deterministic source-neutral discovery orchestration, with no HTTP imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from typing import Protocol

from echo.models.affiliate import (
    AffiliateOpportunityScore, DestinationStatus, EvidenceStatus, EvidenceType,
    ProductCandidate, ProductSet, ProductSetItem, ScoreComponent, ScoreFeature, ValueInterpretation,
)
from echo.models.affiliate_visual import (
    CarouselPlan, CarouselSlide, ComplianceReport, DisclosurePlacement, LifestyleScene, MarketingClaim, PlatformVariant,
    ProductVisualLabel, SlideKind,
    RightsStatus, SocialPlatform, SocialProposal, VisualAsset, VisualAssetKind,
)
from echo.models.discovery import DiscoveryPage, DiscoveryQuery, DiscoverySource, ProviderObservation
from echo.monetization.compliance import evaluate_compliance
from echo.monetization.config import AffiliatePhase0Config, DiscoveryPolicy, load_phase0_config, load_discovery_policy
from echo.monetization.evidence import evidence_is_current, find_conflicting_evidence, interpret_evidence_value
from echo.monetization.scoring import rank_candidates, score_candidate
from echo.monetization.signals import derive_buy_now_signals
from echo.monetization.visuals import build_carousel_plan


class DiscoveryProvider(Protocol):
    def discover(self, query: DiscoveryQuery, *, observed_at: datetime) -> DiscoveryPage: ...


@dataclass(frozen=True)
class DiscoveryResult:
    observations: tuple[ProviderObservation, ...] = field(repr=False)
    candidates: tuple[ProductCandidate, ...] = field(repr=False)
    scores: tuple[AffiliateOpportunityScore, ...]
    selected: tuple[ProductCandidate, ...] = field(repr=False)
    signals_by_product: dict = field(repr=False)
    exclusions: dict[str, tuple[str, ...]]
    proposals: tuple[SocialProposal, ...] = field(repr=False)
    compliance: tuple[ComplianceReport, ...]
    bundle: ProductSet | None
    bundle_notes: tuple[str, ...]
    human_approval_required: bool = True
    can_publish: bool = False


def _merge(observations: tuple[ProviderObservation, ...], *, as_of: datetime,
           price_age: timedelta, availability_age: timedelta, destination_age: timedelta,
           score_age: timedelta) -> tuple[ProductCandidate, ...]:
    groups = {}
    for observation in observations:
        candidate = observation.candidate
        key = (candidate.service.value, candidate.provider_item_id)
        groups.setdefault(key, []).append(observation)
    merged = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda o: (-min(r.observed_at.timestamp() for r in o.candidate.evidence),
                                o.source.value, o.candidate.offer.offer_id, o.query.model_dump_json()))
        base = rows[0].candidate
        records = {}
        for row in rows:
            if row.candidate.product_id != base.product_id:
                raise ValueError("provider item identity must be stable")
            for record in row.candidate.evidence:
                if record.evidence_id in records and records[record.evidence_id] != record:
                    raise ValueError("evidence ID collision; observations cannot be overwritten")
                records[record.evidence_id] = record
        def current(row, kind, *, age, evidence_id=None):
            return any(r.evidence_type == kind and (evidence_id is None or r.evidence_id == evidence_id)
                       and evidence_is_current(r, as_of=as_of, max_age=age) for r in row.candidate.evidence)
        # An absent field is not a contradiction. Retain the latest current known
        # field, with its original evidence linkage, rather than copying one sparse offer.
        price = next((o.candidate.offer.price for o in rows if o.candidate.offer.price is not None
                      and current(o, EvidenceType.PRICE, age=price_age,
                                  evidence_id=o.candidate.offer.price.evidence_id)), None)
        available = next((o.candidate.offer.available for o in rows if o.candidate.offer.available is not None
                          and current(o, EvidenceType.AVAILABILITY, age=availability_age)), None)
        rate = next((o.candidate.offer.affiliate_rate for o in rows if o.candidate.offer.affiliate_rate is not None
                     and current(o, EvidenceType.AFFILIATE_RATE, age=score_age)), None)
        def destination(attribute, kind):
            return next((getattr(o.candidate.offer, attribute) for o in rows
                         if getattr(o.candidate.offer, attribute).status == DestinationStatus.VERIFIED
                         and current(o, kind, age=destination_age,
                                     evidence_id=getattr(o.candidate.offer, attribute).verification_evidence_id)),
                        getattr(base.offer, attribute))
        offer = type(base.offer).model_validate({**base.offer.model_dump(), "price": price,
            "available": available, "affiliate_rate": rate,
            "product_destination": destination("product_destination", EvidenceType.PRODUCT_DESTINATION),
            "affiliate_destination": destination("affiliate_destination", EvidenceType.AFFILIATE_DESTINATION)})
        merged.append(ProductCandidate.model_validate({**base.model_dump(), "offer": offer,
            "evidence": tuple(records[k] for k in sorted(records))}))
    return tuple(merged)


def _assess(candidate: ProductCandidate, policy: DiscoveryPolicy, *, as_of: datetime, max_age: timedelta) -> ProductCandidate:
    positive = {}
    for record in sorted(candidate.evidence, key=lambda r: (-r.observed_at.timestamp(), r.evidence_id)):
        if (evidence_is_current(record, as_of=as_of, max_age=max_age)
                and interpret_evidence_value(record)[0] == ValueInterpretation.POSITIVE):
            positive.setdefault(record.evidence_type, record)
    features = []
    def add(component, record, value):
        if record is not None:
            features.append(ScoreFeature(component=component, value=max(Decimal(0), min(Decimal(1), value)), evidence_ids=(record.evidence_id,)))
    price = next((r for r in candidate.evidence if candidate.offer.price and r.evidence_id == candidate.offer.price.evidence_id), None)
    add(ScoreComponent.COMMERCIAL_ATTRACTIVENESS, price, policy.observed_price_assessment)
    rank = positive.get(EvidenceType.RANKING)
    count = positive.get(EvidenceType.REVIEW_COUNT)
    if rank:
        add(ScoreComponent.DEMAND, rank, (Decimal(11) - rank.value_number) / 10)
    elif count:
        add(ScoreComponent.DEMAND, count, count.value_number / policy.review_count_target)
    rating = positive.get(EvidenceType.REVIEW_RATING)
    if rating:
        add(ScoreComponent.TRUST, rating, (rating.value_number - 3) / 2)
    rate = next((r for r in candidate.evidence if r.evidence_type == EvidenceType.AFFILIATE_RATE
                 and candidate.offer.affiliate_rate is not None and r.value_number == candidate.offer.affiliate_rate * 100
                 and r in positive.values()), None)
    if rate:
        add(ScoreComponent.AFFILIATE_ECONOMICS, rate, rate.value_number / policy.affiliate_percent_target)
    end = positive.get(EvidenceType.SALE_END)
    points = positive.get(EvidenceType.POINT_MULTIPLIER)
    if end:
        hours = Decimal(str((end.valid_until - as_of).total_seconds())) / 3600
        add(ScoreComponent.URGENCY, end, max(Decimal(0), Decimal(1) - hours / 72))
    elif points:
        add(ScoreComponent.URGENCY, points, (points.value_number - 1) / 9)
    identity = next((r for r in candidate.evidence if r.evidence_type == EvidenceType.PRODUCT_IDENTITY and r.value_text == candidate.name), None)
    add(ScoreComponent.CONTEXTUAL_FIT, identity, policy.contextual_identity_assessment)
    return ProductCandidate.model_validate({**candidate.model_dump(), "score_features": tuple(features)})


def _scene(identity, context, categories, *, detail=False):
    return LifestyleScene(scene_id=identity, room_geometry="planned rectangular room", room_size="planned compact room",
        window_placement="planned side window", furniture_placement="planned functional corner", interior_style="restrained original lifestyle",
        time_of_day="planned daytime", lighting="planned natural light", color_temperature="planned neutral",
        outside_scenery="unspecified planned view", season="unspecified", camera_angle="detail view " + identity if detail else "wide overview",
        usage_context=context, product_categories=categories)


def _proposal(candidates, observations, context, config, as_of):
    ids = tuple(c.product_id for c in candidates)
    identity = hashlib.sha256((context + "|" + "|".join(ids)).encode()).hexdigest()[:16]
    set_id = "discovery-set-" + identity
    product_set = ProductSet(product_set_id=set_id, theme=context,
        shared_scene_id="overview-" + identity,
        items=tuple(ProductSetItem(product_id=c.product_id, slide_order=i + 1, featured=True) for i, c in enumerate(candidates))) if len(candidates) >= 2 else None
    assets = []
    for candidate in candidates:
        refs = [a for o in observations if o.candidate.product_id == candidate.product_id for a in o.assets]
        if not refs or len(candidate.name) > config.visual.max_slide1_headline_characters:
            return None
        ref = sorted(refs, key=lambda a: (a.url, a.source_field))[0]
        assets.append(VisualAsset(asset_id="asset-" + candidate.product_id, kind=VisualAssetKind.PRODUCT,
            source_reference=ref.url, provenance_status=ref.status, rights_status=RightsStatus.UNKNOWN,
            official_asset=None, transformations_allowed=None, product_ids=(candidate.product_id,)))
    overview_id = "context-" + identity
    detail_ids = {c.product_id: "context-detail-" + c.product_id for c in candidates}
    for aid in (overview_id, *detail_ids.values()):
        assets.append(VisualAsset(asset_id=aid, kind=VisualAssetKind.GENERATED_CONTEXT,
            source_reference="planned-not-rendered:" + aid, provenance_status=EvidenceStatus.UNKNOWN,
            rights_status=RightsStatus.UNKNOWN))
    if product_set is not None:
        carousel = build_carousel_plan(product_set, candidates, assets=tuple(assets),
        overview_scene=_scene(product_set.shared_scene_id, context, tuple(sorted({c.category for c in candidates}))),
        detail_scenes={c.product_id: _scene("detail-" + c.product_id, context, (c.category,), detail=True) for c in candidates},
        overview_context_asset_id=overview_id, detail_context_asset_ids=detail_ids, headline=candidates[0].name,
        policy=config.visual, prior_scene_fingerprints=())
    else:
        candidate = candidates[0]
        label = ProductVisualLabel(product_id=candidate.product_id, product_name=candidate.name,
            price=candidate.offer.price.amount, currency=candidate.offer.price.currency,
            price_evidence_id=candidate.offer.price.evidence_id,
            destination_id=candidate.offer.affiliate_destination.destination_id, product_asset_id="asset-" + candidate.product_id)
        carousel = CarouselPlan(product_set_id=set_id, slides=(
            CarouselSlide(slide_number=1, kind=SlideKind.OVERVIEW,
                scene=_scene("overview-" + identity, context, (candidate.category,)), labels=(label,),
                context_asset_id=overview_id, headline=candidate.name, arrow_product_ids=(candidate.product_id,)),
            CarouselSlide(slide_number=2, kind=SlideKind.PRODUCT_DETAIL,
                scene=_scene("detail-" + candidate.product_id, context, (candidate.category,), detail=True),
                labels=(label,), context_asset_id=detail_ids[candidate.product_id])))
    claims = tuple(MarketingClaim(claim_id="identity-" + c.product_id, product_id=c.product_id,
        statement=c.name, claim_type=EvidenceType.PRODUCT_IDENTITY,
        evidence_ids=(next(r.evidence_id for r in c.evidence if r.evidence_type == EvidenceType.PRODUCT_IDENTITY and r.value_text == c.name),)) for c in candidates)
    message = " / ".join(c.name for c in candidates)
    proposal = SocialProposal(proposal_id="discovery-proposal-" + identity, product_set_id=set_id,
        canonical_message=message, product_ids=ids, claims=claims, visual_assets=tuple(assets), carousel=carousel,
        platform_variants=(PlatformVariant(platform=SocialPlatform.X, caption="PR " + message,
            disclosure_text="PR", disclosure_placement=DisclosurePlacement.FIRST_VIEW),), created_at=as_of)
    report = evaluate_compliance(proposal, candidates, config.compliance, as_of=as_of,
                                 prior_scene_fingerprints=None)
    return product_set, proposal, report


def discover_products(provider: DiscoveryProvider, queries: tuple[DiscoveryQuery, ...], *, as_of: datetime,
                      policy: DiscoveryPolicy | None = None, config: AffiliatePhase0Config | None = None) -> DiscoveryResult:
    policy, config = policy or load_discovery_policy(), config or load_phase0_config()
    if as_of.tzinfo is None or not queries or len(queries) > policy.max_queries or any(q.source == DiscoverySource.GENRES for q in queries):
        raise ValueError("bounded product queries and an aware evaluation time are required")
    from collections import defaultdict
    observations = []
    for query in queries:
        maximum = 34 if query.source == DiscoverySource.RANKING else 100
        for page in range(query.page, min(maximum + 1, query.page + policy.pages_per_query)):
            current = DiscoveryQuery.model_validate({**query.model_dump(), "page": page})
            result = provider.discover(current, observed_at=as_of)
            observations.extend(result.observations)
            if result.not_found or not result.observations or result.total_pages is not None and page >= result.total_pages:
                break
    observations = tuple(sorted(observations, key=lambda o: (o.candidate.product_id, o.candidate.offer.offer_id, o.query.model_dump_json())))
    max_age = timedelta(hours=config.scoring_max_evidence_age_hours)
    candidates = tuple(_assess(c, policy, as_of=as_of, max_age=max_age) for c in _merge(observations,
        as_of=as_of, price_age=timedelta(hours=config.compliance.max_price_age_hours),
        availability_age=timedelta(hours=config.buy_now.max_age_by_type[EvidenceType.AVAILABILITY]),
        destination_age=timedelta(hours=config.compliance.max_destination_age_hours), score_age=max_age))
    scores = tuple(score_candidate(c, config.score, as_of=as_of, max_evidence_age=max_age, evidence_candidates=candidates) for c in candidates)
    signals = {c.product_id: derive_buy_now_signals(c, as_of=as_of, max_age_by_type=config.buy_now.max_age_by_type) for c in candidates}
    score_by_id = {s.product_id: s for s in scores};exclusions = {};eligible = []
    for candidate in rank_candidates(candidates, scores):
        reasons = []
        if candidate.offer.available is not True:
            reasons.append("availability_unknown_or_out_of_stock")
        available = [r for r in candidate.evidence if r.evidence_type == EvidenceType.AVAILABILITY and r.value_boolean is True
                     and evidence_is_current(r, as_of=as_of, max_age=timedelta(hours=config.buy_now.max_age_by_type[EvidenceType.AVAILABILITY]))]
        if not available:
            reasons.append("current_availability_evidence_missing")
        price = next((r for r in candidate.evidence if candidate.offer.price and r.evidence_id == candidate.offer.price.evidence_id), None)
        if price is None or not evidence_is_current(price, as_of=as_of, max_age=timedelta(hours=config.compliance.max_price_age_hours)):
            reasons.append("current_exact_price_missing")
        if find_conflicting_evidence((candidate,), as_of=as_of, max_age=max_age):
            reasons.append("current_evidence_conflict")
        if score_by_id[candidate.product_id].final_score < policy.minimum_score:
            reasons.append("below_quality_threshold")
        if reasons:
            exclusions[candidate.product_id] = tuple(reasons)
        else:
            eligible.append(candidate)
    selected = tuple(eligible[:policy.top_n]);proposals = [];reports = [];bundle = None;bundle_notes = []
    by_product = defaultdict(list)
    for o in observations:
        by_product[o.candidate.product_id].append(o)
    for candidate in selected:
        contexts = {o.query.lifestyle_context for o in by_product[candidate.product_id] if o.query.lifestyle_context}
        if len(contexts) == 1:
            planned = _proposal((candidate,), observations, next(iter(contexts)), config, as_of)
            if planned:
                proposals.append(planned[1]);reports.append(planned[2])
    # Bundle only explicit, unambiguous complementary intents with individually verified destinations.
    contexts = {};roles = {}
    for c in selected:
        contexts[c.product_id] = {o.query.lifestyle_context for o in by_product[c.product_id]}
        roles[c.product_id] = {o.query.complementary_role for o in by_product[c.product_id]}
    if len(selected) >= 2:
        common = set.intersection(*(contexts[c.product_id] for c in selected)) - {None}
        unique_roles = [next(iter(roles[c.product_id])) if len(roles[c.product_id]) == 1 else None for c in selected]
        destinations = all(c.offer.product_destination.status == c.offer.affiliate_destination.status == DestinationStatus.VERIFIED for c in selected)
        verified = all(all(r.status == EvidenceStatus.VERIFIED for r in c.evidence) for c in selected)
        if len(common) == 1 and all(len(contexts[c.product_id]) == 1 for c in selected) and all(unique_roles) and len(set(unique_roles)) == len(selected) and destinations and verified:
            planned = _proposal(selected, observations, next(iter(common)), config, as_of)
            if planned:
                bundle = planned[0];proposals.append(planned[1]);reports.append(planned[2])
        if bundle is None:
            bundle_notes.append("bundle_requires_explicit_shared_context_complementary_roles_verified_individual_evidence_and_destinations")
    return DiscoveryResult(observations, candidates, scores, selected, signals, exclusions,
                           tuple(proposals), tuple(reports), bundle, tuple(bundle_notes))
