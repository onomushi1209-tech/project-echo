"""Stage 6A identity/copy/rights/credit contracts; synthetic transport only."""

from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from echo.models.affiliate import AffiliateService, EvidenceType
from echo.models.affiliate_assets import AssetEligibility, AssetSourceClass, BoundingRegion, RightsProvenance, RightsSafeVisualPlan
from echo.models.affiliate_content import ContextHeadline, WebServiceCredit
from echo.models.affiliate_visual import ComplianceCheckCode, HumanApproval, SocialProposal
from echo.models.discovery import DiscoveryQuery
from echo.models.enums import DecisionType
from echo.models.review import ReviewDecision
from echo.monetization.asset_policy import asset_eligibility, visual_render_ready
from echo.monetization.compliance import evaluate_compliance
from echo.monetization.config import load_phase0_config
from echo.monetization.content_proposal import build_content_proposal
from echo.monetization.discovery import discover_products
from echo.monetization.fixtures import DEMO_AS_OF
from echo.monetization.rakuten import ENDPOINTS, RakutenDiscoveryProvider
from echo.monetization.transport import HttpResponse
from echo.monetization.visuals import proposal_content_digest

LONG_NAME = "Synthetic desk lamp original model with full colour and connector qualifiers " * 2


@pytest.fixture
def content_case():
    data = json.loads((Path(__file__).parent / "fixtures/affiliate/ranked_hydration.json").read_text(encoding="utf-8"))
    for page in data.values():
        page["items"][0]["itemName"] = LONG_NAME
    def sender(request, timeout, max_bytes):
        source = next(s for s, endpoint in ENDPOINTS.items() if endpoint == request.endpoint)
        parameters = dict(request.parameters)
        key = source.value + ":" + parameters.get("page", "1")
        if parameters.get("itemCode"):
            key += ":" + parameters["itemCode"]
        return HttpResponse(200, json.dumps(data[key]).encode())
    adapter = RakutenDiscoveryProvider.live(live_readonly=True, environment={
        "ECHO_RAKUTEN_LIVE_READONLY":"1", "RAKUTEN_APPLICATION_ID":"SYNTHETIC_APP",
        "RAKUTEN_ACCESS_KEY":"SYNTHETIC_ACCESS", "RAKUTEN_AFFILIATE_ID":"SYNTHETIC_AFFILIATE"},
        sender=sender, sleeper=lambda delay: None)
    result = discover_products(adapter, (DiscoveryQuery(source="ranking", category="lighting", lifestyle_context="reading corner"),), as_of=DEMO_AS_OF)
    assert len(result.selected) == len(result.proposals) == 1
    return result.selected, result.observations, result.proposals[0]


def report(proposal, candidates, *, at=DEMO_AS_OF, approval=None):
    return evaluate_compliance(proposal,candidates,load_phase0_config().compliance,as_of=at,approval=approval)


def passed(result, code):
    return next(c.passed for c in result.checks if c.code == code)


def reviewed_asset(candidate, **updates):
    values = dict(asset_id="asset-"+candidate.product_id, product_id=candidate.product_id, service=candidate.service,
        provider_item_id=candidate.provider_item_id, source_class=AssetSourceClass.AFFILIATE_PORTAL,
        source_reference="synthetic-manual-portal-asset", acquisition_method="manual_official_affiliate_portal",
        download_source_class=AssetSourceClass.AFFILIATE_PORTAL, rights_basis="synthetic policy review",
        rights_proof_reference="synthetic-review-record", asset_content_sha256="a"*64, local_asset_available=True,
        crop_permission=False, resize_permission=True, overlay_permission=False, context_composition_permission=True,
        contains_person=False, creative_photography=False, distinctive_design=False,
        manual_reviewer="synthetic-reviewer", reviewed_at=DEMO_AS_OF, rights_valid_until=DEMO_AS_OF+timedelta(days=1))
    return RightsProvenance(**{**values,**updates})


def test_ast_t01_api_reference_does_not_grant_rights(content_case):
    candidates, _, proposal = content_case
    asset = proposal.visual_plan.assets[0]
    assert asset_eligibility(asset,as_of=DEMO_AS_OF) == AssetEligibility.API_REFERENCE_ONLY
    assert not visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF)
    forged = asset.model_copy(update={"local_asset_available":True,"asset_content_sha256":"a"*64,"rights_basis":"claim"})
    assert asset_eligibility(forged,as_of=DEMO_AS_OF) == AssetEligibility.API_REFERENCE_ONLY


