"""Fail-closed offline affiliate proposal checks and Human Review binding."""

from __future__ import annotations

from datetime import datetime, timedelta

from echo.models.affiliate import (
    DestinationStatus,
    EvidenceStatus,
    EvidenceType,
    ProductCandidate,
)
from echo.models.affiliate_visual import (
    ComplianceCheck,
    ComplianceCheckCode,
    ComplianceReport,
    DisclosurePlacement,
    HumanApproval,
    RightsStatus,
    SocialPlatform,
    SocialProposal,
    VisualAssetKind,
)
from echo.monetization.config import CompliancePolicy, load_phase0_config
from echo.monetization.evidence import find_conflicting_evidence
from echo.monetization.evidence import evidence_is_current
from echo.monetization.asset_policy import visual_render_ready
from echo.monetization.visuals import proposal_content_digest, validate_scene_diversity


PROMOTION_EVIDENCE = frozenset({
    EvidenceType.DISCOUNT,
    EvidenceType.SALE_END,
    EvidenceType.COUPON,
    EvidenceType.POINT_MULTIPLIER,
})


def evaluate_compliance(
    proposal: SocialProposal,
    candidates: tuple[ProductCandidate, ...],
    policy: CompliancePolicy,
    *,
    as_of: datetime,
    seen_proposal_digests: tuple[str, ...] = (),
    prior_scene_fingerprints: tuple[str, ...] | None = None,
    approval: HumanApproval | None = None,
) -> ComplianceReport:
    """Check disclosure, destination, claims, freshness, rights, duplicates and approval.

    Passing this Phase 0 policy never authorizes a live action. No publisher or
    affiliate-link creator exists in this package.
    """
    product_by_id = {item.product_id: item for item in candidates}
    candidate_ids_unique = len(product_by_id) == len(candidates)
    digest = proposal_content_digest(proposal, candidates)

    platforms = {variant.platform for variant in proposal.platform_variants}
    disclosure_ok = bool(proposal.platform_variants) and set(policy.required_platforms).issubset(platforms)
    if policy.require_affiliate_disclosure:
        disclosure_ok = disclosure_ok and all(
            variant.disclosure_text == "PR"
            and variant.caption == ("PR" if not proposal.canonical_message else f"PR {proposal.canonical_message}")
            and variant.disclosure_placement == DisclosurePlacement.FIRST_VIEW
            for variant in proposal.platform_variants
        )

    requested_products = [product_by_id.get(product_id) for product_id in proposal.product_ids]
    destination_ids = []
    destination_ok = all(candidate is not None for candidate in requested_products)
    for candidate in requested_products:
        if candidate is None:
            continue
        product_destination = candidate.offer.product_destination
        affiliate_destination = candidate.offer.affiliate_destination
        destination_ids.append(affiliate_destination.destination_id)
        if (
            product_destination.service != candidate.service
            or affiliate_destination.service != candidate.service
            or product_destination.provider_item_id != candidate.provider_item_id
            or affiliate_destination.provider_item_id != candidate.provider_item_id
            or product_destination.status != DestinationStatus.VERIFIED
            or affiliate_destination.status != DestinationStatus.VERIFIED
            or not _destination_evidence_valid(candidate, product_destination, EvidenceType.PRODUCT_DESTINATION,
                                               as_of, timedelta(hours=policy.max_destination_age_hours))
            or not _destination_evidence_valid(candidate, affiliate_destination,
                                               EvidenceType.AFFILIATE_DESTINATION, as_of,
                                               timedelta(hours=policy.max_destination_age_hours))
        ):
            destination_ok = False
    if not candidate_ids_unique:
        destination_ok = False
    if len(set(destination_ids)) != len(destination_ids):
        destination_ok = False

    price_ok = bool(requested_products)
    for candidate in requested_products:
        if candidate is None or candidate.offer.price is None:
            price_ok = False
            continue
        quote = candidate.offer.price
        evidence = next((item for item in candidate.evidence
                         if item.evidence_id == quote.evidence_id), None) if candidate is not None else None
        if (
            not candidate_ids_unique
            or evidence is None
            or evidence.evidence_type != EvidenceType.PRICE
            or evidence.value_number != quote.amount
            or evidence.status != EvidenceStatus.VERIFIED
            or not _fresh(evidence.observed_at, evidence.valid_until, as_of,
                          timedelta(hours=policy.max_price_age_hours), evidence.valid_from)
        ):
            price_ok = False
        if not _labels_match(proposal, candidate):
            price_ok = False

    rendered_claims = [
        (claim, product_by_id.get(claim.product_id)) for claim in proposal.claims
    ]
    rendered_claim_statements = [
        _render_claim_copy(claim, candidate) if candidate is not None else None
        for claim, candidate in rendered_claims
    ]
    claim_statements = {statement for statement in rendered_claim_statements if statement is not None}
    expected_canonical_message = " / ".join(
        statement for statement in rendered_claim_statements if statement is not None
    )
    stage6_valid = True
    if proposal.content is not None:
        try:
            SocialProposal.model_validate(proposal.model_dump())
            stage6_valid = _content_inventory_valid(proposal, candidates)
            expected_canonical_message = proposal.content.body_copy
        except (ValueError, TypeError, AttributeError):
            stage6_valid = False
    publish_copy_ok = (
        all(statement is not None for statement in rendered_claim_statements)
        and stage6_valid
        and proposal.canonical_message == expected_canonical_message
    )
    expected_caption = "PR" if not expected_canonical_message else f"PR {expected_canonical_message}"
    publish_copy_ok = publish_copy_ok and all(
        variant.caption == expected_caption for variant in proposal.platform_variants
    )
    publish_copy_ok = publish_copy_ok and all(
        slide.headline is None or slide.headline in claim_statements
        or proposal.content is not None and stage6_valid and slide.headline == proposal.content.headline.value
        for slide in proposal.carousel.slides
    ) and all(
        not label.annotation or any(
            candidate is not None
            and candidate.product_id == label.product_id
            and _render_claim_copy(claim, candidate) == label.annotation
            for claim, candidate in rendered_claims
        )
        for slide in proposal.carousel.slides for label in slide.labels
    )
    displayed_products = [
        product_by_id.get(label.product_id)
        for slide in proposal.carousel.slides for label in slide.labels
    ]
    claims_ok = candidate_ids_unique and publish_copy_ok and all(
        candidate is not None and _identity_evidence_valid(candidate)
        for candidate in displayed_products
    )
    promotion_ok = True
    for claim in proposal.claims:
        candidate = product_by_id.get(claim.product_id)
        if candidate is None:
            claims_ok = False
            promotion_ok = False
            continue
        candidate_evidence = {item.evidence_id: item for item in candidate.evidence}
        for evidence_id in claim.evidence_ids:
            evidence = candidate_evidence.get(evidence_id)
            if (
                evidence is None
                or evidence.product_id != claim.product_id
                or evidence.service != candidate.service
                or evidence.status != EvidenceStatus.VERIFIED
                or evidence.evidence_type != claim.claim_type
                or not _claim_statement_matches(claim, candidate, evidence)
                or not _fresh(evidence.observed_at, evidence.valid_until, as_of,
                              timedelta(hours=policy.max_promotion_age_hours), evidence.valid_from)
            ):
                claims_ok = False
                promotion_ok = False
                continue
            if claim.claim_type in PROMOTION_EVIDENCE and not _fresh(
                evidence.observed_at, evidence.valid_until, as_of,
                timedelta(hours=policy.max_promotion_age_hours), evidence.valid_from,
            ):
                promotion_ok = False

    conflict_candidates = tuple(candidate for candidate in requested_products if candidate is not None)
    conflicts = find_conflicting_evidence(conflict_candidates,
        **({"as_of":as_of, "max_age":timedelta(hours=load_phase0_config().scoring_max_evidence_age_hours)}
           if proposal.content is not None else {}))

    used_asset_ids = {
        slide.context_asset_id for slide in proposal.carousel.slides
    } | {
        label.product_asset_id
        for slide in proposal.carousel.slides
        for label in slide.labels
    }
    asset_by_id = {asset.asset_id: asset for asset in proposal.visual_assets}
    assets_present = used_asset_ids.issubset(asset_by_id)
    used_assets = [asset_by_id[asset_id] for asset_id in used_asset_ids if asset_id in asset_by_id]
    rights_ok = assets_present and all(
        asset.rights_status == RightsStatus.GRANTED
        and asset.provenance_status == EvidenceStatus.VERIFIED
        and (asset.kind != VisualAssetKind.PRODUCT or bool(asset.product_ids))
        and (asset.kind != VisualAssetKind.PRODUCT
             or (asset.official_asset is not None and asset.transformations_allowed is not None))
        for asset in used_assets
    )
    if proposal.content is not None:
        rights_ok = rights_ok and stage6_valid and visual_render_ready(proposal.visual_plan, as_of=as_of)
    appearance_ok = assets_present and all(
        asset.kind != VisualAssetKind.PRODUCT or not asset.product_appearance_altered
        for asset in used_assets
    )
    scenes = proposal.carousel.slides
    scene_fingerprints = tuple(slide.scene.diversity_fingerprint for slide in scenes)
    scene_diversity_ok = bool(
        prior_scene_fingerprints is not None
        and len(set(scene_fingerprints)) == len(scene_fingerprints)
        and all(validate_scene_diversity(slide.scene, prior_scene_fingerprints) for slide in scenes)
    )
    scene_diversity_ok = scene_diversity_ok and all(
        all(product_by_id.get(label.product_id) is not None
            and product_by_id[label.product_id].category in slide.scene.product_categories
            for label in slide.labels)
        and slide.scene.product_is_primary
        and candidate_ids_unique
        for slide in scenes
    )

    unique_proposal = digest not in set(seen_proposal_digests)
    approval_valid = bool(
        approval is not None
        and approval.proposal_id == proposal.proposal_id
        and approval.approved
        and _not_future(approval.review_decision.reviewed_at, as_of)
        and approval.approved_content_digest == digest
        and approval.reviewed_content_digest == digest
    )

    checks = (
        ComplianceCheck(code=ComplianceCheckCode.DISCLOSURE, passed=disclosure_ok,
                        reason="Every variant must begin with the exact PR marker and record first-view placement."),
        ComplianceCheck(code=ComplianceCheckCode.DESTINATION, passed=destination_ok,
                        reason="Each product needs its own verified service/item and affiliate destination."),
        ComplianceCheck(code=ComplianceCheckCode.CLAIM_EVIDENCE, passed=claims_ok,
                        reason="All proposal, caption, headline and annotation copy must exactly render typed evidence claims."),
        ComplianceCheck(code=ComplianceCheckCode.CONFLICTING_EVIDENCE, passed=not conflicts,
                        reason="Contradictory same-time product evidence must be resolved before approval."),
        ComplianceCheck(code=ComplianceCheckCode.PRICE_FRESHNESS, passed=price_ok,
                        reason="Every displayed price must match current verified price evidence."),
        ComplianceCheck(code=ComplianceCheckCode.PROMOTION_FRESHNESS, passed=promotion_ok,
                        reason="Promotion claims require current evidence and an unexpired deadline."),
        ComplianceCheck(code=ComplianceCheckCode.RIGHTS_PROVENANCE, passed=rights_ok,
                        reason="Every used asset needs verified provenance and rights; product assets must declare official and transformation status."),
        ComplianceCheck(code=ComplianceCheckCode.PRODUCT_APPEARANCE, passed=appearance_ok,
                        reason="Real product appearance must remain unchanged from the fixed source asset."),
        ComplianceCheck(code=ComplianceCheckCode.SCENE_DIVERSITY, passed=scene_diversity_ok,
                        reason="Every slide must use a product-first category-matched scene distinct from recent scenes."),
        ComplianceCheck(code=ComplianceCheckCode.DUPLICATE_PROPOSAL, passed=unique_proposal,
                        reason="The same canonical proposal digest cannot be repeated in the selected history."),
        ComplianceCheck(code=ComplianceCheckCode.HUMAN_APPROVAL, passed=approval_valid,
                        reason="A current explicit approval through the existing Human Review Gate is required."),
        ComplianceCheck(code=ComplianceCheckCode.WEBSERVICE_CREDIT,
                        passed=proposal.content is None,
                        reason="Stage 6A requires Rakuten Web Service credit; social-only placement is unresolved and cannot be approved away."),
        ComplianceCheck(code=ComplianceCheckCode.PLATFORM_COMPLIANCE,
                        passed=proposal.content is None or all(v.platform != SocialPlatform.X or
                            v.native_disclosure_requirement_known and v.native_paid_partnership_enabled for v in proposal.platform_variants),
                        reason="X affiliate partnerships also require verified native Paid Partnership disclosure; PR alone is insufficient."),
        ComplianceCheck(code=ComplianceCheckCode.CURRENT_AVAILABILITY,
                        passed=proposal.content is None or all(c.offer.available is True and any(
                            e.evidence_type == EvidenceType.AVAILABILITY and e.value_boolean is True
                            and e.status == EvidenceStatus.VERIFIED and evidence_is_current(e,as_of=as_of,
                                max_age=timedelta(hours=load_phase0_config().buy_now.max_age_by_type[EvidenceType.AVAILABILITY]))
                            for e in c.evidence) for c in conflict_candidates),
                        reason="Content proposals require current verified positive availability, independently of price."),
    )
    preapproval_ok = all(check.passed for check in checks if check.code != ComplianceCheckCode.HUMAN_APPROVAL)
    return ComplianceReport(
        proposal_id=proposal.proposal_id,
        proposal_digest=digest,
        checks=checks,
        ready_for_human_approval=preapproval_ok,
        approval_valid=approval_valid,
        eligible_for_future_publish=preapproval_ok and approval_valid,
        live_publish_authorized=False,
    )


