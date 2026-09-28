"""Deterministic, synthetic affiliate fixtures and the offline demo workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from echo.models.affiliate import (
    AffiliateOpportunityScore,
    AffiliateService,
    EvidenceType,
    ProductCandidate,
    ProductSet,
    ProductSetItem,
    ScoreComponent,
    ScoreFeature,
)
from echo.models.affiliate_visual import (
    ComplianceReport,
    DisclosurePlacement,
    LifestyleScene,
    MarketingClaim,
    PlatformVariant,
    SocialPlatform,
    SocialProposal,
    VisualAsset,
    VisualAssetKind,
    RightsStatus,
)
from echo.monetization.adapters import RakuyokoBoundaryAdapter, RakutenFixtureAdapter
from echo.monetization.compliance import evaluate_compliance
from echo.monetization.config import AffiliatePhase0Config, load_phase0_config
from echo.monetization.scoring import rank_candidates, score_candidate
from echo.monetization.signals import derive_buy_now_signals
from echo.monetization.visuals import build_carousel_plan


DEMO_AS_OF = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class AffiliateDemo:
    candidates: tuple[ProductCandidate, ...]
    signals_by_product: dict[str, tuple]
    scores: tuple[AffiliateOpportunityScore, ...]
    ranking: tuple[ProductCandidate, ...]
    proposal: SocialProposal
    compliance: ComplianceReport
    config: AffiliatePhase0Config
    rakuyoko: RakuyokoBoundaryAdapter


def sample_rakuten_candidates(as_of: datetime = DEMO_AS_OF) -> tuple[ProductCandidate, ...]:
    adapter = RakutenFixtureAdapter()
    records = (
        {
            "itemCode": "fixture-lamp-001", "itemName": "Adjustable reading lamp",
            "itemPrice": 5980, "itemUrl": "https://fixture.invalid/items/lamp",
            "availability": 1, "reviewCount": 42, "reviewAverage": "4.6",
            "affiliateRate": "4.0", "endTime": "2026-10-01 23:59",
        },
        {
            "itemCode": "fixture-rug-002", "itemName": "Soft woven area rug",
            "itemPrice": 8990, "itemUrl": "https://fixture.invalid/items/rug",
            "availability": 1, "reviewCount": 8, "reviewAverage": "4.1",
            "affiliateRate": "2.0", "endTime": "2026-09-27 23:59",
        },
        {
            "itemCode": "fixture-blanket-003", "itemName": "Light cotton blanket",
            "itemUrl": "https://fixture.invalid/items/blanket",
        },
        {
            "itemCode": "fixture-organizer-004", "itemName": "Compact desk organizer",
            "itemPrice": 1280, "itemUrl": "https://fixture.invalid/items/organizer",
        },
    )
    categories = ("lighting", "rugs", "bedding", "storage")
    normalized = tuple(adapter.normalize(item, observed_at=as_of, category=category)
                       for item, category in zip(records, categories, strict=True))
    by_id = {candidate.provider_item_id: candidate for candidate in normalized}
    return (
        _with_score_features(by_id["fixture-lamp-001"], {
            ScoreComponent.COMMERCIAL_ATTRACTIVENESS: ("0.80", ("itemPrice",)),
            ScoreComponent.URGENCY: ("0.90", ("endTime",)),
            ScoreComponent.DEMAND: ("0.72", ("reviewCount",)),
            ScoreComponent.TRUST: ("0.82", ("reviewAverage",)),
            ScoreComponent.AFFILIATE_ECONOMICS: ("0.80", ("affiliateRate",)),
            ScoreComponent.CONTEXTUAL_FIT: ("0.90", ("itemName",)),
            ScoreComponent.EVIDENCE_CONFIDENCE: ("0.90", ("itemPrice", "itemName")),
            ScoreComponent.FRESHNESS: ("1.00", ("itemPrice",)),
        }),
        _with_score_features(by_id["fixture-rug-002"], {
            ScoreComponent.COMMERCIAL_ATTRACTIVENESS: ("0.72", ("itemPrice",)),
            ScoreComponent.URGENCY: ("0.90", ("endTime",)),
            ScoreComponent.DEMAND: ("0.45", ("reviewCount",)),
            ScoreComponent.TRUST: ("0.60", ("reviewAverage",)),
            ScoreComponent.AFFILIATE_ECONOMICS: ("0.60", ("affiliateRate",)),
            ScoreComponent.CONTEXTUAL_FIT: ("0.86", ("itemName",)),
            ScoreComponent.EVIDENCE_CONFIDENCE: ("0.68", ("itemPrice", "itemName")),
            ScoreComponent.FRESHNESS: ("0.00", ("itemPrice",)),
        }),
        by_id["fixture-blanket-003"],
        _with_score_features(by_id["fixture-organizer-004"], {
            ScoreComponent.COMMERCIAL_ATTRACTIVENESS: ("0.40", ("itemPrice",)),
            ScoreComponent.CONTEXTUAL_FIT: ("0.50", ("itemName",)),
            ScoreComponent.EVIDENCE_CONFIDENCE: ("0.20", ("itemName",)),
        }),
    )


def run_offline_demo(config: AffiliatePhase0Config | None = None) -> AffiliateDemo:
    config = config or load_phase0_config()
    candidates = sample_rakuten_candidates()
    signals = {
        candidate.product_id: derive_buy_now_signals(
            candidate, as_of=DEMO_AS_OF,
            max_age_by_type=config.buy_now.max_age_by_type,
        )
        for candidate in candidates
    }
    scores = tuple(score_candidate(
        candidate, config.score, as_of=DEMO_AS_OF,
        max_evidence_age=timedelta(hours=config.scoring_max_evidence_age_hours),
        evidence_candidates=candidates,
    ) for candidate in candidates)
    ranking = rank_candidates(candidates, scores)
    product_set = ProductSet(
        product_set_id="fixture-room-set-001",
        theme="calm reading corner",
        shared_scene_id="fixture-scene-overview",
        items=(
            ProductSetItem(product_id=_by_item(candidates, "fixture-rug-002").product_id,
                           slide_order=1, featured=True),
            ProductSetItem(product_id=_by_item(candidates, "fixture-lamp-001").product_id,
                           slide_order=2, featured=True),
        ),
    )
    lamp = _by_item(candidates, "fixture-lamp-001")
    rug = _by_item(candidates, "fixture-rug-002")
    assets = (
        VisualAsset(asset_id="fixture-product-lamp", kind=VisualAssetKind.PRODUCT,
                    source_reference="offline-fixture:lamp-image", provenance_status="fixture",
                    rights_status=RightsStatus.UNKNOWN, official_asset=False,
                    transformations_allowed=False, product_ids=(lamp.product_id,)),
        VisualAsset(asset_id="fixture-product-rug", kind=VisualAssetKind.PRODUCT,
                    source_reference="offline-fixture:rug-image", provenance_status="fixture",
                    rights_status=RightsStatus.UNKNOWN, official_asset=False,
                    transformations_allowed=False, product_ids=(rug.product_id,)),
        VisualAsset(asset_id="fixture-context-overview", kind=VisualAssetKind.GENERATED_CONTEXT,
                    source_reference="offline-fixture:generated-room", provenance_status="fixture",
                    rights_status=RightsStatus.UNKNOWN),
        VisualAsset(asset_id="fixture-context-workspace", kind=VisualAssetKind.GENERATED_CONTEXT,
                    source_reference="offline-fixture:generated-workspace", provenance_status="fixture",
                    rights_status=RightsStatus.UNKNOWN),
        VisualAsset(asset_id="fixture-context-living-area", kind=VisualAssetKind.GENERATED_CONTEXT,
                    source_reference="offline-fixture:generated-living-area", provenance_status="fixture",
                    rights_status=RightsStatus.UNKNOWN),
    )
    overview_scene = _scene("fixture-scene-overview", usage_context="reading and resting corner",
                            camera_angle="wide eye-level overview", product_categories=("rugs", "lighting"))
    detail_scenes = {
        rug.product_id: _scene("fixture-scene-rug", usage_context="rug under a reading chair",
                               camera_angle="low seated angle", product_categories=(rug.category,)),
        lamp.product_id: _scene("fixture-scene-lamp", usage_context="lamp lighting a reading desk",
                                camera_angle="desk-level angle", product_categories=(lamp.category,)),
    }
    carousel = build_carousel_plan(
        product_set, (rug, lamp), assets=assets, overview_scene=overview_scene,
        detail_scenes=detail_scenes, overview_context_asset_id="fixture-context-overview",
        detail_context_asset_ids={
            rug.product_id: "fixture-context-living-area",
            lamp.product_id: "fixture-context-workspace",
        },
        headline=lamp.name, policy=config.visual, prior_scene_fingerprints=(),
    )
    claims = (MarketingClaim(
        claim_id="fixture-lamp-identity",
        product_id=lamp.product_id,
        statement=lamp.name,
        claim_type=EvidenceType.PRODUCT_IDENTITY,
        evidence_ids=(next(item.evidence_id for item in lamp.evidence
                           if item.evidence_type == EvidenceType.PRODUCT_IDENTITY),),
    ),)
    candidate_by_id = {item.product_id: item for item in (rug, lamp)}
    canonical_message = " / ".join(
        candidate_by_id[claim.product_id].name
        if claim.claim_type == EvidenceType.PRODUCT_IDENTITY
        else f"{candidate_by_id[claim.product_id].name}: {claim.statement}"
        for claim in claims
    )
    variants = tuple(PlatformVariant(
        platform=platform,
        caption=f"PR {canonical_message}",
        disclosure_text="PR",
        disclosure_placement=DisclosurePlacement.FIRST_VIEW,
    ) for platform in (SocialPlatform.X, SocialPlatform.INSTAGRAM, SocialPlatform.THREADS))
    proposal = SocialProposal(
        proposal_id="fixture-proposal-room-001",
        product_set_id=product_set.product_set_id,
        canonical_message=canonical_message,
        product_ids=(rug.product_id, lamp.product_id),
        claims=claims, visual_assets=assets, carousel=carousel,
        platform_variants=variants, created_at=DEMO_AS_OF,
    )
    compliance = evaluate_compliance(
        proposal, (rug, lamp), config.compliance, as_of=DEMO_AS_OF,
        prior_scene_fingerprints=(),
    )
    return AffiliateDemo(
        candidates=candidates, signals_by_product=signals, scores=scores, ranking=ranking,
        proposal=proposal, compliance=compliance, config=config,
        rakuyoko=RakuyokoBoundaryAdapter(),
    )


def _with_score_features(candidate: ProductCandidate,
                         inputs: dict[ScoreComponent, tuple[str, tuple[str, ...]]]) -> ProductCandidate:
    evidence_by_field = {item.source_field: item.evidence_id for item in candidate.evidence}
    features = []
    for component, (value, fields) in inputs.items():
        evidence_ids = tuple(evidence_by_field[field] for field in fields if field in evidence_by_field)
        if fields and not evidence_ids:
            continue
        features.append(ScoreFeature(component=component, value=Decimal(value), evidence_ids=evidence_ids))
    return ProductCandidate.model_validate({
        **candidate.model_dump(),
        "score_features": tuple(features),
    })


def _by_item(candidates: tuple[ProductCandidate, ...], provider_item_id: str) -> ProductCandidate:
    return next(candidate for candidate in candidates if candidate.provider_item_id == provider_item_id)


def _scene(scene_id: str, *, usage_context: str, camera_angle: str,
           product_categories: tuple[str, ...]) -> LifestyleScene:
    return LifestyleScene(
        scene_id=scene_id, room_geometry="compact rectangle", room_size="small apartment room",
        window_placement="east wall", furniture_placement="chair beside low shelf",
        interior_style="warm modern", time_of_day="early evening", lighting="soft side light",
        color_temperature="warm neutral", outside_scenery="tree-lined street",
        season="early autumn", camera_angle=camera_angle, usage_context=usage_context,
        product_categories=product_categories,
    )
