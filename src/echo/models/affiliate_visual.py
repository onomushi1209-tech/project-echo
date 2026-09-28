"""Visual proposal, rights, disclosure, compliance and human-review contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import Field, model_validator

from echo.models.affiliate import AffiliateModel, EvidenceStatus, EvidenceType, ProductSet
from echo.models.enums import DecisionType
from echo.models.review import ReviewDecision


class VisualAssetKind(str, Enum):
    PRODUCT = "product"
    GENERATED_CONTEXT = "generated_context"


class RightsStatus(str, Enum):
    GRANTED = "granted"
    UNKNOWN = "unknown"
    PROHIBITED = "prohibited"


APPROVAL_DIGEST_NOTE_PREFIX = "Affiliate Phase 0 content SHA-256: "


def _reviewed_affiliate_digest(reviewer_note: str | None) -> str | None:
    """Read the exact Phase 0 digest recorded with the Human Review decision."""
    if reviewer_note is None:
        return None
    first_line = reviewer_note.splitlines()[0] if reviewer_note.splitlines() else ""
    if not first_line.startswith(APPROVAL_DIGEST_NOTE_PREFIX):
        return None
    digest = first_line[len(APPROVAL_DIGEST_NOTE_PREFIX):]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return None
    return digest


class VisualAsset(AffiliateModel):
    asset_id: str = Field(min_length=1)
    kind: VisualAssetKind
    source_reference: str = Field(min_length=1)
    provenance_status: EvidenceStatus = EvidenceStatus.UNKNOWN
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    official_asset: bool | None = None
    transformations_allowed: bool | None = None
    product_ids: tuple[str, ...] = ()
    product_appearance_altered: bool = False

    @model_validator(mode="after")
    def _asset_role_is_explicit(self) -> Self:
        if self.kind == VisualAssetKind.PRODUCT and not self.product_ids:
            raise ValueError("product assets must identify the product they depict")
        if self.kind == VisualAssetKind.GENERATED_CONTEXT and self.product_ids:
            raise ValueError("generated context assets cannot stand in for product pixels")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("visual asset product IDs must be unique")
        return self


class LifestyleScene(AffiliateModel):
    scene_id: str = Field(min_length=1)
    room_geometry: str = Field(min_length=1)
    room_size: str = Field(min_length=1)
    window_placement: str = Field(min_length=1)
    furniture_placement: str = Field(min_length=1)
    interior_style: str = Field(min_length=1)
    time_of_day: str = Field(min_length=1)
    lighting: str = Field(min_length=1)
    color_temperature: str = Field(min_length=1)
    outside_scenery: str = Field(min_length=1)
    season: str = Field(min_length=1)
    camera_angle: str = Field(min_length=1)
    usage_context: str = Field(min_length=1)
    product_categories: tuple[str, ...] = Field(min_length=1)
    people_included: bool = False
    people_rationale: str | None = None
    product_is_primary: bool = True

    @model_validator(mode="after")
    def _people_are_optional_and_justified(self) -> Self:
        if self.people_included and not (self.people_rationale and self.people_rationale.strip()):
            raise ValueError("people require a product-understanding rationale")
        if len(set(self.product_categories)) != len(self.product_categories):
            raise ValueError("scene product categories must be unique")
        if not self.product_is_primary:
            raise ValueError("the featured product must remain primary in its lifestyle scene")
        return self

    @property
    def diversity_fingerprint(self) -> str:
        return "|".join((self.room_geometry, self.room_size, self.window_placement,
                         self.furniture_placement, self.interior_style, self.time_of_day,
                         self.lighting, self.color_temperature, self.outside_scenery,
                         self.season, self.camera_angle, self.usage_context))


class ProductVisualLabel(AffiliateModel):
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_evidence_id: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    product_asset_id: str = Field(min_length=1)
    annotation: str = ""


class SlideKind(str, Enum):
    OVERVIEW = "overview"
    PRODUCT_DETAIL = "product_detail"


class CarouselSlide(AffiliateModel):
    slide_number: int = Field(ge=1)
    kind: SlideKind
    scene: LifestyleScene
    labels: tuple[ProductVisualLabel, ...] = Field(min_length=1)
    context_asset_id: str = Field(min_length=1)
    headline: str | None = None
    arrow_product_ids: tuple[str, ...] = ()
    annotation_color_family: str = "soft_light_gray"

    @model_validator(mode="after")
    def _slide_contract(self) -> Self:
        product_ids = [label.product_id for label in self.labels]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("a slide cannot repeat a product label")
        if self.kind == SlideKind.OVERVIEW:
            if self.slide_number != 1 or not (self.headline and self.headline.strip()):
                raise ValueError("slide 1 must be an overview with one short headline")
            if set(self.arrow_product_ids) != set(product_ids):
                raise ValueError("overview arrows/annotations must identify every featured product")
        else:
            if self.slide_number < 2 or len(self.labels) != 1:
                raise ValueError("each detail slide must zoom exactly one product after slide 1")
            if self.headline is not None:
                raise ValueError("detail slides do not use decorative headlines")
            if self.arrow_product_ids:
                raise ValueError("detail slides do not require overview arrows")
        if self.annotation_color_family != "soft_light_gray":
            raise ValueError("annotation family must remain understated soft light gray")
        return self


class CarouselPlan(AffiliateModel):
    product_set_id: str = Field(min_length=1)
    slides: tuple[CarouselSlide, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _ordered_overview_then_details(self) -> Self:
        if [slide.slide_number for slide in self.slides] != list(range(1, len(self.slides) + 1)):
            raise ValueError("carousel slides must be contiguous and in order")
        if self.slides[0].kind != SlideKind.OVERVIEW:
            raise ValueError("carousel slide 1 must be the whole-context overview")
        if any(slide.kind != SlideKind.PRODUCT_DETAIL for slide in self.slides[1:]):
            raise ValueError("slides after slide 1 must be product detail slides")
        fingerprints = [slide.scene.diversity_fingerprint for slide in self.slides]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("scene plans within a carousel must be diverse")
        return self


class VisualPolicy(AffiliateModel):
    max_slide1_headline_characters: int = Field(ge=1)
    require_product_asset_rights: bool = True
    require_scene_diversity: bool = True
    people_default: bool = False

    @model_validator(mode="after")
    def _preserve_canonical_safeguards(self) -> Self:
        if not self.require_product_asset_rights or not self.require_scene_diversity:
            raise ValueError("product rights and scene diversity safeguards cannot be disabled")
        if self.people_default:
            raise ValueError("people must remain optional and excluded by default")
        return self


class SocialPlatform(str, Enum):
    X = "x"
    INSTAGRAM = "instagram"
    THREADS = "threads"


class DisclosurePlacement(str, Enum):
    FIRST_VIEW = "first_view"
    BODY = "body"
    AFTER_FOLD = "after_fold"


class PlatformVariant(AffiliateModel):
    platform: SocialPlatform
    caption: str = Field(min_length=1)
    disclosure_text: str = Field(min_length=1)
    disclosure_placement: DisclosurePlacement
    native_disclosure_requirement_known: bool = False


class MarketingClaim(AffiliateModel):
    claim_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    claim_type: EvidenceType
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("claim evidence IDs must be unique")
        if len(self.evidence_ids) != 1:
            raise ValueError("Phase 0 claims must bind to exactly one evidence record")
        return self


class SocialProposal(AffiliateModel):
    proposal_id: str = Field(min_length=1)
    product_set_id: str = Field(min_length=1)
    canonical_message: str
    product_ids: tuple[str, ...] = Field(min_length=1)
    claims: tuple[MarketingClaim, ...] = ()
    visual_assets: tuple[VisualAsset, ...] = ()
    carousel: CarouselPlan
    platform_variants: tuple[PlatformVariant, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def _proposal_references(self) -> Self:
        if self.carousel.product_set_id != self.product_set_id:
            raise ValueError("carousel and proposal must refer to the same product set")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("proposal product IDs must be unique")
        if len(self.carousel.slides) != len(self.product_ids) + 1:
            raise ValueError("carousel must contain one overview and one detail slide per product")
        overview_products = {label.product_id for label in self.carousel.slides[0].labels}
        detail_products = [self.carousel.slides[index].labels[0].product_id
                           for index in range(1, len(self.carousel.slides))]
        if overview_products != set(self.product_ids) or set(detail_products) != set(self.product_ids):
            raise ValueError("overview and detail slides must each cover every proposal product exactly once")
        if len(detail_products) != len(set(detail_products)):
            raise ValueError("each proposal product must have one detail slide")
        assets_by_id = {asset.asset_id: asset for asset in self.visual_assets}
        if len(assets_by_id) != len(self.visual_assets):
            raise ValueError("visual asset IDs must be unique within a proposal")
        for slide in self.carousel.slides:
            context = assets_by_id.get(slide.context_asset_id)
            if context is None or context.kind != VisualAssetKind.GENERATED_CONTEXT:
                raise ValueError("each carousel slide must reference a generated context asset")
            for label in slide.labels:
                asset = assets_by_id.get(label.product_asset_id)
                if (asset is None or asset.kind != VisualAssetKind.PRODUCT
                        or label.product_id not in asset.product_ids):
                    raise ValueError("product labels must use their own fixed product asset")
        if any(claim.product_id not in self.product_ids for claim in self.claims):
            raise ValueError("marketing claims must reference a product in the proposal")
        variant_platforms = [item.platform for item in self.platform_variants]
        if len(set(variant_platforms)) != len(variant_platforms):
            raise ValueError("platform-specific formats must be unique per platform")
        claim_ids = [item.claim_id for item in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim IDs must be unique")
        return self


class HumanApproval(AffiliateModel):
    """Digest binding recorded in the existing Human Review decision note."""

    proposal_id: str = Field(min_length=1)
    review_decision: ReviewDecision
    approved_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _bind_existing_review(self) -> Self:
        if self.review_decision.draft_id != self.proposal_id:
            raise ValueError("Human Review Gate decision must reference this proposal's draft ID")
        if _reviewed_affiliate_digest(self.review_decision.reviewer_note) != self.approved_content_digest:
            raise ValueError("Human Review Gate note must bind the exact approved Phase 0 content digest")
        return self

    @property
    def approved(self) -> bool:
        return self.review_decision.decision == DecisionType.APPROVE

    @property
    def reviewed_content_digest(self) -> str | None:
        return _reviewed_affiliate_digest(self.review_decision.reviewer_note)


class ComplianceCheckCode(str, Enum):
    DISCLOSURE = "disclosure"
    DESTINATION = "destination"
    CLAIM_EVIDENCE = "claim_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    PRICE_FRESHNESS = "price_freshness"
    PROMOTION_FRESHNESS = "promotion_freshness"
    RIGHTS_PROVENANCE = "rights_provenance"
    PRODUCT_APPEARANCE = "product_appearance"
    SCENE_DIVERSITY = "scene_diversity"
    DUPLICATE_PROPOSAL = "duplicate_proposal"
    HUMAN_APPROVAL = "human_approval"


class ComplianceCheck(AffiliateModel):
    code: ComplianceCheckCode
    passed: bool
    reason: str = Field(min_length=1)


class ComplianceReport(AffiliateModel):
    proposal_id: str = Field(min_length=1)
    proposal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[ComplianceCheck, ...]
    ready_for_human_approval: bool
    approval_valid: bool
    eligible_for_future_publish: bool
    live_publish_authorized: Literal[False] = False

    @property
    def can_publish(self) -> bool:
        return False

    @model_validator(mode="after")
    def _fail_closed(self) -> Self:
        passed = {item.code: item.passed for item in self.checks}
        required = set(ComplianceCheckCode)
        if set(passed) != required or len(self.checks) != len(required):
            raise ValueError("compliance report must include every fail-closed check")
        preapproval_ok = all(value for code, value in passed.items() if code != ComplianceCheckCode.HUMAN_APPROVAL)
        if self.ready_for_human_approval != preapproval_ok:
            raise ValueError("ready_for_human_approval must reflect every pre-approval check")
        if self.approval_valid != passed[ComplianceCheckCode.HUMAN_APPROVAL]:
            raise ValueError("approval_valid must match the human approval check")
        future_ok = preapproval_ok and self.approval_valid
        if self.eligible_for_future_publish != future_ok:
            raise ValueError("future publish eligibility requires compliance and current human approval")
        return self
