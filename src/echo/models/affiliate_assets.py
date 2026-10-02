"""Source-neutral rights attestations and separate, protected product regions.

These are reviewed metadata contracts, not an asset downloader or renderer.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import Field, model_validator

from echo.models.affiliate import AffiliateModel, AffiliateService


class AssetSourceClass(str, Enum):
    API_REFERENCE = "api_reference"
    AFFILIATE_PORTAL = "affiliate_portal"
    SEPARATE_LICENSE = "separate_license"
    USER_OWNED = "user_owned"
    UNKNOWN = "unknown"


class AssetEligibility(str, Enum):
    API_REFERENCE_ONLY = "api_reference_only"
    AFFILIATE_PORTAL_ASSET_UNVERIFIED = "affiliate_portal_asset_unverified"
    AFFILIATE_PORTAL_ASSET_MANUAL_REVIEW_REQUIRED = "affiliate_portal_asset_manual_review_required"
    AFFILIATE_PORTAL_ASSET_ELIGIBLE = "affiliate_portal_asset_eligible"
    SEPARATELY_LICENSED = "separately_licensed"
    USER_OWNED_PHOTO = "user_owned_photo"
    REJECTED = "rejected"


class CompositionLevel(str, Enum):
    RIGHTS_SAFE_CONTEXT = "rights_safe_context"
    INTEGRATED_LIFESTYLE = "integrated_lifestyle"


class RightsProvenance(AffiliateModel):
    asset_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    service: AffiliateService
    provider_item_id: str = Field(min_length=1, repr=False)
    source_class: AssetSourceClass = AssetSourceClass.UNKNOWN
    source_reference: str = Field(min_length=1, repr=False)
    acquisition_method: Literal["api_reference_only", "manual_official_affiliate_portal", "manual_separate_license", "manual_user_owned", "unknown"] = "unknown"
    download_source_class: AssetSourceClass = AssetSourceClass.UNKNOWN
    rights_basis: str | None = None
    rights_proof_reference: str | None = None
    asset_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    local_asset_available: bool = Field(default=False, strict=True)
    crop_permission: bool | None = Field(default=None, strict=True)
    resize_permission: bool | None = Field(default=None, strict=True)
    overlay_permission: bool | None = Field(default=None, strict=True)
    context_composition_permission: bool | None = Field(default=None, strict=True)
    integrated_composition_permission: bool | None = Field(default=None, strict=True)
    contains_person: bool | None = Field(default=None, strict=True)
    creative_photography: bool | None = Field(default=None, strict=True)
    distinctive_design: bool | None = Field(default=None, strict=True)
    restricted_content_permission: bool | None = Field(default=None, strict=True)
    manual_reviewer: str | None = None
    reviewed_at: datetime | None = None
    rights_valid_until: datetime | None = None

    @model_validator(mode="after")
    def _safe_attestation_metadata(self) -> Self:
        from urllib.parse import urlparse
        for value in (self.source_reference, self.rights_proof_reference):
            if value is None:
                continue
            if any(ord(c) < 32 for c in value):
                raise ValueError("asset references cannot contain controls")
            if "://" in value:
                parsed = urlparse(value)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError("use an opaque asset reference rather than a sensitive URL")
        for value in (self.reviewed_at, self.rights_valid_until):
            if value is not None and value.tzinfo is None:
                raise ValueError("rights timestamps require an explicit timezone")
        if self.reviewed_at and self.rights_valid_until and self.rights_valid_until <= self.reviewed_at:
            raise ValueError("rights must remain valid after review")
        return self


class BoundingRegion(AffiliateModel):
    x: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    y: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    width: Decimal = Field(gt=0, le=1, allow_inf_nan=False)
    height: Decimal = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _inside_canvas(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized region must stay within the canvas")
        return self

    def intersects(self, other: "BoundingRegion") -> bool:
        return (self.x < other.x + other.width and other.x < self.x + self.width
                and self.y < other.y + other.height and other.y < self.y + self.height)


class ProtectedProductRegion(AffiliateModel):
    product_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    bounds: BoundingRegion
    fit: Literal["contain"] = "contain"
    preserve_full_image: Literal[True] = True
    preserve_aspect_ratio: Literal[True] = True


class TextPlacement(AffiliateModel):
    kind: Literal["canonical_product_name", "price", "headline", "annotation"]
    product_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    bounds: BoundingRegion
    line_wrap: Literal[True] = True
    truncate: Literal[False] = False


class ArrowPlacement(AffiliateModel):
    product_id: str = Field(min_length=1)
    bounds: BoundingRegion
    direction: Literal["toward_product_image_boundary"] = "toward_product_image_boundary"


class RightsSafeSlide(AffiliateModel):
    slide_number: int = Field(ge=1)
    scene_type: Literal["lifestyle_context_overview", "product_detail_context"]
    use_context: str = Field(min_length=1)
    product_regions: tuple[ProtectedProductRegion, ...] = Field(min_length=1)
    text_regions: tuple[TextPlacement, ...] = Field(min_length=1)
    no_overlay_zones: tuple[BoundingRegion, ...] = Field(min_length=1)
    arrow_regions: tuple[ArrowPlacement, ...] = ()

    @model_validator(mode="after")
    def _protect_whole_asset(self) -> Self:
        if len({r.product_id for r in self.product_regions}) != len(self.product_regions):
            raise ValueError("product regions must be unique")
        if any(r.bounds not in self.no_overlay_zones for r in self.product_regions):
            raise ValueError("every whole product image needs a matching no-overlay zone")
        if any(t.product_id not in {r.product_id for r in self.product_regions} for t in self.text_regions):
            raise ValueError("text must identify a product in its slide")
        if any(t.bounds.intersects(zone) for t in self.text_regions for zone in self.no_overlay_zones):
            raise ValueError("text/annotation intersects the protected product image")
        if (any(a.product_id not in {r.product_id for r in self.product_regions} for a in self.arrow_regions)
                or len({a.product_id for a in self.arrow_regions}) != len(self.arrow_regions)
                or any(a.bounds.intersects(z) for a in self.arrow_regions for z in self.no_overlay_zones)):
            raise ValueError("arrows must remain outside protected product pixels")
        if any(a.bounds.intersects(b.bounds) for i, a in enumerate(self.product_regions) for b in self.product_regions[i+1:]):
            raise ValueError("fixed product images cannot overlap")
        return self


class RightsSafeVisualPlan(AffiliateModel):
    level: CompositionLevel = CompositionLevel.RIGHTS_SAFE_CONTEXT
    slides: tuple[RightsSafeSlide, ...] = Field(min_length=2)
    assets: tuple[RightsProvenance, ...] = Field(min_length=1)
    crop_requested: bool = Field(default=False, strict=True)
    direct_overlay_requested: bool = Field(default=False, strict=True)
    resize_requested: bool = Field(default=True, strict=True)
    product_redraw_requested: Literal[False] = False
    product_appearance_altered: Literal[False] = False
    generated_context_excludes_product_pixels: Literal[True] = True

    @model_validator(mode="after")
    def _plan_integrity(self) -> Self:
        if [s.slide_number for s in self.slides] != list(range(1, len(self.slides)+1)):
            raise ValueError("visual plan slides must be contiguous")
        if self.slides[0].scene_type != "lifestyle_context_overview" or any(s.scene_type != "product_detail_context" for s in self.slides[1:]):
            raise ValueError("lifestyle overview must precede the detail slides")
        by_id = {a.asset_id:a for a in self.assets}
        if len(by_id) != len(self.assets):
            raise ValueError("rights assets must be unique")
        used = {r.asset_id for s in self.slides for r in s.product_regions}
        if used != set(by_id):
            raise ValueError("every used product region needs its exact rights attestation")
        for slide in self.slides:
            for region in slide.product_regions:
                asset = by_id[region.asset_id]
                if asset.product_id != region.product_id:
                    raise ValueError("asset and placement product identity must agree")
                if self.crop_requested or self.direct_overlay_requested:
                    raise ValueError("Stage 6A keeps whole product pixels free of crop and overlay")
                if self.level == CompositionLevel.INTEGRATED_LIFESTYLE and (
                    asset.source_class not in (AssetSourceClass.SEPARATE_LICENSE, AssetSourceClass.USER_OWNED)
                    or asset.integrated_composition_permission is not True):
                    raise ValueError("integrated composition requires separate stronger permission")
        return self

    @property
    def visual_plan_ready(self) -> bool:
        return True  # Valid metadata only; neither rights nor actual rendering.