def test_ast_t02_unreviewed_portal_asset_blocks_render(content_case):
    candidates, observations, _ = content_case
    asset=reviewed_asset(candidates[0],manual_reviewer=None,reviewed_at=None)
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(asset,))
    assert asset_eligibility(asset,as_of=DEMO_AS_OF) == AssetEligibility.AFFILIATE_PORTAL_ASSET_UNVERIFIED
    assert not visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF)


def test_ast_t03_attested_whole_portal_asset_allows_level1_plan(content_case):
    candidates, observations, _ = content_case
    asset=reviewed_asset(candidates[0])
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(asset,))
    assert asset_eligibility(asset,as_of=DEMO_AS_OF) == AssetEligibility.AFFILIATE_PORTAL_ASSET_ELIGIBLE
    assert proposal.visual_plan.visual_plan_ready and visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF)
    assert not proposal.visual_plan.crop_requested and not proposal.visual_plan.direct_overlay_requested
    assert all(r.preserve_full_image and r.preserve_aspect_ratio for s in proposal.visual_plan.slides for r in s.product_regions)
    # This is a metadata attestation, not actual intake/render or generated-background rights.
    assert not passed(report(proposal,candidates),ComplianceCheckCode.RIGHTS_PROVENANCE)


@pytest.mark.parametrize("kind",["annotation","headline","canonical_product_name","price","arrow"])
def test_ast_t04_protected_image_rejects_every_overlay_kind(content_case,kind):
    _,_,proposal=content_case
    data=proposal.visual_plan.slides[0].model_dump()
    if kind=="arrow":
        data["arrow_regions"][0]["bounds"]=data["product_regions"][0]["bounds"]
    else:
        data["text_regions"][0].update(kind=kind,bounds=data["product_regions"][0]["bounds"])
    with pytest.raises(ValidationError):
        type(proposal.visual_plan.slides[0]).model_validate(data)


def test_ast_t05_all_text_and_arrows_outside_all_protected_regions(content_case):
    _,_,proposal=content_case
    for slide in proposal.visual_plan.slides:
        assert all(not t.bounds.intersects(z) for t in (*slide.text_regions,*slide.arrow_regions) for z in slide.no_overlay_zones)
    assert SocialProposal.model_validate(proposal.model_dump()) == proposal


@pytest.mark.parametrize("field",["crop_requested","direct_overlay_requested","product_redraw_requested","product_appearance_altered"])
def test_ast_t06_t07_crop_overlay_redraw_appearance_rejected(content_case,field):
    _,_,proposal=content_case
    with pytest.raises(ValidationError):
        RightsSafeVisualPlan.model_validate({**proposal.visual_plan.model_dump(),field:True})


@pytest.mark.parametrize("field",["contains_person","creative_photography","distinctive_design"])
def test_ast_t08_unknown_categories_require_manual_review_and_restricted_portal_rejects(content_case,field):
    candidates,_,_=content_case
    assert asset_eligibility(reviewed_asset(candidates[0],**{field:None}),as_of=DEMO_AS_OF) == AssetEligibility.AFFILIATE_PORTAL_ASSET_MANUAL_REVIEW_REQUIRED
    assert asset_eligibility(reviewed_asset(candidates[0],**{field:True}),as_of=DEMO_AS_OF) == AssetEligibility.REJECTED


def test_copy_t01_t05_supported_name_price_disclosure_content_ready(content_case):
    candidates,_,proposal=content_case
    result=report(proposal,candidates)
    assert proposal.platform_variants[0].caption.startswith("PR ")
    assert passed(result,ComplianceCheckCode.DISCLOSURE) and passed(result,ComplianceCheckCode.PRICE_FRESHNESS)
    assert result.content_ready and not result.publish_ready and not result.can_publish


@pytest.mark.parametrize("suffix,check",[("end_pr",ComplianceCheckCode.DISCLOSURE),
    (" SALE",ComplianceCheckCode.CLAIM_EVIDENCE),(" 今だけ",ComplianceCheckCode.CLAIM_EVIDENCE)])