def _content_inventory_valid(proposal, candidates) -> bool:
    by_id = {c.product_id:c for c in candidates}
    if len(by_id) != len(candidates) or set(by_id) != set(proposal.product_ids):
        return False
    expected_claims = set()
    for product in proposal.content.products:
        candidate = by_id[product.product_id]
        quote = candidate.offer.price
        if quote is None or (product.service,product.provider_item_id,product.canonical_product_name,
                product.price,product.currency,product.price_evidence_id,product.affiliate_destination_reference) != (
                candidate.service,candidate.provider_item_id,candidate.name,quote.amount,quote.currency,quote.evidence_id,
                candidate.offer.affiliate_destination.destination_id):
            return False
        expected_claims |= {(product.product_id,EvidenceType.PRODUCT_IDENTITY,product.identity_evidence_id),
                            (product.product_id,EvidenceType.PRICE,product.price_evidence_id)}
    actual_claims = {(c.product_id,c.claim_type,c.evidence_ids[0]) for c in proposal.claims}
    if actual_claims != expected_claims or len(actual_claims) != len(proposal.claims):
        return False
    for asset in proposal.visual_plan.assets:
        candidate = by_id.get(asset.product_id)
        if candidate is None or (asset.service,asset.provider_item_id) != (candidate.service,candidate.provider_item_id):
            return False
    return True


