"""Offline regression coverage for the Affiliate Phase 0 foundation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from echo.cli import app
from echo.models.affiliate import (
    AffiliateDestination,
    AffiliateOffer,
    AffiliateService,
    BuyNowSignal,
    DestinationStatus,
    EvidenceStatus,
    EvidenceType,
    OpportunityScoreConfig,
    ProductCandidate,
    ProductEvidence,
    ProductSet,
    ProductSetItem,
    ScoreComponent,
    ScoreFeature,
    ScoreWeight,
)
from echo.models.affiliate_kpi import (
    AffiliateAttribution,
    AffiliateKPIObservation,
)
from echo.models.affiliate_visual import (
    ComplianceCheckCode,
    DisclosurePlacement,
    HumanApproval,
    LifestyleScene,
    MarketingClaim,
    PlatformVariant,
    RightsStatus,
    SocialPlatform,
    SocialProposal,
    VisualAsset,
    VisualAssetKind,
)
from echo.models.enums import DecisionType
from echo.models.review import ReviewDecision
from echo.monetization.adapters import (
    CapabilityStatus,
    RakuyokoBoundaryAdapter,
    RakutenFixtureAdapter,
    UnknownCapabilityError,
)
from echo.monetization.compliance import evaluate_compliance
from echo.monetization.config import CompliancePolicy, load_phase0_config
from echo.monetization.evidence import find_conflicting_evidence
from echo.monetization.fixtures import DEMO_AS_OF, run_offline_demo, sample_rakuten_candidates
from echo.monetization.kpi import calculate_kpis
from echo.monetization.scoring import rank_candidates, score_candidate
from echo.monetization.signals import derive_buy_now_signals
from echo.monetization.visuals import proposal_content_digest, validate_scene_diversity


runner = CliRunner()
CONFIG = load_phase0_config()


def _by_item(provider_item_id: str, *, verified: bool = False) -> ProductCandidate:
    candidate = next(item for item in sample_rakuten_candidates()
                     if item.provider_item_id == provider_item_id)
    if not verified:
        return candidate
    evidence = [ProductEvidence.model_validate({
        **item.model_dump(), "status": EvidenceStatus.VERIFIED,
    }) for item in candidate.evidence]
    product_url = f"https://fixture.invalid/items/{provider_item_id}"
    affiliate_url = f"https://fixture.invalid/affiliate/{provider_item_id}"
    product_evidence_id = f"{candidate.product_id}:verified-product-destination"
    affiliate_evidence_id = f"{candidate.product_id}:verified-affiliate-destination"
    evidence.extend((
        ProductEvidence(
            evidence_id=product_evidence_id, product_id=candidate.product_id,
            service=candidate.service, evidence_type=EvidenceType.PRODUCT_DESTINATION,
            source_name="Synthetic compliance fixture", source_reference="offline-fixture:destination-proof",
            source_field="itemUrl", provider_item_id=candidate.provider_item_id,
            observed_at=DEMO_AS_OF, status=EvidenceStatus.VERIFIED, value_text=product_url,
        ),
        ProductEvidence(
            evidence_id=affiliate_evidence_id, product_id=candidate.product_id,
            service=candidate.service, evidence_type=EvidenceType.AFFILIATE_DESTINATION,
            source_name="Synthetic compliance fixture", source_reference="offline-fixture:destination-proof",
            source_field="affiliateUrl", provider_item_id=candidate.provider_item_id,
            observed_at=DEMO_AS_OF, status=EvidenceStatus.VERIFIED, value_text=affiliate_url,
        ),
    ))
    product_destination = AffiliateDestination(
        destination_id=candidate.offer.product_destination.destination_id,
        service=candidate.service,
        provider_item_id=candidate.provider_item_id,
        status=DestinationStatus.VERIFIED,
        destination_url=product_url,
        verification_evidence_id=product_evidence_id,
    )
    affiliate_destination = AffiliateDestination(
        destination_id=candidate.offer.affiliate_destination.destination_id,
        service=candidate.service,
        provider_item_id=candidate.provider_item_id,
        status=DestinationStatus.VERIFIED,
        destination_url=affiliate_url,
        verification_evidence_id=affiliate_evidence_id,
    )
    offer = AffiliateOffer(
        offer_id=candidate.offer.offer_id,
        service=candidate.service,
        provider_item_id=candidate.provider_item_id,
        product_destination=product_destination,
        affiliate_destination=affiliate_destination,
        price=candidate.offer.price,
        affiliate_rate=candidate.offer.affiliate_rate,
        available=candidate.offer.available,
    )
    return ProductCandidate(
        product_id=candidate.product_id, name=candidate.name, category=candidate.category,
        service=candidate.service, provider_item_id=candidate.provider_item_id,
        offer=offer, evidence=tuple(evidence), score_features=candidate.score_features,
    )


def _approved_test_proposal() -> tuple[SocialProposal, tuple[ProductCandidate, ...]]:
    demo = run_offline_demo()
    candidates = (
        _by_item("fixture-rug-002", verified=True),
        _by_item("fixture-lamp-001", verified=True),
    )
    assets = tuple(VisualAsset.model_validate({
        **asset.model_dump(),
        "provenance_status": EvidenceStatus.VERIFIED,
        "rights_status": RightsStatus.GRANTED,
        "official_asset": False if asset.kind == VisualAssetKind.PRODUCT else asset.official_asset,
        "transformations_allowed": False if asset.kind == VisualAssetKind.PRODUCT else asset.transformations_allowed,
    }) for asset in demo.proposal.visual_assets)
    proposal = SocialProposal.model_validate({
        **demo.proposal.model_dump(),
        "visual_assets": assets,
    })
    return proposal, candidates


def _proposal_with_claims(
    proposal: SocialProposal,
    candidates: tuple[ProductCandidate, ...],
    claims: tuple[MarketingClaim, ...],
) -> SocialProposal:
    candidate_by_id = {item.product_id: item for item in candidates}
    rendered_claims = []
    for claim in claims:
        candidate = candidate_by_id[claim.product_id]
        rendered_claims.append(
            candidate.name if claim.claim_type == EvidenceType.PRODUCT_IDENTITY
            else f"{candidate.name}: {claim.statement}"
        )
    canonical_message = " / ".join(rendered_claims)
    variants = tuple(PlatformVariant(
        platform=item.platform,
        caption="PR" if not canonical_message else f"PR {canonical_message}",
        disclosure_text="PR",
        disclosure_placement=DisclosurePlacement.FIRST_VIEW,
    ) for item in proposal.platform_variants)
    return SocialProposal.model_validate({
        **proposal.model_dump(),
        "canonical_message": canonical_message,
        "claims": claims,
        "platform_variants": variants,
    })


def _check(report, code: ComplianceCheckCode) -> bool:
    return next(item.passed for item in report.checks if item.code == code)


def test_rakuten_fixture_normalizes_officially_documented_item_fields_without_links() -> None:
    adapter = RakutenFixtureAdapter()
    candidate = adapter.normalize({
        "itemCode": "fixture:point-lamp", "itemName": "Reading lamp", "itemPrice": 4500,
        "itemUrl": "https://fixture.invalid/product", "availability": 1, "reviewCount": 21,
        "reviewAverage": "4.5", "affiliateRate": "3.0", "pointRate": 5,
        "pointRateStartTime": "2026-09-28 11:00", "pointRateEndTime": "2026-09-29 11:00",
        "startTime": "2026-09-28 10:00", "endTime": "2026-09-30 22:00",
    }, observed_at=DEMO_AS_OF, category="lighting")

    by_type = {item.evidence_type: item for item in candidate.evidence}
    assert candidate.service == AffiliateService.RAKUTEN_ICHIBA
    assert candidate.offer.price.amount == Decimal("4500")
    assert candidate.offer.affiliate_rate == Decimal("0.03")
    assert candidate.offer.available is True
    assert by_type[EvidenceType.POINT_MULTIPLIER].value_number == Decimal("5")
    assert by_type[EvidenceType.POINT_MULTIPLIER].valid_until == datetime(
        2026, 9, 29, 11, tzinfo=timezone.utc
    )
    assert all(item.status == EvidenceStatus.FIXTURE for item in candidate.evidence)
    assert candidate.offer.affiliate_destination.status == DestinationStatus.NOT_CREATED
    assert candidate.offer.product_destination.destination_url is None
    assert candidate.offer.affiliate_destination.destination_url is None


def test_missing_rakuten_price_remains_unknown_and_has_no_visual_price() -> None:
    candidate = _by_item("fixture-blanket-003")
    assert candidate.offer.price is None
    assert not any(item.evidence_type == EvidenceType.PRICE for item in candidate.evidence)


def test_rakuyoko_boundary_keeps_undocumented_integrations_unknown() -> None:
    adapter = RakuyokoBoundaryAdapter()
    status = {item.capability: item.status for item in adapter.capabilities}
    assert status["customer_facing_storefront"] == CapabilityStatus.VERIFIED
    assert status["app_customer_notifications"] == CapabilityStatus.VERIFIED
    for capability in ("external_product_search_api", "affiliate_destination",
                       "bundle_content_or_workflow_assistance"):
        assert status[capability] == CapabilityStatus.UNKNOWN
        with pytest.raises(UnknownCapabilityError):
            adapter.require_verified(capability)
    candidate = adapter.normalize_fixture(
        provider_item_id="unknown-1", product_name="Unverified product", observed_at=DEMO_AS_OF
    )
    assert candidate.offer.price is None
    assert candidate.offer.affiliate_destination.status == DestinationStatus.UNKNOWN


def test_product_set_and_carousel_keep_each_item_and_destination_separate() -> None:
    demo = run_offline_demo()
    proposal = demo.proposal
    item_ids = [item.product_id for item in proposal.carousel.slides[0].labels]
    destinations = [item.destination_id for item in proposal.carousel.slides[0].labels]
    assert len(item_ids) == 2 and len(set(item_ids)) == 2
    assert len(destinations) == 2 and len(set(destinations)) == 2
    assert [slide.labels[0].product_id for slide in proposal.carousel.slides[1:]] == item_ids
    assert all(label.product_name and label.price > 0 for slide in proposal.carousel.slides
               for label in slide.labels)
    with pytest.raises(ValidationError):
        ProductSet(product_set_id="bad", theme="test", shared_scene_id="room", items=(
            ProductSetItem(product_id="same", slide_order=1),
            ProductSetItem(product_id="same", slide_order=2),
        ))


def test_buy_now_signals_cite_fresh_evidence_and_expire_by_policy() -> None:
    candidate = _by_item("fixture-lamp-001")
    signals = derive_buy_now_signals(candidate, as_of=DEMO_AS_OF,
                                      max_age_by_type=CONFIG.buy_now.max_age_by_type)
    assert signals
    assert all(signal.evidence_id in {item.evidence_id for item in candidate.evidence}
               for signal in signals)
    assert all(signal.evidence_status == EvidenceStatus.FIXTURE
               and signal.live_action_authorized is False for signal in signals)
    review_count_signal = next(item for item in signals if item.evidence_type == EvidenceType.REVIEW_COUNT)
    review_evidence = next(item for item in candidate.evidence if item.evidence_id == review_count_signal.evidence_id)
    assert review_count_signal.expires_at == review_evidence.observed_at + timedelta(hours=168)
    rug = _by_item("fixture-rug-002")
    assert not any(item.evidence_type == EvidenceType.SALE_END for item in derive_buy_now_signals(
        rug, as_of=DEMO_AS_OF, max_age_by_type=CONFIG.buy_now.max_age_by_type
    ))


def test_future_and_expired_promotion_evidence_do_not_emit_signals() -> None:
    candidate = _by_item("fixture-lamp-001")
    evidence = ProductEvidence(
        evidence_id="future-coupon", product_id=candidate.product_id, service=candidate.service,
        evidence_type=EvidenceType.COUPON, source_name="fixture", source_reference="offline-fixture:coupon",
        source_field="coupon", observed_at=DEMO_AS_OF, valid_from=DEMO_AS_OF + timedelta(hours=1),
        valid_until=DEMO_AS_OF + timedelta(hours=2), status=EvidenceStatus.FIXTURE, value_text="10%",
    )
    changed = ProductCandidate.model_validate({**candidate.model_dump(),
        "evidence": (*candidate.evidence, evidence)})
    signals = derive_buy_now_signals(changed, as_of=DEMO_AS_OF,
                                     max_age_by_type=CONFIG.buy_now.max_age_by_type)
    assert all(item.evidence_id != evidence.evidence_id for item in signals)


def test_negative_availability_and_zero_strength_do_not_become_buy_now_signals() -> None:
    candidate = _by_item("fixture-lamp-001")
    negative = ProductEvidence(
        evidence_id="out-of-stock", product_id=candidate.product_id, service=candidate.service,
        evidence_type=EvidenceType.AVAILABILITY, source_name="fixture", source_reference="offline-fixture:stock",
        source_field="availability", observed_at=DEMO_AS_OF, status=EvidenceStatus.FIXTURE,
        value_boolean=False,
    )
    changed = ProductCandidate.model_validate({**candidate.model_dump(),
        "evidence": (*candidate.evidence, negative)})
    signals = derive_buy_now_signals(changed, as_of=DEMO_AS_OF,
                                     max_age_by_type=CONFIG.buy_now.max_age_by_type)
    assert all(item.evidence_id != negative.evidence_id for item in signals)


def test_score_is_deterministic_explainable_and_does_not_renormalize_missing_data() -> None:
    candidate = _by_item("fixture-lamp-001")
    first = score_candidate(candidate, CONFIG.score, as_of=DEMO_AS_OF,
                            max_evidence_age=timedelta(hours=CONFIG.scoring_max_evidence_age_hours))
    second = score_candidate(candidate, CONFIG.score, as_of=DEMO_AS_OF,
                             max_evidence_age=timedelta(hours=CONFIG.scoring_max_evidence_age_hours))
    assert first == second
    assert len(first.components) == len(ScoreComponent)
    assert sum(item.weighted_value for item in first.components) == first.final_score
    missing = _by_item("fixture-blanket-003")
    missing_score = score_candidate(missing, CONFIG.score, as_of=DEMO_AS_OF,
                                    max_evidence_age=timedelta(hours=168))
    assert missing_score.final_score == 0
    old_price = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.PRICE)
    stale = ProductEvidence.model_validate({
        **old_price.model_dump(), "observed_at": DEMO_AS_OF - timedelta(days=30),
    })
    evidence = tuple(stale if item.evidence_id == old_price.evidence_id else item
                     for item in candidate.evidence)
    features = (ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS,
                             value=Decimal("1"), evidence_ids=(old_price.evidence_id,)),)
    stale_candidate = ProductCandidate.model_validate({**candidate.model_dump(),
        "evidence": evidence, "score_features": features})
    stale_score = score_candidate(stale_candidate, CONFIG.score, as_of=DEMO_AS_OF,
                                  max_evidence_age=timedelta(hours=168))
    assert stale_score.final_score == 0


def test_candidate_ranking_is_stable_and_missing_data_stays_at_the_bottom() -> None:
    demo = run_offline_demo()
    first = rank_candidates(demo.candidates, demo.scores)
    second = rank_candidates(demo.candidates, demo.scores)
    assert first == second == demo.ranking
    assert first[0].provider_item_id == "fixture-lamp-001"
    assert first[-1].provider_item_id == "fixture-blanket-003"


def test_invalid_score_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OpportunityScoreConfig(formula_version="bad", weights=tuple(
            ScoreWeight(component=component, weight=Decimal("0.1")) for component in ScoreComponent
        ))
    lookup = CONFIG.score.weight_by_component
    lookup[ScoreComponent.URGENCY] = Decimal("1")
    assert CONFIG.score.weight_by_component[ScoreComponent.URGENCY] == Decimal("0.12")
    freshness = CONFIG.buy_now.max_age_by_type
    freshness[EvidenceType.PRICE] = 0
    assert EvidenceType.PRICE not in CONFIG.buy_now.max_age_by_type


def test_compliance_policy_cannot_disable_required_safeguards() -> None:
    with pytest.raises(ValidationError):
        CompliancePolicy(max_price_age_hours=24, max_promotion_age_hours=6,
                         require_affiliate_disclosure=False)
    with pytest.raises(ValidationError):
        type(CONFIG.visual)(max_slide1_headline_characters=24, require_scene_diversity=False)


def test_same_product_same_time_conflicting_prices_are_detected() -> None:
    candidate = _by_item("fixture-lamp-001")
    evidence = ProductEvidence(
        evidence_id="second-price", product_id=candidate.product_id, service=candidate.service,
        evidence_type=EvidenceType.PRICE, source_name="second fixture", source_reference="offline-fixture:2",
        source_field="itemPrice", observed_at=next(item.observed_at for item in candidate.evidence
                                                    if item.evidence_type == EvidenceType.PRICE),
        status=EvidenceStatus.FIXTURE, value_number=Decimal("4700"),
    )
    changed = ProductCandidate.model_validate({**candidate.model_dump(),
        "evidence": (*candidate.evidence, evidence)})
    conflicts = find_conflicting_evidence((changed,))
    assert len(conflicts) == 1
    original = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.PRICE)
    assert set(conflicts[0].evidence_ids) == {original.evidence_id, evidence.evidence_id}
    conflicted_signal_ids = {signal.evidence_id for signal in derive_buy_now_signals(
        changed, as_of=DEMO_AS_OF, max_age_by_type=CONFIG.buy_now.max_age_by_type
    )}
    assert {original.evidence_id, evidence.evidence_id}.isdisjoint(conflicted_signal_ids)


def test_verified_destinations_require_item_bound_exact_url_evidence() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    destination = candidate.offer.affiliate_destination
    with pytest.raises(ValidationError):
        AffiliateDestination(
            destination_id="unbound", service=candidate.service,
            provider_item_id=candidate.provider_item_id, status=DestinationStatus.VERIFIED,
            destination_url="https://unrelated.example/path",
        )
    altered = AffiliateDestination.model_validate({
        **destination.model_dump(), "destination_url": "https://unrelated.example/path",
    })
    offer = AffiliateOffer.model_validate({
        **candidate.offer.model_dump(), "affiliate_destination": altered,
    })
    with pytest.raises(ValidationError):
        ProductCandidate.model_validate({**candidate.model_dump(), "offer": offer})

    proposal, candidates = _approved_test_proposal()
    aged_candidates = []
    for item in candidates:
        aged_evidence = tuple(ProductEvidence.model_validate({
            **record.model_dump(),
            "observed_at": DEMO_AS_OF - timedelta(hours=25)
            if record.evidence_type in (EvidenceType.PRODUCT_DESTINATION, EvidenceType.AFFILIATE_DESTINATION)
            else record.observed_at,
        }) for record in item.evidence)
        aged_candidates.append(ProductCandidate.model_validate({**item.model_dump(), "evidence": aged_evidence}))
    stale_report = evaluate_compliance(
        proposal, tuple(aged_candidates), CONFIG.compliance, as_of=DEMO_AS_OF,
        prior_scene_fingerprints=(),
    )
    assert not _check(stale_report, ComplianceCheckCode.DESTINATION)


def test_candidate_price_check_uses_its_own_evidence_when_ids_collide() -> None:
    proposal, candidates = _approved_test_proposal()
    lamp = next(item for item in candidates if item.provider_item_id == "fixture-lamp-001")
    rug = next(item for item in candidates if item.provider_item_id == "fixture-rug-002")
    lamp_price = next(item for item in lamp.evidence if item.evidence_type == EvidenceType.PRICE)
    rug_identity = next(item for item in rug.evidence if item.evidence_type == EvidenceType.PRODUCT_IDENTITY)
    shared_id = "cross-candidate-collision"
    changed_lamp_evidence = tuple(ProductEvidence.model_validate({
        **item.model_dump(), "evidence_id": shared_id,
    }) if item.evidence_id == lamp_price.evidence_id else item for item in lamp.evidence)
    changed_lamp_offer = AffiliateOffer.model_validate({
        **lamp.offer.model_dump(),
        "price": {**lamp.offer.price.model_dump(), "evidence_id": shared_id},
    })
    changed_lamp = ProductCandidate.model_validate({
        **lamp.model_dump(), "offer": changed_lamp_offer, "evidence": changed_lamp_evidence,
    })
    changed_rug_evidence = tuple(ProductEvidence.model_validate({
        **item.model_dump(), "evidence_id": shared_id,
    }) if item.evidence_id == rug_identity.evidence_id else item for item in rug.evidence)
    changed_rug = ProductCandidate.model_validate({**rug.model_dump(), "evidence": changed_rug_evidence})
    changed_slides = []
    for slide in proposal.carousel.slides:
        labels = tuple(type(label).model_validate({
            **label.model_dump(), "price_evidence_id": shared_id,
        }) if label.product_id == lamp.product_id else label for label in slide.labels)
        changed_slides.append(type(slide).model_validate({**slide.model_dump(), "labels": labels}))
    changed_carousel = type(proposal.carousel).model_validate({
        **proposal.carousel.model_dump(), "slides": tuple(changed_slides),
    })
    changed_proposal = SocialProposal.model_validate({
        **proposal.model_dump(), "carousel": changed_carousel,
    })
    report = evaluate_compliance(changed_proposal, (changed_lamp, changed_rug), CONFIG.compliance,
                                 as_of=DEMO_AS_OF)
    assert _check(report, ComplianceCheckCode.PRICE_FRESHNESS)


def test_visible_item_names_require_verified_matching_identity_evidence() -> None:
    proposal, candidates = _approved_test_proposal()
    lamp = next(item for item in candidates if item.provider_item_id == "fixture-lamp-001")
    changed_name = f"{lamp.name} (unverified)"
    renamed_lamp = ProductCandidate.model_validate({**lamp.model_dump(), "name": changed_name})
    changed_candidates = tuple(renamed_lamp if item.product_id == lamp.product_id else item
                               for item in candidates)
    old_identity = next(item for item in lamp.evidence
                        if item.evidence_type == EvidenceType.PRODUCT_IDENTITY)
    changed_claim = MarketingClaim(
        claim_id="fixture-lamp-identity", product_id=lamp.product_id,
        statement=changed_name, claim_type=EvidenceType.PRODUCT_IDENTITY,
        evidence_ids=(old_identity.evidence_id,),
    )
    slides = []
    for slide in proposal.carousel.slides:
        labels = tuple(type(label).model_validate({
            **label.model_dump(),
            "product_name": changed_name if label.product_id == lamp.product_id else label.product_name,
        }) for label in slide.labels)
        headline = changed_name if slide.kind.value == "overview" else slide.headline
        slides.append(type(slide).model_validate({**slide.model_dump(), "labels": labels, "headline": headline}))
    carousel = type(proposal.carousel).model_validate({
        **proposal.carousel.model_dump(), "slides": tuple(slides),
    })
    renamed_proposal = SocialProposal.model_validate({
        **proposal.model_dump(), "carousel": carousel,
    })
    renamed_proposal = _proposal_with_claims(renamed_proposal, changed_candidates, (changed_claim,))
    report = evaluate_compliance(
        renamed_proposal, changed_candidates, CONFIG.compliance, as_of=DEMO_AS_OF,
        prior_scene_fingerprints=(),
    )
    assert _check(report, ComplianceCheckCode.PRICE_FRESHNESS)
    assert not _check(report, ComplianceCheckCode.CLAIM_EVIDENCE)


def test_product_annotation_claim_must_belong_to_the_annotated_item() -> None:
    proposal, candidates = _approved_test_proposal()
    lamp = next(item for item in candidates if item.provider_item_id == "fixture-lamp-001")
    rug = next(item for item in candidates if item.provider_item_id == "fixture-rug-002")
    sale = next(item for item in lamp.evidence if item.evidence_type == EvidenceType.SALE_END)
    lamp_sale_claim = MarketingClaim(
        claim_id="lamp-sale-end", product_id=lamp.product_id,
        statement=f"販売終了: {sale.valid_until.isoformat()}",
        claim_type=EvidenceType.SALE_END, evidence_ids=(sale.evidence_id,),
    )
    supported = _proposal_with_claims(proposal, candidates, (*proposal.claims, lamp_sale_claim))
    supported_report = evaluate_compliance(
        supported, candidates, CONFIG.compliance, as_of=DEMO_AS_OF, prior_scene_fingerprints=(),
    )
    assert _check(supported_report, ComplianceCheckCode.CLAIM_EVIDENCE)

    slides = []
    for slide in supported.carousel.slides:
        labels = tuple(type(label).model_validate({
            **label.model_dump(),
            "annotation": f"{lamp.name}: {lamp_sale_claim.statement}"
            if label.product_id == rug.product_id and slide.kind.value == "product_detail"
            else label.annotation,
        }) for label in slide.labels)
        slides.append(type(slide).model_validate({**slide.model_dump(), "labels": labels}))
    carousel = type(supported.carousel).model_validate({
        **supported.carousel.model_dump(), "slides": tuple(slides),
    })
    mismatched = SocialProposal.model_validate({**supported.model_dump(), "carousel": carousel})
    report = evaluate_compliance(
        mismatched, candidates, CONFIG.compliance, as_of=DEMO_AS_OF, prior_scene_fingerprints=(),
    )
    assert not _check(report, ComplianceCheckCode.CLAIM_EVIDENCE)


def test_compliance_fails_closed_for_fixture_urls_rights_and_missing_approval() -> None:
    demo = run_offline_demo()
    codes = {item.code for item in demo.compliance.checks if not item.passed}
    assert ComplianceCheckCode.DESTINATION in codes
    assert ComplianceCheckCode.RIGHTS_PROVENANCE in codes
    assert ComplianceCheckCode.CLAIM_EVIDENCE in codes
    assert ComplianceCheckCode.HUMAN_APPROVAL in codes
    assert not demo.compliance.can_publish
    assert demo.compliance.live_publish_authorized is False


def test_repeated_proposal_and_altered_product_asset_fail_compliance() -> None:
    proposal, candidates = _approved_test_proposal()
    digest = proposal_content_digest(proposal, candidates)
    repeated = evaluate_compliance(proposal, candidates, CONFIG.compliance,
                                   as_of=DEMO_AS_OF, seen_proposal_digests=(digest,))
    assert not _check(repeated, ComplianceCheckCode.DUPLICATE_PROPOSAL)
    altered_assets = tuple(VisualAsset.model_validate({
        **asset.model_dump(),
        "product_appearance_altered": asset.kind == VisualAssetKind.PRODUCT,
    }) for asset in proposal.visual_assets)
    altered = SocialProposal.model_validate({**proposal.model_dump(), "visual_assets": altered_assets})
    report = evaluate_compliance(altered, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(report, ComplianceCheckCode.PRODUCT_APPEARANCE)


def test_compliance_requires_disclosure_fresh_price_rights_and_explicit_approval() -> None:
    proposal, candidates = _approved_test_proposal()
    report = evaluate_compliance(proposal, candidates, CONFIG.compliance, as_of=DEMO_AS_OF,
                                 prior_scene_fingerprints=())
    assert report.ready_for_human_approval
    assert not report.approval_valid
    assert not report.can_publish
    decision = ReviewDecision(
        review_id="review-1", draft_id=proposal.proposal_id, trace_id="ECHO-AI-20260928-000001",
        decision=DecisionType.APPROVE, reviewed_at=DEMO_AS_OF,
        reviewer_note=f"Affiliate Phase 0 content SHA-256: {report.proposal_digest}",
    )
    approval = HumanApproval(proposal_id=proposal.proposal_id, review_decision=decision,
                             approved_content_digest=report.proposal_digest)
    approved = evaluate_compliance(proposal, candidates, CONFIG.compliance, as_of=DEMO_AS_OF,
                                   prior_scene_fingerprints=(), approval=approval)
    assert approved.approval_valid and approved.eligible_for_future_publish
    assert not approved.can_publish and approved.live_publish_authorized is False
    variants = tuple(PlatformVariant(
        platform=item.platform, caption="A product note", disclosure_text="PR",
        disclosure_placement=DisclosurePlacement.BODY,
    ) for item in proposal.platform_variants)
    no_disclosure = SocialProposal.model_validate({**proposal.model_dump(), "platform_variants": variants})
    failed = evaluate_compliance(no_disclosure, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(failed, ComplianceCheckCode.DISCLOSURE)
    misplaced_variants = tuple(PlatformVariant(
        platform=item.platform, caption=f"Unverified promotion. PR {proposal.canonical_message}",
        disclosure_text="PR", disclosure_placement=DisclosurePlacement.FIRST_VIEW,
    ) for item in proposal.platform_variants)
    misplaced = SocialProposal.model_validate({**proposal.model_dump(), "platform_variants": misplaced_variants})
    misplaced_report = evaluate_compliance(misplaced, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(misplaced_report, ComplianceCheckCode.DISCLOSURE)
    assert not _check(misplaced_report, ComplianceCheckCode.CLAIM_EVIDENCE)
    appended_variants = tuple(PlatformVariant(
        platform=item.platform, caption=f"PR {proposal.canonical_message} 期間限定でお得",
        disclosure_text="PR", disclosure_placement=DisclosurePlacement.FIRST_VIEW,
    ) for item in proposal.platform_variants)
    appended = SocialProposal.model_validate({**proposal.model_dump(), "platform_variants": appended_variants})
    appended_report = evaluate_compliance(appended, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(appended_report, ComplianceCheckCode.CLAIM_EVIDENCE)
    false_label_variants = tuple(PlatformVariant(
        platform=item.platform, caption=item.caption, disclosure_text="sponsored",
        disclosure_placement=DisclosurePlacement.FIRST_VIEW,
    ) for item in proposal.platform_variants)
    false_label = SocialProposal.model_validate({**proposal.model_dump(), "platform_variants": false_label_variants})
    false_label_report = evaluate_compliance(false_label, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(false_label_report, ComplianceCheckCode.DISCLOSURE)
    stale_candidates = []
    for candidate in candidates:
        evidence = tuple(ProductEvidence.model_validate({
            **item.model_dump(),
            "observed_at": DEMO_AS_OF - timedelta(hours=25) if item.evidence_type == EvidenceType.PRICE
                else item.observed_at,
        }) for item in candidate.evidence)
        stale_candidates.append(ProductCandidate.model_validate({**candidate.model_dump(), "evidence": evidence}))
    stale_report = evaluate_compliance(proposal, tuple(stale_candidates), CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(stale_report, ComplianceCheckCode.PRICE_FRESHNESS)
    assert _check(stale_report, ComplianceCheckCode.RIGHTS_PROVENANCE)


def test_stale_promotion_claim_and_unknown_claim_evidence_fail_closed() -> None:
    proposal, candidates = _approved_test_proposal()
    candidate = candidates[0]
    promotion = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.SALE_END)
    claim = MarketingClaim(claim_id="claim-sale", product_id=candidate.product_id,
                          statement="セール終了間近", claim_type=EvidenceType.SALE_END,
                          evidence_ids=(promotion.evidence_id,))
    with_claim = _proposal_with_claims(proposal, candidates, (*proposal.claims, claim))
    report = evaluate_compliance(with_claim, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(report, ComplianceCheckCode.CLAIM_EVIDENCE)
    assert not _check(report, ComplianceCheckCode.PROMOTION_FRESHNESS)
    unknown_claim = MarketingClaim(claim_id="claim-unknown", product_id=candidate.product_id,
                                   statement="Unsupported claim", claim_type=EvidenceType.OTHER,
                                   evidence_ids=("absent",))
    changed = SocialProposal.model_validate({**proposal.model_dump(), "claims": (unknown_claim,)})
    unknown_report = evaluate_compliance(changed, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(unknown_report, ComplianceCheckCode.CLAIM_EVIDENCE)


def test_freeform_and_wrong_type_claims_fail_but_exact_evidence_rendering_passes() -> None:
    proposal, candidates = _approved_test_proposal()
    candidate = next(item for item in candidates if item.provider_item_id == "fixture-lamp-001")
    sale = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.SALE_END)
    exact_statement = f"販売終了: {sale.valid_until.isoformat()}"
    wrong_type = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.REVIEW_COUNT)
    unsupported = MarketingClaim(
        claim_id="wrong-evidence-kind", product_id=candidate.product_id,
        statement=exact_statement, claim_type=EvidenceType.SALE_END,
        evidence_ids=(wrong_type.evidence_id,),
    )
    wrong_proposal = _proposal_with_claims(proposal, candidates, (*proposal.claims, unsupported))
    wrong_report = evaluate_compliance(wrong_proposal, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(wrong_report, ComplianceCheckCode.CLAIM_EVIDENCE)

    freeform = MarketingClaim(
        claim_id="freeform-sale", product_id=candidate.product_id,
        statement="セール終了はもうすぐです", claim_type=EvidenceType.SALE_END,
        evidence_ids=(sale.evidence_id,),
    )
    freeform_proposal = _proposal_with_claims(proposal, candidates, (*proposal.claims, freeform))
    freeform_report = evaluate_compliance(freeform_proposal, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(freeform_report, ComplianceCheckCode.CLAIM_EVIDENCE)

    supported = MarketingClaim(
        claim_id="supported-sale", product_id=candidate.product_id,
        statement=exact_statement, claim_type=EvidenceType.SALE_END,
        evidence_ids=(sale.evidence_id,),
    )
    supported_proposal = _proposal_with_claims(proposal, candidates, (*proposal.claims, supported))
    supported_report = evaluate_compliance(supported_proposal, candidates, CONFIG.compliance,
                                           as_of=DEMO_AS_OF, prior_scene_fingerprints=())
    assert _check(supported_report, ComplianceCheckCode.CLAIM_EVIDENCE)
    assert _check(supported_report, ComplianceCheckCode.PROMOTION_FRESHNESS)


def test_sale_end_evidence_requires_an_explicit_deadline() -> None:
    with pytest.raises(ValidationError):
        ProductEvidence(
            evidence_id="missing-deadline", product_id="item", service=AffiliateService.RAKUTEN_ICHIBA,
            evidence_type=EvidenceType.SALE_END, source_name="fixture", source_reference="offline-fixture",
            source_field="endTime", observed_at=DEMO_AS_OF, status=EvidenceStatus.FIXTURE,
            value_text="not supplied",
        )


def test_human_approval_is_invalidated_by_content_or_evidence_digest_change() -> None:
    proposal, candidates = _approved_test_proposal()
    original_digest = proposal_content_digest(proposal, candidates)
    changed_proposal = SocialProposal.model_validate({
        **proposal.model_dump(), "canonical_message": proposal.canonical_message + " updated",
    })
    assert proposal_content_digest(changed_proposal, candidates) != original_digest
    decision = ReviewDecision(review_id="review-2", draft_id=proposal.proposal_id,
                              trace_id="ECHO-AI-20260928-000002", decision=DecisionType.APPROVE,
                              reviewed_at=DEMO_AS_OF,
                              reviewer_note=f"Affiliate Phase 0 content SHA-256: {original_digest}")
    approval = HumanApproval(proposal_id=proposal.proposal_id, review_decision=decision,
                             approved_content_digest=original_digest)
    report = evaluate_compliance(changed_proposal, candidates, CONFIG.compliance,
                                 as_of=DEMO_AS_OF, approval=approval)
    assert not report.approval_valid
    with pytest.raises(ValidationError):
        HumanApproval(
            proposal_id=proposal.proposal_id,
            review_decision=decision,
            approved_content_digest=proposal_content_digest(changed_proposal, candidates),
        )
    altered = list(candidates)
    altered[0] = ProductCandidate.model_validate({
        **altered[0].model_dump(), "name": altered[0].name + " revised",
    })
    assert proposal_content_digest(proposal, tuple(altered)) != original_digest


def test_visual_policy_and_product_asset_integrity_are_explicit() -> None:
    demo = run_offline_demo()
    proposal = demo.proposal
    overview = proposal.carousel.slides[0]
    assert overview.headline and len(overview.headline) <= CONFIG.visual.max_slide1_headline_characters
    assert set(overview.arrow_product_ids) == {label.product_id for label in overview.labels}
    assert overview.annotation_color_family == "soft_light_gray"
    assert all(slide.headline is None and len(slide.labels) == 1
               and slide.labels[0].product_name and slide.labels[0].price > 0
               for slide in proposal.carousel.slides[1:])
    assert all(not asset.product_appearance_altered for asset in proposal.visual_assets
               if asset.kind == VisualAssetKind.PRODUCT)
    assert all(asset.rights_status == RightsStatus.UNKNOWN for asset in proposal.visual_assets)
    assert all(asset.official_asset is False and asset.transformations_allowed is False
               for asset in proposal.visual_assets if asset.kind == VisualAssetKind.PRODUCT)
    assert all(not slide.scene.people_included for slide in proposal.carousel.slides)
    assert not validate_scene_diversity(overview.scene, (overview.scene.diversity_fingerprint,))
    assert validate_scene_diversity(overview.scene, ())

    compliant_proposal, candidates = _approved_test_proposal()
    missing_asset_declaration = tuple(VisualAsset.model_validate({
        **asset.model_dump(), "official_asset": None,
    }) if asset.kind == VisualAssetKind.PRODUCT else asset
        for asset in compliant_proposal.visual_assets)
    incomplete_assets = SocialProposal.model_validate({
        **compliant_proposal.model_dump(), "visual_assets": missing_asset_declaration,
    })
    incomplete_report = evaluate_compliance(
        incomplete_assets, candidates, CONFIG.compliance, as_of=DEMO_AS_OF, prior_scene_fingerprints=(),
    )
    assert not _check(incomplete_report, ComplianceCheckCode.RIGHTS_PROVENANCE)


def test_people_require_reason_and_platform_variants_remain_separate() -> None:
    demo = run_offline_demo()
    with pytest.raises(ValidationError):
        LifestyleScene(
            scene_id="invalid", room_geometry="compact", room_size="small", window_placement="east",
            furniture_placement="desk", interior_style="warm", time_of_day="day", lighting="soft",
            color_temperature="neutral", outside_scenery="trees", season="autumn",
            camera_angle="eye-level", usage_context="reading", product_categories=("books",),
            people_included=True,
        )
    assert {item.platform for item in demo.proposal.platform_variants} == set(SocialPlatform)
    assert all(item.disclosure_placement == DisclosurePlacement.FIRST_VIEW
               and "PR" in item.caption for item in demo.proposal.platform_variants)


def test_initial_x_variant_is_required_and_recent_scene_reuse_fails_closed() -> None:
    proposal, candidates = _approved_test_proposal()
    threads_only = SocialProposal.model_validate({
        **proposal.model_dump(),
        "platform_variants": tuple(item for item in proposal.platform_variants
                                    if item.platform == SocialPlatform.THREADS),
    })
    missing_x = evaluate_compliance(threads_only, candidates, CONFIG.compliance, as_of=DEMO_AS_OF)
    assert not _check(missing_x, ComplianceCheckCode.DISCLOSURE)

    overview = proposal.carousel.slides[0]
    repeated = evaluate_compliance(
        proposal, candidates, CONFIG.compliance, as_of=DEMO_AS_OF,
        prior_scene_fingerprints=(overview.scene.diversity_fingerprint,),
    )
    assert not _check(repeated, ComplianceCheckCode.SCENE_DIVERSITY)


def test_carousel_rejects_duplicate_or_wrong_category_scenes() -> None:
    demo = run_offline_demo()
    scene = demo.proposal.carousel.slides[0].scene
    with pytest.raises(ValidationError):
        type(demo.proposal.carousel).model_validate({
            **demo.proposal.carousel.model_dump(),
            "slides": tuple(type(slide).model_validate({**slide.model_dump(), "scene": scene})
                            for slide in demo.proposal.carousel.slides),
        })
    proposal, candidates = _approved_test_proposal()
    slides = list(proposal.carousel.slides)
    detail = slides[1]
    wrong_scene = type(detail.scene).model_validate({
        **detail.scene.model_dump(), "product_categories": ("different-category",),
    })
    slides[1] = type(detail).model_validate({**detail.model_dump(), "scene": wrong_scene})
    wrong_carousel = type(proposal.carousel).model_validate({
        **proposal.carousel.model_dump(), "slides": tuple(slides),
    })
    wrong_category = SocialProposal.model_validate({**proposal.model_dump(), "carousel": wrong_carousel})
    report = evaluate_compliance(
        wrong_category, candidates, CONFIG.compliance, as_of=DEMO_AS_OF,
        prior_scene_fingerprints=(),
    )
    assert not _check(report, ComplianceCheckCode.SCENE_DIVERSITY)


def test_kpi_metrics_use_confirmed_revenue_and_preserve_missing_values() -> None:
    observation = AffiliateKPIObservation(
        observation_id="kpi-1", observed_at=DEMO_AS_OF,
        attribution=AffiliateAttribution(source_service=AffiliateService.RAKUTEN_ICHIBA,
            platform=SocialPlatform.X, account_id="account", post_id="post", proposal_id="proposal",
            product_id="product", product_set_id="set", creative_format="carousel", time_slot="evening"),
        currency="JPY", impressions=1000, clicks=50, orders=5,
        gross_affiliate_revenue=Decimal("1200"), confirmed_revenue=Decimal("900"),
        rejected_or_cancelled_revenue=Decimal("300"), actual_costs=Decimal("250"),
    )
    metrics = calculate_kpis(observation)
    assert metrics.ctr == Decimal("0.05")
    assert metrics.cvr == Decimal("0.1")
    assert metrics.epc == Decimal("18")
    assert metrics.revenue_per_1000_impressions == Decimal("900")
    assert metrics.profit == Decimal("650")
    incomplete = AffiliateKPIObservation(
        observation_id="kpi-2", observed_at=DEMO_AS_OF,
        attribution=AffiliateAttribution(source_service=AffiliateService.RAKUTEN_ICHIBA),
        currency="JPY", impressions=0, clicks=None, orders=None,
    )
    null_metrics = calculate_kpis(incomplete)
    assert null_metrics.ctr is None and null_metrics.cvr is None and null_metrics.epc is None
    assert null_metrics.revenue_per_1000_impressions is None and null_metrics.profit is None


def test_affiliate_demo_cli_is_offline_and_does_not_use_the_database(tmp_path) -> None:
    database = tmp_path / "must-not-exist.db"
    result = runner.invoke(app, ["affiliate", "demo"], env={"ECHO_DATABASE_PATH": str(database)})
    assert result.exit_code == 0, result.stdout
    assert result.exception is None
    assert "OFFLINE" in result.stdout
    assert "No network" in result.stdout
    assert "commercial_attractiveness" in result.stdout
    assert "human_approval=required" in result.stdout
    assert "live_publish_authorized=False" in result.stdout
    assert not database.exists()


def _remediation_evidence(kind: EvidenceType, **values) -> ProductEvidence:
    candidate = _by_item("fixture-blanket-003")
    return ProductEvidence(
        evidence_id="remediation-evidence", product_id=candidate.product_id, service=candidate.service,
        evidence_type=kind, source_name="Synthetic remediation fixture",
        source_reference="offline-fixture:remediation", source_field=kind.value,
        observed_at=DEMO_AS_OF, status=EvidenceStatus.VERIFIED, **values,
    )


def _signals_for_evidence(*records: ProductEvidence):
    candidate = _by_item("fixture-blanket-003")
    changed = ProductCandidate.model_validate({**candidate.model_dump(), "evidence": records})
    return derive_buy_now_signals(changed, as_of=DEMO_AS_OF,
                                 max_age_by_type=CONFIG.buy_now.max_age_by_type)


@pytest.mark.parametrize("kind,values,positive", [
    (EvidenceType.AVAILABILITY, {"value_text": "available"}, True),
    (EvidenceType.AVAILABILITY, {"value_text": "in_stock"}, True),
    (EvidenceType.AVAILABILITY, {"value_text": "unavailable"}, False),
    (EvidenceType.AVAILABILITY, {"value_text": "out_of_stock"}, False),
    (EvidenceType.COUPON, {"value_text": "10%", "valid_until": DEMO_AS_OF + timedelta(hours=1)}, True),
    (EvidenceType.COUPON, {"value_text": "none"}, False),
    (EvidenceType.COUPON, {"value_text": "no_coupon"}, False),
    (EvidenceType.AVAILABILITY, {"value_text": "maybe"}, False),
    (EvidenceType.REVIEW_COUNT, {"value_boolean": True}, False),
    (EvidenceType.DISCOUNT, {"value_number": Decimal("0")}, False),
    (EvidenceType.DISCOUNT, {"value_number": Decimal("-10")}, False),
], ids=[f"SIG-T{number:02d}" for number in range(1, 12)])
def test_sig_value_contract(kind, values, positive) -> None:
    evidence = _remediation_evidence(kind, **values)
    signals = _signals_for_evidence(evidence)
    assert bool(signals) is positive
    if positive:
        assert signals[0].supporting_evidence == evidence
        assert signals[0].normalized_interpretation == "positive"
        assert signals[0].interpretation_basis
        assert signals[0].supporting_evidence.service == evidence.service
        assert signals[0].supporting_evidence.source_reference == evidence.source_reference
        assert signals[0].supporting_evidence.valid_until == evidence.valid_until
        assert signals[0].live_action_authorized is False


@pytest.mark.parametrize("kind,values,positive", [
    (EvidenceType.AVAILABILITY, {"value_boolean": True}, True),
    (EvidenceType.AVAILABILITY, {"value_boolean": False}, False),
    (EvidenceType.AVAILABILITY, {"value_number": Decimal("1")}, False),
    (EvidenceType.COUPON, {"value_text": "not_applicable"}, False),
    (EvidenceType.COUPON, {"value_text": "special deal", "valid_until": DEMO_AS_OF + timedelta(hours=1)}, False),
    (EvidenceType.COUPON, {"value_number": Decimal("500"), "valid_until": DEMO_AS_OF + timedelta(hours=1)}, True),
    (EvidenceType.COUPON, {"value_text": "10%"}, False),
    (EvidenceType.COUPON, {"value_text": "101%", "valid_until": DEMO_AS_OF + timedelta(hours=1)}, False),
    (EvidenceType.POINT_MULTIPLIER, {"value_number": Decimal("1")}, False),
    (EvidenceType.POINT_MULTIPLIER, {"value_number": Decimal("5")}, True),
    (EvidenceType.REVIEW_RATING, {"value_number": Decimal("1")}, False),
    (EvidenceType.REVIEW_RATING, {"value_number": Decimal("4")}, True),
    (EvidenceType.REVIEW_RATING, {"value_number": Decimal("6")}, False),
    (EvidenceType.RANKING, {"value_number": Decimal("11")}, False),
    (EvidenceType.RANKING, {"value_number": Decimal("1")}, True),
    (EvidenceType.REVIEW_COUNT, {"value_number": Decimal("0.5")}, False),
    (EvidenceType.SEASONALITY, {"value_text": "autumn"}, False),
    (EvidenceType.TREND_RELEVANCE, {"value_number": Decimal("0.8")}, True),
    (EvidenceType.TREND_RELEVANCE, {"value_number": Decimal("2")}, False),
    (EvidenceType.SALE_END, {"value_text": (DEMO_AS_OF + timedelta(hours=1)).isoformat(),
                             "valid_until": DEMO_AS_OF + timedelta(hours=1)}, True),
    (EvidenceType.SALE_END, {"value_text": "soon", "valid_until": DEMO_AS_OF + timedelta(hours=1)}, False),
])
def test_sig_typed_positive_boundaries(kind, values, positive) -> None:
    assert bool(_signals_for_evidence(_remediation_evidence(kind, **values))) is positive


@pytest.mark.parametrize("updates", [
    {"valid_until": DEMO_AS_OF},
    {"observed_at": DEMO_AS_OF - timedelta(days=2)},
    {"observed_at": DEMO_AS_OF - timedelta(hours=12)},
    {"observed_at": DEMO_AS_OF + timedelta(seconds=1)},
    {"valid_from": DEMO_AS_OF + timedelta(seconds=1)},
    {"observed_at": DEMO_AS_OF.replace(tzinfo=None)},
], ids=["SIG-T12-expired", "stale", "freshness-expiry-boundary", "future", "not-started", "incomparable-clock"])
def test_sig_time_contract(updates) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    evidence = ProductEvidence.model_validate({**original.model_dump(), **updates})
    assert not _signals_for_evidence(evidence)


def test_sig_t13_conflicted_positive_evidence_is_suppressed() -> None:
    positive = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    negative = ProductEvidence.model_validate({**positive.model_dump(),
        "evidence_id": "negative-stock", "value_boolean": False})
    assert not _signals_for_evidence(positive, negative)


@pytest.mark.parametrize("updates", [
    {"status": EvidenceStatus.UNKNOWN}, {"status": EvidenceStatus.CONFLICTED},
    {"source_name": " "}, {"source_reference": " "}, {"source_field": " "},
])
def test_sig_t14_missing_status_or_provenance_fails_closed(updates) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    assert not _signals_for_evidence(ProductEvidence.model_validate({**original.model_dump(), **updates}))


@pytest.mark.parametrize("kind,values,updates", [
    (EvidenceType.AVAILABILITY, {"value_text": "unavailable"}, {}),
    (EvidenceType.AVAILABILITY, {"value_text": "maybe"}, {}),
    (EvidenceType.COUPON, {"value_text": "none"}, {}),
    (EvidenceType.POINT_MULTIPLIER, {"value_number": Decimal("1")}, {}),
    (EvidenceType.REVIEW_COUNT, {"value_boolean": True}, {}),
    (EvidenceType.PRICE, {"value_number": Decimal("100")}, {}),
    (EvidenceType.AVAILABILITY, {"value_boolean": True}, {"status": EvidenceStatus.UNKNOWN}),
    (EvidenceType.AVAILABILITY, {"value_boolean": True}, {"source_reference": " "}),
])
def test_sig_public_model_rejects_nonpositive_or_ineligible_support(kind, values, updates) -> None:
    original = _remediation_evidence(kind, **values)
    evidence = ProductEvidence.model_validate({**original.model_dump(), **updates})
    with pytest.raises(ValidationError):
        BuyNowSignal(signal_id="direct", product_id=evidence.product_id, evidence_id=evidence.evidence_id,
            evidence_type=evidence.evidence_type, evidence_status=evidence.status,
            observed_at=evidence.observed_at, expires_at=DEMO_AS_OF + timedelta(hours=1),
            supporting_evidence=evidence, interpretation_basis="caller-asserted-positive")


def test_sig_public_model_rejects_forged_expiry_and_retains_valid_support() -> None:
    evidence = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True,
                                    valid_until=DEMO_AS_OF + timedelta(hours=1))
    signal = _signals_for_evidence(evidence)[0]
    assert BuyNowSignal.model_validate(signal.model_dump()) == signal
    for expires_at in (None, DEMO_AS_OF, DEMO_AS_OF + timedelta(hours=2)):
        with pytest.raises(ValidationError):
            BuyNowSignal.model_validate({**signal.model_dump(), "expires_at": expires_at})
    with pytest.raises(ValidationError):
        BuyNowSignal.model_validate({**signal.model_dump(), "interpretation_basis": "caller-asserted-discount"})


def _remediation_score(candidate: ProductCandidate):
    return score_candidate(candidate, CONFIG.score, as_of=DEMO_AS_OF,
                           max_evidence_age=timedelta(hours=CONFIG.scoring_max_evidence_age_hours))


def _score_component(score, component):
    return next(item for item in score.components if item.component == component)


def _candidate_with_features(candidate, features, evidence=None):
    return ProductCandidate.model_validate({**candidate.model_dump(), "score_features": features,
        "evidence": candidate.evidence if evidence is None else evidence})


def test_score_t01_identity_reuse_cannot_max_all_components() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    identity = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.PRODUCT_IDENTITY)
    features = tuple(ScoreFeature(component=component, value=Decimal("1"), evidence_ids=(identity.evidence_id,))
                     for component in ScoreComponent)
    score = _remediation_score(_candidate_with_features(candidate, features))
    assert score.final_score == CONFIG.score.weight_by_component[ScoreComponent.CONTEXTUAL_FIT]
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).value == 0  # SCORE-T09
    assert _score_component(score, ScoreComponent.FRESHNESS).value == 0


@pytest.mark.parametrize("component", [ScoreComponent.COMMERCIAL_ATTRACTIVENESS, ScoreComponent.URGENCY,
                                      ScoreComponent.AFFILIATE_ECONOMICS, ScoreComponent.DEMAND, ScoreComponent.TRUST],
                         ids=["SCORE-T02", "SCORE-T03", "SCORE-T04", "SCORE-T14-demand", "SCORE-T14-trust"])
def test_score_identity_is_not_commercial_support(component) -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    identity = next(item for item in candidate.evidence if item.evidence_type == EvidenceType.PRODUCT_IDENTITY)
    score = _remediation_score(_candidate_with_features(candidate, (
        ScoreFeature(component=component, value=Decimal("1"), evidence_ids=(identity.evidence_id,)),)))
    rejected = _score_component(score, component)
    assert rejected.value == 0 and score.final_score == 0
    assert rejected.validation_basis == "unsupported_component_evidence_type"


def test_score_t05_relevant_price_assessment_explains_support() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("0.8"),
                           evidence_ids=(candidate.offer.price.evidence_id,))
    score = _remediation_score(_candidate_with_features(candidate, (feature,)))
    component = _score_component(score, feature.component)
    assert component.value == Decimal("0.8")
    assert component.weighted_value == component.value * component.weight
    assert component.evidence_ids == feature.evidence_ids
    assert component.evidence_types == (EvidenceType.PRICE,)
    assert component.validation_basis == "eligible_normalized_component_assessment"
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).value == Decimal("0.2")


@pytest.mark.parametrize("updates", [
    {"observed_at": DEMO_AS_OF - timedelta(days=30)}, {"valid_until": DEMO_AS_OF},
    {"observed_at": DEMO_AS_OF + timedelta(seconds=1)}, {"status": EvidenceStatus.CONFLICTED},
    {"status": EvidenceStatus.UNKNOWN}, {"source_reference": " "},
], ids=["SCORE-T06", "expired", "future", "SCORE-T07", "unknown", "missing-provenance"])
def test_score_ineligible_support_contributes_zero(updates) -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    original = next(item for item in candidate.evidence if item.evidence_id == candidate.offer.price.evidence_id)
    changed = ProductEvidence.model_validate({**original.model_dump(), **updates})
    records = tuple(changed if item.evidence_id == changed.evidence_id else item for item in candidate.evidence)
    feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("1"),
                           evidence_ids=(changed.evidence_id,))
    assert _remediation_score(_candidate_with_features(candidate, (feature,), records)).final_score == 0


@pytest.mark.parametrize("cite_both", [False, True])
def test_score_t08_contradictory_price_suppresses_selected_and_combined_support(cite_both) -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    price = next(item for item in candidate.evidence if item.evidence_id == candidate.offer.price.evidence_id)
    contradictory = ProductEvidence.model_validate({**price.model_dump(), "evidence_id": "second-current-price",
                                                    "value_number": price.value_number + 1})
    cited = (price.evidence_id, contradictory.evidence_id) if cite_both else (price.evidence_id,)
    feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("1"), evidence_ids=cited)
    score = _remediation_score(_candidate_with_features(candidate, (feature,), (*candidate.evidence, contradictory)))
    assert score.final_score == 0
    assert _score_component(score, feature.component).validation_basis == "conflicted_evidence"


def test_score_t10_confidence_requires_verified_contributing_factual_components() -> None:
    strong = _by_item("fixture-lamp-001", verified=True)
    score = _remediation_score(strong)
    confidence = _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE)
    assert confidence.value == 1
    assert score.final_score > Decimal("0.8")
    assert confidence.validation_basis == "derived_verified_factual_component_coverage:5/5"
    by_id = {item.evidence_id: item for item in strong.evidence}
    assert all(by_id[eid].status == EvidenceStatus.VERIFIED
               and by_id[eid].evidence_type != EvidenceType.PRODUCT_IDENTITY for eid in confidence.evidence_ids)
    assert _score_component(_remediation_score(_by_item("fixture-lamp-001")),
                            ScoreComponent.EVIDENCE_CONFIDENCE).value == 0  # SCORE-T12 fixture != verified


def test_score_t11_missing_evidence_and_caller_confidence_are_not_support() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    features = (
        ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("1"), evidence_ids=("absent",)),
        ScoreFeature(component=ScoreComponent.EVIDENCE_CONFIDENCE, value=Decimal("1"), evidence_ids=("absent",)),
    )
    score = _remediation_score(_candidate_with_features(candidate, features))
    assert score.final_score == 0
    assert _score_component(score, ScoreComponent.COMMERCIAL_ATTRACTIVENESS).validation_basis == "missing_evidence"


def test_score_mixed_citations_zero_the_whole_feature_without_selective_filtering() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    price_id = candidate.offer.price.evidence_id
    identity_id = next(item.evidence_id for item in candidate.evidence if item.evidence_type == EvidenceType.PRODUCT_IDENTITY)
    for invalid_id in (identity_id, "absent"):
        feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS,
            value=Decimal("1"), evidence_ids=(price_id, invalid_id))
        score = _remediation_score(_candidate_with_features(candidate, (feature,)))
        assert score.final_score == 0


def test_score_t12_unused_verified_evidence_does_not_upgrade_weak_assessment() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    price = next(item for item in candidate.evidence if item.evidence_id == candidate.offer.price.evidence_id)
    features = (ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("0.1"),
                             evidence_ids=(price.evidence_id,)),)
    score = _remediation_score(_candidate_with_features(candidate, features))
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).value == Decimal("0.2")
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).evidence_ids == (price.evidence_id,)


def test_score_t13_reversed_input_order_and_tied_rankings_are_deterministic() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    reversed_features = tuple(ScoreFeature.model_validate({**feature.model_dump(),
        "evidence_ids": tuple(reversed(feature.evidence_ids))}) for feature in reversed(candidate.score_features))
    reverse = _candidate_with_features(candidate, reversed_features, tuple(reversed(candidate.evidence)))
    assert _remediation_score(candidate) == _remediation_score(reverse)
    candidates = tuple(_candidate_with_features(item, ()) for item in sample_rakuten_candidates())
    scores = tuple(_remediation_score(item) for item in candidates)
    assert rank_candidates(candidates, scores) == rank_candidates(tuple(reversed(candidates)), tuple(reversed(scores)))
    assert tuple(item.product_id for item in rank_candidates(candidates, scores)) == tuple(sorted(item.product_id for item in candidates))


def test_score_t15_legitimate_verified_ranking_remains_useful() -> None:
    candidates = tuple(_by_item(item.provider_item_id, verified=True) for item in sample_rakuten_candidates())
    scores = tuple(_remediation_score(item) for item in candidates)
    ranking = rank_candidates(candidates, scores)
    assert ranking[0].provider_item_id == "fixture-lamp-001"
    assert ranking[-1].provider_item_id == "fixture-blanket-003"


def test_score_zero_weight_assessment_cannot_supply_confidence_or_freshness() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("1"),
                           evidence_ids=(candidate.offer.price.evidence_id,))
    config = OpportunityScoreConfig(formula_version="zero-price-weight", weights=tuple(
        ScoreWeight(component=component, weight=Decimal("1") if component == ScoreComponent.EVIDENCE_CONFIDENCE else Decimal("0"))
        for component in ScoreComponent))
    score = score_candidate(_candidate_with_features(candidate, (feature,)), config, as_of=DEMO_AS_OF,
                            max_evidence_age=timedelta(hours=168))
    assert score.final_score == 0


def _temporal_time(hour):
    return DEMO_AS_OF.replace(hour=0) + timedelta(hours=hour)


@pytest.mark.parametrize("construction", ["direct", "model_validate", "json"])
@pytest.mark.parametrize("start,expiry,accepted", [
    (12, 11, False), (12, 12, False), (12, 13, True),
    (None, 10, False), (None, 11, True), (12, 16, False),
    (12, 15, True), (9, 11, True), (9, 10, False),
], ids=["SIG2-T01", "SIG2-T02", "SIG2-T03", "SIG2-T04", "SIG2-T05",
        "SIG2-T06", "SIG2-T07-exclusive-end", "SIG2-T08", "observed-floor"])
def test_sig2_public_nonempty_applicability_interval(construction, start, expiry, accepted) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    evidence = ProductEvidence.model_validate({**original.model_dump(),
        "observed_at": _temporal_time(10),
        "valid_from": _temporal_time(start) if start is not None else None,
        "valid_until": _temporal_time(15)})
    payload = dict(signal_id="temporal-signal", product_id=evidence.product_id,
        evidence_id=evidence.evidence_id, evidence_type=evidence.evidence_type,
        evidence_status=evidence.status, observed_at=evidence.observed_at,
        expires_at=_temporal_time(expiry), supporting_evidence=evidence,
        interpretation_basis="explicit_availability_boolean")

    def construct():
        if construction == "direct":
            return BuyNowSignal(**payload)
        if construction == "model_validate":
            return BuyNowSignal.model_validate(payload)
        import json
        return BuyNowSignal.model_validate_json(json.dumps({**payload,
            "evidence_type": evidence.evidence_type.value, "evidence_status": evidence.status.value,
            "observed_at": evidence.observed_at.isoformat(),
            "expires_at": payload["expires_at"].isoformat(),
            "supporting_evidence": evidence.model_dump(mode="json")}))

    if accepted:
        signal = construct()
        assert signal.supporting_evidence == evidence
        assert signal.expires_at == _temporal_time(expiry)
    else:
        with pytest.raises(ValidationError):
            construct()


@pytest.mark.parametrize("hour,accepted", [(9, False), (11, False), (12, True),
                                            (13, True), (15, False), (16, False)],
                         ids=["future-observation", "SIG2-T12", "inclusive-start",
                              "SIG2-T13", "SIG2-T14-at-end", "SIG2-T14-after-end"])
def test_sig2_generator_start_and_exclusive_end(hour, accepted) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    evidence = ProductEvidence.model_validate({**original.model_dump(), "observed_at": _temporal_time(10),
        "valid_from": _temporal_time(12), "valid_until": _temporal_time(15)})
    candidate = _by_item("fixture-blanket-003")
    candidate = ProductCandidate.model_validate({**candidate.model_dump(), "evidence": (evidence,)})
    signals = derive_buy_now_signals(candidate, as_of=_temporal_time(hour),
                                    max_age_by_type=CONFIG.buy_now.max_age_by_type)
    assert bool(signals) is accepted
    if accepted:
        assert signals[0].expires_at == evidence.valid_until
        assert signals[0].supporting_evidence == evidence  # SIG2-T11


@pytest.mark.parametrize("hour,accepted", [(21.5, True), (22, False), (23, False)])
def test_sig2_generator_freshness_expiry_is_exclusive(hour, accepted) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    evidence = ProductEvidence.model_validate({**original.model_dump(), "observed_at": _temporal_time(10),
                                               "valid_from": _temporal_time(12)})
    candidate = _by_item("fixture-blanket-003")
    candidate = ProductCandidate.model_validate({**candidate.model_dump(), "evidence": (evidence,)})
    signals = derive_buy_now_signals(candidate, as_of=_temporal_time(hour),
                                    max_age_by_type=CONFIG.buy_now.max_age_by_type)
    assert bool(signals) is accepted
    if accepted:
        assert signals[0].expires_at == _temporal_time(22)


@pytest.mark.parametrize("end", [_temporal_time(11), _temporal_time(12),
                                  _temporal_time(15).replace(tzinfo=None)])
def test_sig2_evidence_rejects_reversed_zero_or_incomparable_window(end) -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    with pytest.raises(ValidationError):
        ProductEvidence.model_validate({**original.model_dump(),
                                        "valid_from": _temporal_time(12), "valid_until": end})


def test_sig2_late_observation_is_historical_but_cannot_create_a_live_interval() -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    evidence = ProductEvidence.model_validate({**original.model_dump(), "observed_at": _temporal_time(16),
        "valid_from": _temporal_time(12), "valid_until": _temporal_time(15)})
    with pytest.raises(ValidationError):
        BuyNowSignal(signal_id="late", product_id=evidence.product_id, evidence_id=evidence.evidence_id,
            evidence_type=evidence.evidence_type, evidence_status=evidence.status,
            observed_at=evidence.observed_at, expires_at=_temporal_time(17), supporting_evidence=evidence,
            interpretation_basis="explicit_availability_boolean")


def _temporal_price(evidence_id, amount, *, observed=10, start=9, end=13):
    candidate = _by_item("fixture-lamp-001", verified=True)
    original = next(item for item in candidate.evidence if item.evidence_id == candidate.offer.price.evidence_id)
    return ProductEvidence.model_validate({**original.model_dump(), "evidence_id": evidence_id,
        "value_number": Decimal(amount), "observed_at": _temporal_time(observed),
        "valid_from": _temporal_time(start) if start is not None else None,
        "valid_until": _temporal_time(end) if end is not None else None})


def _temporal_candidate(records, *, chosen=0, cited=None, base=None):
    candidate = base or _by_item("fixture-lamp-001", verified=True)
    quote = {**candidate.offer.price.model_dump(), "evidence_id": records[chosen].evidence_id,
             "amount": records[chosen].value_number}
    remaining = tuple(item for item in candidate.evidence if item.evidence_type != EvidenceType.PRICE)
    feature = ScoreFeature(component=ScoreComponent.COMMERCIAL_ATTRACTIVENESS, value=Decimal("1"),
        evidence_ids=cited if cited is not None else (records[chosen].evidence_id,))
    return ProductCandidate.model_validate({**candidate.model_dump(),
        "offer": {**candidate.offer.model_dump(), "price": quote},
        "evidence": (*remaining, *records), "score_features": (feature,)})


def _temporal_score(candidate, *, as_of=DEMO_AS_OF, evidence_candidates=()):
    return score_candidate(candidate, CONFIG.score, as_of=as_of, max_evidence_age=timedelta(hours=168),
                           evidence_candidates=evidence_candidates)


def _current_conflicts(*candidates, as_of=DEMO_AS_OF):
    return find_conflicting_evidence(candidates, as_of=as_of, max_age=timedelta(hours=168))


@pytest.mark.parametrize("cite_both", [False, True])
def test_score2_t01_t02_t03_overlapping_different_observations_suppress_every_score_use(cite_both) -> None:
    records = (_temporal_price("price-a", "1000"), _temporal_price("price-b", "2000", observed=11))
    cited = tuple(item.evidence_id for item in records) if cite_both else (records[0].evidence_id,)
    candidate = _temporal_candidate(records, cited=cited)
    conflicts = _current_conflicts(candidate)
    assert len(conflicts) == 1 and conflicts[0].evidence_ids == ("price-a", "price-b")
    score = _temporal_score(candidate)
    component = _score_component(score, ScoreComponent.COMMERCIAL_ATTRACTIVENESS)
    assert component.value == 0 and component.validation_basis == "conflicted_evidence"
    assert score.final_score == 0
    for kind in (ScoreComponent.EVIDENCE_CONFIDENCE, ScoreComponent.FRESHNESS):
        assert _score_component(score, kind).value == 0
        assert _score_component(score, kind).evidence_ids == ()


def test_score2_t04_t07_equivalent_decimal_prices_do_not_false_conflict() -> None:
    candidate = _temporal_candidate((_temporal_price("price-a", "1000"),
        _temporal_price("price-b", "1000.00", observed=11)))
    assert not _current_conflicts(candidate)
    score = _temporal_score(candidate)
    assert _score_component(score, ScoreComponent.COMMERCIAL_ATTRACTIVENESS).value == 1
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).value == Decimal("0.2")


@pytest.mark.parametrize("first_end", [10.5, 11], ids=["SCORE2-T05-gap", "SCORE2-T06-touching"])
def test_score2_nonoverlap_succession_remains_usable_at_inclusive_start(first_end) -> None:
    records = (_temporal_price("price-a", "1000", end=first_end),
               _temporal_price("price-b", "2000", observed=11, start=11))
    candidate = _temporal_candidate(records, chosen=1)
    assert not find_conflicting_evidence((candidate,))
    assert not _current_conflicts(candidate, as_of=_temporal_time(11))
    assert _temporal_score(candidate, as_of=_temporal_time(11)).final_score > 0


def test_score2_t08_different_products_do_not_conflict() -> None:
    first = _temporal_candidate((_temporal_price("price-a", "1000"),))
    rug = _by_item("fixture-rug-002", verified=True)
    other = ProductEvidence.model_validate({**_temporal_price("price-b", "2000").model_dump(),
                                           "product_id": rug.product_id})
    second = _temporal_candidate((other,), base=rug)
    assert not _current_conflicts(first, second)
    assert _temporal_score(first).final_score > 0


def test_score2_t09_unrelated_families_do_not_conflict() -> None:
    price = _temporal_price("price-a", "1000")
    discount = ProductEvidence.model_validate({**price.model_dump(), "evidence_id": "discount-a",
                                              "evidence_type": EvidenceType.DISCOUNT, "value_number": Decimal("20")})
    candidate = _temporal_candidate((price, discount))
    assert not _current_conflicts(candidate)
    assert _temporal_score(candidate).final_score > 0


def test_score2_t10_stale_unbounded_history_cannot_poison_current_price() -> None:
    old = _temporal_price("old-price", "2000", observed=-200, start=None, end=None)
    current = _temporal_price("price-a", "1000")
    candidate = _temporal_candidate((old, current), chosen=1)
    assert not _current_conflicts(candidate)
    score = _temporal_score(candidate)
    assert score.final_score > 0
    assert _score_component(score, ScoreComponent.FRESHNESS).evidence_ids == (current.evidence_id,)


@pytest.mark.parametrize("start", [9, 13], ids=["future-observation", "future-effective-start"])
def test_score2_t11_future_evidence_cannot_poison_current_price(start) -> None:
    current = _temporal_price("price-a", "1000")
    future = _temporal_price("future-price", "2000", observed=13, start=start, end=15)
    candidate = _temporal_candidate((current, future))
    assert not _current_conflicts(candidate)
    assert _temporal_score(candidate).final_score > 0


def test_score2_t12_overlapping_offer_records_share_one_conflict_rule() -> None:
    first = _temporal_price("price-a", "1000")
    second = _temporal_price("price-b", "2000", observed=11)
    separate_offers = (_temporal_candidate((first,)), _temporal_candidate((second,)))
    assert _current_conflicts(*separate_offers)[0].evidence_ids == ("price-a", "price-b")
    for inventory in (separate_offers, tuple(reversed(separate_offers))):
        for offer in separate_offers:
            score = _temporal_score(offer, evidence_candidates=inventory)
            assert score.final_score == 0
            assert _score_component(score, ScoreComponent.COMMERCIAL_ATTRACTIVENESS).validation_basis == "conflicted_evidence"
            for kind in (ScoreComponent.EVIDENCE_CONFIDENCE, ScoreComponent.FRESHNESS):
                assert _score_component(score, kind).value == 0
                assert _score_component(score, kind).evidence_ids == ()
    assert _temporal_score(separate_offers[0], evidence_candidates=(separate_offers[1],)).final_score == 0


def test_score2_t13_historical_third_record_does_not_hide_current_conflict() -> None:
    records = (_temporal_price("price-a", "1000"), _temporal_price("price-b", "2000", observed=11),
               _temporal_price("historical", "3000", observed=4, start=4, end=5))
    candidate = _temporal_candidate(records)
    assert _current_conflicts(candidate)[0].evidence_ids == ("price-a", "price-b")
    assert _temporal_score(candidate).final_score == 0


def test_score2_t14_resolved_historical_conflict_does_not_poison_current_price() -> None:
    records = (_temporal_price("old-a", "1000", observed=4, start=4, end=5),
               _temporal_price("old-b", "2000", observed=4.5, start=4, end=5),
               _temporal_price("price-a", "3000"))
    candidate = _temporal_candidate(records, chosen=2)
    assert find_conflicting_evidence((candidate,))[0].evidence_ids == ("old-a", "old-b")
    assert not _current_conflicts(candidate)
    assert _temporal_score(candidate).final_score > 0


def test_score2_t15_conflict_and_score_are_stable_under_record_and_offer_reversal() -> None:
    records = (_temporal_price("price-a", "1000"), _temporal_price("price-b", "2000", observed=11),
               _temporal_price("price-c", "1000", observed=9.5))
    candidate = _temporal_candidate(records)
    reverse = ProductCandidate.model_validate({**candidate.model_dump(), "evidence": tuple(reversed(candidate.evidence))})
    assert _current_conflicts(candidate) == _current_conflicts(reverse)
    assert _temporal_score(candidate) == _temporal_score(reverse)
    offers = tuple(_temporal_candidate((record,)) for record in records)
    assert _current_conflicts(*offers) == _current_conflicts(*reversed(offers))


def test_score2_t16_uncontested_high_quality_candidate_retains_positive_ranking() -> None:
    candidate = _by_item("fixture-lamp-001", verified=True)
    score = _temporal_score(candidate)
    assert score.final_score > Decimal("0.8")
    assert _score_component(score, ScoreComponent.EVIDENCE_CONFIDENCE).value == 1


@pytest.mark.parametrize("second_value", [" available ", "IN_STOCK", True])
def test_sig2_normalized_availability_duplicates_preserve_original_evidence(second_value) -> None:
    first = _remediation_evidence(EvidenceType.AVAILABILITY, value_text="available")
    second = ProductEvidence.model_validate({**first.model_dump(), "evidence_id": "duplicate-availability",
        "observed_at": DEMO_AS_OF - timedelta(hours=1), "value_text": second_value if isinstance(second_value, str) else None,
        "value_boolean": second_value if isinstance(second_value, bool) else None})
    signals = _signals_for_evidence(first, second)
    assert len(signals) == 2
    assert {signal.supporting_evidence for signal in signals} == {first, second}


def test_sig2_historical_conflict_does_not_poison_current_signal() -> None:
    first = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    old = ProductEvidence.model_validate({**first.model_dump(), "evidence_id": "old-negative",
        "observed_at": DEMO_AS_OF - timedelta(days=2), "value_boolean": False})
    signals = _signals_for_evidence(first, old)
    assert len(signals) == 1 and signals[0].evidence_id == first.evidence_id


def test_sig2_overlapping_current_contradiction_uses_shared_conflict_suppression() -> None:
    original = _remediation_evidence(EvidenceType.AVAILABILITY, value_boolean=True)
    first = ProductEvidence.model_validate({**original.model_dump(),
        "observed_at": DEMO_AS_OF - timedelta(hours=2), "valid_from": DEMO_AS_OF - timedelta(hours=3),
        "valid_until": DEMO_AS_OF + timedelta(hours=1)})
    second = ProductEvidence.model_validate({**first.model_dump(), "evidence_id": "negative-stock-later",
        "observed_at": DEMO_AS_OF - timedelta(hours=1), "value_boolean": False})
    assert not _signals_for_evidence(first, second)
    assert not _signals_for_evidence(second, first)


@pytest.mark.parametrize("kind,first_values,second_values", [
    (EvidenceType.COUPON, {"value_text": "10%"}, {"value_text": "10.0%"}),
    (EvidenceType.SALE_END, {"value_text": (DEMO_AS_OF + timedelta(hours=1)).isoformat()},
        {"value_text": (DEMO_AS_OF + timedelta(hours=1)).astimezone(timezone(timedelta(hours=9))).isoformat()}),
])
def test_sig2_equivalent_typed_coupon_and_deadline_values_do_not_false_conflict(kind, first_values, second_values) -> None:
    first = _remediation_evidence(kind, valid_until=DEMO_AS_OF + timedelta(hours=1), **first_values)
    second = ProductEvidence.model_validate({**first.model_dump(), **second_values,
        "evidence_id": "equivalent-record", "observed_at": DEMO_AS_OF - timedelta(minutes=30)})
    assert len(_signals_for_evidence(first, second)) == 2


def test_score2_duplicate_record_identity_is_deduplicated_or_rejected_consistently() -> None:
    first = _temporal_price("same-id", "1000")
    candidate = _temporal_candidate((first,))
    assert not _current_conflicts(candidate, candidate)
    second = _temporal_price("same-id", "2000", observed=11)
    other = _temporal_candidate((second,))
    for offers in ((candidate, other), (other, candidate)):
        with pytest.raises(ValueError, match="one evidence ID"):
            _current_conflicts(*offers)


def _temporal_other_service(candidate):
    data = candidate.model_dump()
    data["service"] = AffiliateService.RAKUYOKO
    data["offer"]["service"] = AffiliateService.RAKUYOKO
    for destination in (data["offer"]["product_destination"], data["offer"]["affiliate_destination"]):
        destination["service"] = AffiliateService.RAKUYOKO
    for evidence in data["evidence"]:
        evidence["service"] = AffiliateService.RAKUYOKO
    return ProductCandidate.model_validate(data)


def test_score2_service_separated_conflicts_have_a_total_deterministic_order() -> None:
    first = _temporal_candidate((_temporal_price("a-price", "1000"),
                                _temporal_price("b-price", "2000", observed=11)))
    second = _temporal_other_service(_temporal_candidate((_temporal_price("c-price", "1000"),
                                _temporal_price("d-price", "2000", observed=11))))
    forward = _current_conflicts(first, second)
    assert {item.evidence_ids for item in forward} == {("a-price", "b-price"), ("c-price", "d-price")}
    assert forward == _current_conflicts(second, first)


@pytest.mark.parametrize("other_kind", ["product", "service"])
def test_score2_inventory_conflicts_do_not_leak_across_subjects_or_services(other_kind) -> None:
    current = _temporal_price("price-a", "1000")
    first = _temporal_candidate((current,))
    records = (_temporal_price("price-a", "2000"), _temporal_price("price-b", "3000", observed=11))
    if other_kind == "service":
        other = _temporal_other_service(_temporal_candidate(records))
    else:
        rug = _by_item("fixture-rug-002", verified=True)
        records = tuple(ProductEvidence.model_validate({**item.model_dump(), "product_id": rug.product_id})
                        for item in records)
        other = _temporal_candidate(records, base=rug)
    assert _current_conflicts(other)
    assert _temporal_score(first, evidence_candidates=(other,)) == _temporal_score(first)


@pytest.mark.parametrize("other_window", ["stale", "future", "touching", "equivalent"])
def test_score2_separate_offer_context_preserves_usable_temporal_succession(other_window) -> None:
    first = _temporal_candidate((_temporal_price("price-a", "1000"),))
    if other_window == "stale":
        record = _temporal_price("price-b", "2000", observed=-200, start=None, end=None)
    elif other_window == "future":
        record = _temporal_price("price-b", "2000", observed=11, start=13, end=15)
    elif other_window == "touching":
        record = _temporal_price("price-b", "2000", observed=8, start=8, end=9)
    else:
        record = _temporal_price("price-b", "1000.00", observed=11)
    other = _temporal_candidate((record,))
    assert _temporal_score(first, evidence_candidates=(other,)).final_score > 0


@pytest.mark.parametrize("other_family", [EvidenceType.DISCOUNT, EvidenceType.COUPON])
def test_score2_sibling_conflict_cannot_suppress_an_unrelated_family_with_reused_id(other_family) -> None:
    first = _temporal_candidate((_temporal_price("price-a", "1000"),))
    promotion = ProductEvidence.model_validate({**_temporal_price("price-a", "20").model_dump(),
                                              "evidence_type": other_family})
    incompatible = ProductEvidence.model_validate({**promotion.model_dump(),
                                                   "evidence_id": "promotion-b", "value_number": Decimal("10")})
    other = _temporal_candidate((_temporal_price("sibling-price", "1000", observed=11),
                                promotion, incompatible))
    conflicts = _current_conflicts(first, other)
    assert len(conflicts) == 1 and conflicts[0].evidence_type == other_family
    assert conflicts[0].evidence_ids == ("price-a", "promotion-b")
    for inventory in ((first, other), (other, first)):
        assert _temporal_score(first, evidence_candidates=inventory) == _temporal_score(first)