def test_copy_t02_t03_t04_end_disclosure_unsupported_sale_urgency_fail(content_case,suffix,check):
    candidates,_,proposal=content_case
    variant=proposal.platform_variants[0]
    caption=variant.caption[3:]+" PR" if suffix=="end_pr" else variant.caption+suffix
    changed=proposal.model_copy(update={"platform_variants":(variant.model_copy(update={"caption":caption}),)})
    assert not passed(report(changed,candidates),check)


def test_copy_t06_changed_and_stale_price_fail(content_case):
    candidates,_,proposal=content_case
    candidate=candidates[0]
    changed=candidate.model_copy(update={"offer":candidate.offer.model_copy(update={"price":candidate.offer.price.model_copy(update={"amount":Decimal(1)})})})
    assert not report(proposal,(changed,)).content_ready
    assert not report(proposal,candidates,at=DEMO_AS_OF+timedelta(days=2)).content_ready


def test_copy_t07_t08_long_name_preserved_independent_short_context_headline(content_case):
    candidates,_,proposal=content_case
    assert len(LONG_NAME)>load_phase0_config().visual.max_slide1_headline_characters
    assert proposal.content.products[0].canonical_product_name == candidates[0].name == LONG_NAME
    assert LONG_NAME in proposal.canonical_message and LONG_NAME in proposal.platform_variants[0].caption
    assert all(label.product_name==LONG_NAME for slide in proposal.carousel.slides for label in slide.labels)
    assert proposal.carousel.slides[0].headline == ContextHeadline.DESK.value
    assert len(proposal.carousel.slides[0].headline)<=24


def approval_for(proposal,candidates):
    digest=proposal_content_digest(proposal,candidates)
    return HumanApproval(proposal_id=proposal.proposal_id,approved_content_digest=digest,
        review_decision=ReviewDecision(review_id="synthetic-review",draft_id=proposal.proposal_id,trace_id="ECHO-AI-20260928-000001",
            decision=DecisionType.APPROVE,reviewed_at=DEMO_AS_OF,
            reviewer_note=f"Affiliate Phase 0 content SHA-256: {digest}"))


def test_credit_t01_t02_t03_unresolved_credit_blocks_even_human_approved_content(content_case):
    candidates,_,proposal=content_case
    result=report(proposal,candidates,approval=approval_for(proposal,candidates))
    assert proposal.content and proposal.visual_plan.visual_plan_ready and result.content_ready
    assert proposal.webservice_credit.required and not proposal.webservice_credit.resolved
    assert result.approval_valid and not passed(result,ComplianceCheckCode.WEBSERVICE_CREDIT)
    assert not result.publish_ready and not result.can_publish
    assert not passed(result,ComplianceCheckCode.PLATFORM_COMPLIANCE)
    with pytest.raises(ValidationError):
        WebServiceCredit(required=False)
    with pytest.raises(ValidationError):
        WebServiceCredit(surface_status="resolved")


@pytest.mark.parametrize("change",["headline","copy","price","destination","asset","geometry"])
def test_content_and_visual_changes_invalidate_existing_review_digest(content_case,change):
    candidates,observations,proposal=content_case
    approval=approval_for(proposal,candidates)
    if change=="headline":
        _,updated=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,headline=ContextHeadline.LIFESTYLE)
    elif change=="copy":
        v=proposal.platform_variants[0]
        updated=proposal.model_copy(update={"platform_variants":(v.model_copy(update={"caption":v.caption+" changed"}),)})
    elif change=="price":
        c=candidates[0]
        candidates=(c.model_copy(update={"offer":c.offer.model_copy(update={"price":c.offer.price.model_copy(update={"amount":Decimal(1)})})}),)
        updated=proposal
    elif change=="destination":
        c=candidates[0];d=c.offer.affiliate_destination
        candidates=(c.model_copy(update={"offer":c.offer.model_copy(update={"affiliate_destination":d.model_copy(update={"destination_url":"https://affiliate.invalid/changed"})})}),)
        updated=proposal
    elif change=="asset":
        _,updated=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(reviewed_asset(candidates[0]),))
    else:
        data=proposal.model_dump();data["visual_plan"]["slides"][0]["arrow_regions"][0]["bounds"]["width"]=Decimal(".02")
        updated=SocialProposal.model_validate(data)
    assert proposal_content_digest(updated,candidates)!=approval.approved_content_digest
    assert not report(updated,candidates,approval=approval).approval_valid


