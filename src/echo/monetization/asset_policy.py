"""Fail-closed reviewed asset eligibility; no file or network acquisition."""

from datetime import datetime

from echo.models.affiliate_assets import (
    AssetEligibility, AssetSourceClass, CompositionLevel, RightsProvenance, RightsSafeVisualPlan,
)


ELIGIBLE_STATES = frozenset({AssetEligibility.AFFILIATE_PORTAL_ASSET_ELIGIBLE,
                           AssetEligibility.SEPARATELY_LICENSED, AssetEligibility.USER_OWNED_PHOTO})


def asset_eligibility(asset: RightsProvenance, *, as_of: datetime) -> AssetEligibility:
    if as_of.tzinfo is None:
        raise ValueError("asset review requires an aware evaluation time")
    if asset.source_class == AssetSourceClass.API_REFERENCE:
        return AssetEligibility.API_REFERENCE_ONLY
    portal = asset.source_class == AssetSourceClass.AFFILIATE_PORTAL
    restricted = (asset.contains_person, asset.creative_photography, asset.distinctive_design)
    if portal and any(value is True for value in restricted):
        return AssetEligibility.REJECTED
    if asset.source_class == AssetSourceClass.UNKNOWN:
        return AssetEligibility.REJECTED
    if not asset.manual_reviewer or not asset.manual_reviewer.strip() or asset.reviewed_at is None:
        return AssetEligibility.AFFILIATE_PORTAL_ASSET_UNVERIFIED if portal else AssetEligibility.REJECTED
    if asset.reviewed_at > as_of or asset.rights_valid_until is not None and asset.rights_valid_until <= as_of:
        return AssetEligibility.REJECTED
    if any(value is None for value in restricted):
        return AssetEligibility.AFFILIATE_PORTAL_ASSET_MANUAL_REVIEW_REQUIRED if portal else AssetEligibility.REJECTED
    if any(value is True for value in restricted) and asset.restricted_content_permission is not True:
        return AssetEligibility.REJECTED
    expected = {AssetSourceClass.AFFILIATE_PORTAL:"manual_official_affiliate_portal",
                AssetSourceClass.SEPARATE_LICENSE:"manual_separate_license",
                AssetSourceClass.USER_OWNED:"manual_user_owned"}
    proven = (asset.acquisition_method == expected[asset.source_class]
              and asset.download_source_class == asset.source_class
              and bool(asset.rights_basis and asset.rights_basis.strip())
              and bool(asset.rights_proof_reference and asset.rights_proof_reference.strip())
              and asset.asset_content_sha256 is not None
              and asset.resize_permission is True and asset.context_composition_permission is True
              and asset.crop_permission is not None and asset.overlay_permission is not None)
    if portal:
        proven = proven and asset.crop_permission is False and asset.overlay_permission is False
        return AssetEligibility.AFFILIATE_PORTAL_ASSET_ELIGIBLE if proven else AssetEligibility.AFFILIATE_PORTAL_ASSET_MANUAL_REVIEW_REQUIRED
    if not proven:
        return AssetEligibility.REJECTED
    return AssetEligibility.SEPARATELY_LICENSED if asset.source_class == AssetSourceClass.SEPARATE_LICENSE else AssetEligibility.USER_OWNED_PHOTO


def visual_render_ready(plan: RightsSafeVisualPlan, *, as_of: datetime) -> bool:
    # model_copy can bypass frozen-model validation; callers still fail closed.
    try:
        plan = RightsSafeVisualPlan.model_validate(plan.model_dump())
    except (ValueError, TypeError, AttributeError):
        return False
    return all(asset_eligibility(a, as_of=as_of) in ELIGIBLE_STATES
               and a.local_asset_available and a.asset_content_sha256 is not None
               and a.context_composition_permission is True
               and (not plan.resize_requested or a.resize_permission is True)
               and (plan.level != CompositionLevel.INTEGRATED_LIFESTYLE or a.integrated_composition_permission is True)
               for a in plan.assets)
