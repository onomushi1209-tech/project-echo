"""Platform-neutral carousel planning and approval-content fingerprinting."""

from __future__ import annotations

import hashlib
import json

from echo.models.affiliate import ProductCandidate, ProductSet, product_set_product_ids
from echo.models.affiliate_visual import (
    CarouselPlan,
    CarouselSlide,
    LifestyleScene,
    ProductVisualLabel,
    SlideKind,
    SocialProposal,
    VisualAsset,
    VisualAssetKind,
    VisualPolicy,
)


def build_carousel_plan(
    product_set: ProductSet,
    candidates: tuple[ProductCandidate, ...],
    *,
    assets: tuple[VisualAsset, ...],
    overview_scene: LifestyleScene,
    detail_scenes: dict[str, LifestyleScene],
    overview_context_asset_id: str,
    detail_context_asset_ids: dict[str, str],
    headline: str,
    policy: VisualPolicy,
    prior_scene_fingerprints: tuple[str, ...],
) -> CarouselPlan:
    """Build overview plus one item-level detail slide per product-set item."""
    if len(headline.strip()) > policy.max_slide1_headline_characters:
        raise ValueError("slide 1 headline exceeds the configured short-headline limit")
    candidate_by_id = {item.product_id: item for item in candidates}
    if len(candidate_by_id) != len(candidates) or set(candidate_by_id) != set(product_set_product_ids(product_set)):
        raise ValueError("carousel candidates must exactly match the product set")
    asset_by_id = {item.asset_id: item for item in assets}
    if len(asset_by_id) != len(assets):
        raise ValueError("visual asset IDs must be unique")

    labels = tuple(
        _product_label(candidate_by_id[item.product_id], asset_by_id)
        for item in sorted(product_set.items, key=lambda item: item.slide_order)
    )
    scenes = (overview_scene, *(detail_scenes[item.product_id]
                                for item in sorted(product_set.items, key=lambda item: item.slide_order)
                                if item.product_id in detail_scenes))
    fingerprints = tuple(scene.diversity_fingerprint for scene in scenes)
    if len(fingerprints) != len(product_set.items) + 1:
        raise ValueError("every detail slide needs a scene before diversity can be verified")
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("carousel scenes must be diverse")
    if any(not validate_scene_diversity(scene, prior_scene_fingerprints) for scene in scenes):
        raise ValueError("carousel scene repeats a recent scene")
    required_overview_categories = {candidate_by_id[label.product_id].category for label in labels}
    if not required_overview_categories.issubset(overview_scene.product_categories):
        raise ValueError("overview scene must name every featured product category")
    for item in product_set.items:
        if item.product_id in detail_scenes:
            scene = detail_scenes[item.product_id]
            if candidate_by_id[item.product_id].category not in scene.product_categories:
                raise ValueError("detail scene must be category-appropriate for its product")
    slides = [CarouselSlide(
        slide_number=1,
        kind=SlideKind.OVERVIEW,
        scene=overview_scene,
        labels=labels,
        context_asset_id=overview_context_asset_id,
        headline=headline.strip(),
        arrow_product_ids=tuple(label.product_id for label in labels),
    )]
    for item in sorted(product_set.items, key=lambda item: item.slide_order):
        candidate = candidate_by_id[item.product_id]
        if item.product_id not in detail_scenes or item.product_id not in detail_context_asset_ids:
            raise ValueError("every detail slide needs a category-appropriate scene and context asset")
        slides.append(CarouselSlide(
            slide_number=len(slides) + 1,
            kind=SlideKind.PRODUCT_DETAIL,
            scene=detail_scenes[item.product_id],
            labels=(_product_label(candidate, asset_by_id),),
            context_asset_id=detail_context_asset_ids[item.product_id],
        ))
    return CarouselPlan(product_set_id=product_set.product_set_id, slides=tuple(slides))


def validate_scene_diversity(scene: LifestyleScene, prior_fingerprints: tuple[str, ...]) -> bool:
    """Return false when a proposal reuses a recent complete scene specification."""
    return scene.diversity_fingerprint not in set(prior_fingerprints)


def proposal_content_digest(proposal: SocialProposal, candidates: tuple[ProductCandidate, ...]) -> str:
    """Bind approval to canonical content and all cited product/evidence state."""
    candidate_by_id = {item.product_id: item for item in candidates}
    if set(proposal.product_ids) - set(candidate_by_id):
        raise ValueError("proposal references an unknown product")
    products = [candidate_by_id[product_id].model_dump(mode="json") for product_id in sorted(proposal.product_ids)]
    payload = {
        "proposal": proposal.model_dump(mode="json"),
        "products": products,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _product_label(candidate: ProductCandidate, assets: dict[str, VisualAsset]) -> ProductVisualLabel:
    if candidate.offer.price is None:
        raise ValueError(f"product {candidate.product_id} has no evidenced price for a visual label")
    product_assets = [asset for asset in assets.values()
                      if asset.kind == VisualAssetKind.PRODUCT and candidate.product_id in asset.product_ids]
    if len(product_assets) != 1:
        raise ValueError(f"product {candidate.product_id} must have exactly one fixed product asset")
    return ProductVisualLabel(
        product_id=candidate.product_id,
        product_name=candidate.name,
        price=candidate.offer.price.amount,
        currency=candidate.offer.price.currency,
        price_evidence_id=candidate.offer.price.evidence_id,
        destination_id=candidate.offer.affiliate_destination.destination_id,
        product_asset_id=product_assets[0].asset_id,
    )