def _fresh(observed_at: datetime, valid_until: datetime | None, as_of: datetime,
           max_age: timedelta, valid_from: datetime | None = None) -> bool:
    try:
        return observed_at <= as_of and (valid_from is None or valid_from <= as_of) \
            and as_of - observed_at <= max_age and (
            valid_until is None or valid_until > as_of
        )
    except TypeError:
        return False


def _not_future(value: datetime, as_of: datetime) -> bool:
    try:
        return value <= as_of
    except TypeError:
        return False


def _labels_match(proposal: SocialProposal, candidate: ProductCandidate) -> bool:
    found = False
    for slide in proposal.carousel.slides:
        for label in slide.labels:
            if label.product_id != candidate.product_id:
                continue
            found = True
            if candidate.offer.price is None:
                return False
            if (
                label.product_name != candidate.name
                or label.price != candidate.offer.price.amount
                or label.currency != candidate.offer.price.currency
                or label.price_evidence_id != candidate.offer.price.evidence_id
                or label.destination_id != candidate.offer.affiliate_destination.destination_id
            ):
                return False
    return found


def _identity_evidence_valid(candidate: ProductCandidate) -> bool:
    """Require the visible item name to come from its own verified identity record."""
    return any(
        evidence.product_id == candidate.product_id
        and evidence.service == candidate.service
        and evidence.evidence_type == EvidenceType.PRODUCT_IDENTITY
        and evidence.status == EvidenceStatus.VERIFIED
        and evidence.value_text == candidate.name
        for evidence in candidate.evidence
    )