def test_exact_candidate_and_fixed_asset_identity_inventory(content_case):
    candidates,observations,proposal=content_case
    with pytest.raises(ValueError):
        proposal_content_digest(proposal,candidates+candidates)
    with pytest.raises(ValueError):
        build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,
            reviewed_assets=(reviewed_asset(candidates[0],provider_item_id="synthetic:other"),))
    data=proposal.model_dump();data["visual_plan"]["assets"][0]["source_reference"]="other-asset"
    with pytest.raises(ValidationError):
        SocialProposal.model_validate(data)
    data=proposal.model_dump();data["visual_plan"]["slides"][0]["text_regions"][0]["text"]="short invented name"
    with pytest.raises(ValidationError):
        SocialProposal.model_validate(data)


def test_missing_image_reference_keeps_plan_but_never_invents_api_asset(content_case):
    candidates,observations,_=content_case
    _,proposal=build_content_proposal(candidates,tuple(o.model_copy(update={"assets":()}) for o in observations),"reading corner",as_of=DEMO_AS_OF)
    assert proposal.visual_plan.visual_plan_ready
    assert asset_eligibility(proposal.visual_plan.assets[0],as_of=DEMO_AS_OF)==AssetEligibility.REJECTED
    assert not visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF)


@pytest.mark.parametrize("updates",[{"local_asset_available":False},{"resize_permission":None},
    {"context_composition_permission":None},{"asset_content_sha256":None},{"reviewed_at":DEMO_AS_OF+timedelta(seconds=1)},
    {"rights_valid_until":DEMO_AS_OF+timedelta(seconds=1)}])
def test_unknown_missing_expired_permissions_block_render(content_case,updates):
    candidates,observations,_=content_case
    asset=reviewed_asset(candidates[0],**updates)
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(asset,))
    assert not visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF+timedelta(seconds=2)) if "rights_valid_until" in updates else not visual_render_ready(proposal.visual_plan,as_of=DEMO_AS_OF)


def test_level2_requires_separate_stronger_permission(content_case):
    candidates,observations,_=content_case
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(reviewed_asset(candidates[0]),))
    with pytest.raises(ValidationError):
        RightsSafeVisualPlan.model_validate({**proposal.visual_plan.model_dump(),"level":"integrated_lifestyle"})
    asset=reviewed_asset(candidates[0],source_class=AssetSourceClass.SEPARATE_LICENSE,download_source_class=AssetSourceClass.SEPARATE_LICENSE,
        acquisition_method="manual_separate_license",integrated_composition_permission=True)
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(asset,))
    plan=RightsSafeVisualPlan.model_validate({**proposal.visual_plan.model_dump(),"level":"integrated_lifestyle"})
    assert visual_render_ready(plan,as_of=DEMO_AS_OF)


def test_current_availability_is_independent_content_requirement(content_case):
    candidates,_,proposal=content_case;c=candidates[0]
    records=tuple(e.model_copy(update={"observed_at":DEMO_AS_OF-timedelta(hours=13)}) if e.evidence_type==EvidenceType.AVAILABILITY else e for e in c.evidence)
    assert not report(proposal,(c.model_copy(update={"evidence":records}),)).content_ready


def test_source_neutral_copy_never_misattributes_service(content_case):
    _,_,proposal=content_case
    product=proposal.content.products[0].model_copy(update={"service":AffiliateService.RAKUYOKO})
    content=proposal.content.model_copy(update={"products":(product,)})
    assert "ラクヨコの商品" in content.body_copy and "楽天市場の商品" not in content.body_copy


def test_render_boundary_rejects_unvalidated_crop_mutation(content_case):
    candidates,observations,_=content_case
    _,proposal=build_content_proposal(candidates,observations,"reading corner",as_of=DEMO_AS_OF,reviewed_assets=(reviewed_asset(candidates[0]),))
    assert not visual_render_ready(proposal.visual_plan.model_copy(update={"crop_requested":True}),as_of=DEMO_AS_OF)