def _render_claim_copy(claim, candidate: ProductCandidate) -> str:
    """Give each fact explicit product context in all publish-facing copy."""
    if claim.claim_type == EvidenceType.PRODUCT_IDENTITY:
        return candidate.name
    return f"{candidate.name}: {claim.statement}"


def _destination_evidence_valid(candidate: ProductCandidate, destination, evidence_type: EvidenceType,
                                as_of: datetime, max_age: timedelta) -> bool:
    if destination.status != DestinationStatus.VERIFIED or destination.destination_url is None:
        return False
    evidence = next((item for item in candidate.evidence
                     if item.evidence_id == destination.verification_evidence_id), None)
    return bool(
        evidence is not None
        and evidence.evidence_type == evidence_type
        and evidence.status == EvidenceStatus.VERIFIED
        and evidence.product_id == candidate.product_id
        and evidence.service == candidate.service
        and evidence.provider_item_id == candidate.provider_item_id
        and evidence.value_text == destination.destination_url
        and _fresh(evidence.observed_at, evidence.valid_until, as_of, max_age, evidence.valid_from)
    )


_CLAIM_LABELS = {
    EvidenceType.DISCOUNT: "割引",
    EvidenceType.COUPON: "クーポン",
    EvidenceType.POINT_MULTIPLIER: "ポイント倍率",
    EvidenceType.RANKING: "ランキング順位",
    EvidenceType.REVIEW_COUNT: "レビュー件数",
    EvidenceType.REVIEW_RATING: "レビュー評価",
    EvidenceType.AVAILABILITY: "在庫",
    EvidenceType.SEASONALITY: "季節情報",
    EvidenceType.TREND_RELEVANCE: "トレンド関連性",
}


def _claim_statement_matches(claim, candidate: ProductCandidate, evidence) -> bool:
    """Accept only exact, evidence-rendered facts; Phase 0 cannot attest freeform copy."""
    if claim.claim_type != evidence.evidence_type:
        return False
    if claim.claim_type == EvidenceType.PRODUCT_IDENTITY:
        return evidence.value_text == candidate.name and claim.statement == candidate.name
    if claim.claim_type == EvidenceType.PRICE:
        quote = candidate.offer.price
        return bool(
            quote is not None
            and quote.evidence_id == evidence.evidence_id
            and evidence.value_number == quote.amount
            and claim.statement == f"価格: {quote.amount} {quote.currency}"
        )
    if claim.claim_type == EvidenceType.SALE_END:
        return bool(
            evidence.valid_until is not None
            and claim.statement == f"販売終了: {evidence.valid_until.isoformat()}"
        )
    label = _CLAIM_LABELS.get(claim.claim_type)
    if label is None:
        return False
    if evidence.value_text is not None:
        rendered = evidence.value_text
    elif evidence.value_number is not None:
        rendered = format(evidence.value_number, "f")
    elif evidence.value_boolean is not None:
        rendered = "あり" if evidence.value_boolean else "なし"
    else:
        return False
    return claim.statement == f"{label}: {rendered}"
