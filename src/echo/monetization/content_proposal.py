"""Evidence-backed content and protected visual planning on SocialProposal.

No asset intake, rendering, publication, persistence or transport occurs here.
"""

from datetime import datetime
from decimal import Decimal
import hashlib

from echo.models.affiliate import EvidenceType, ProductCandidate, ProductSet, ProductSetItem
from echo.models.affiliate_assets import (
    ArrowPlacement, AssetSourceClass, BoundingRegion, ProtectedProductRegion,
    RightsProvenance, RightsSafeSlide, RightsSafeVisualPlan, TextPlacement,
)
from echo.models.affiliate_content import ContentProduct, ContentProposalDetails, ContextHeadline, WebServiceCredit
from echo.models.affiliate_visual import (
    CarouselPlan, CarouselSlide, DisclosurePlacement, LifestyleScene, MarketingClaim,
    PlatformVariant, ProductVisualLabel, RightsStatus, SlideKind, SocialPlatform,
    SocialProposal, VisualAsset, VisualAssetKind,
)
from echo.models.discovery import ProviderObservation
from echo.monetization.asset_policy import ELIGIBLE_STATES, asset_eligibility
from echo.monetization.config import AffiliatePhase0Config, load_phase0_config


def _scene(identity, context, categories, *, detail=False):
    return LifestyleScene(scene_id=identity, room_geometry="planned rectangular room", room_size="planned compact room",
        window_placement="planned side window", furniture_placement="planned functional corner", interior_style="restrained original lifestyle",
        time_of_day="planned daytime", lighting="planned natural light", color_temperature="planned neutral",
        outside_scenery="unspecified planned view", season="unspecified", camera_angle="detail view " + identity if detail else "wide overview",
        usage_context=context, product_categories=categories)


def _region(x, y, width, height):
    return BoundingRegion(x=Decimal(str(x)), y=Decimal(str(y)), width=Decimal(str(width)), height=Decimal(str(height)))


def _protected_slide(number, candidates, labels, context, headline=None):
    count=Decimal(len(candidates));images=[];texts=[];arrows=[]
    for i,(candidate,label) in enumerate(zip(candidates,labels)):
        y=Decimal(".18")+Decimal(i)*Decimal(".72")/count
        bounds=_region(".52",y,".44",Decimal(".64")/count)
        images.append(ProtectedProductRegion(product_id=candidate.product_id,asset_id=label.product_asset_id,bounds=bounds))
        texts.extend((TextPlacement(kind="canonical_product_name",product_id=candidate.product_id,text=candidate.name,
            bounds=_region(".04",y,".44",Decimal(".42")/count)),
            TextPlacement(kind="price",product_id=candidate.product_id,text=f"価格: {label.price} {label.currency}",
            bounds=_region(".04",y+Decimal(".44")/count,".44",Decimal(".10")/count))))
        if number==1:
            arrows.append(ArrowPlacement(product_id=candidate.product_id,
                bounds=_region(".49",y+Decimal(".30")/count,".03",Decimal(".02")/count)))
    if headline is not None:
        texts.append(TextPlacement(kind="headline",product_id=candidates[0].product_id,text=headline,
                                  bounds=_region(".04",".03",".90",".08")))
    return RightsSafeSlide(slide_number=number,scene_type="lifestyle_context_overview" if number==1 else "product_detail_context",
        use_context=context,product_regions=tuple(images),text_regions=tuple(texts),
        no_overlay_zones=tuple(i.bounds for i in images),arrow_regions=tuple(arrows))


def build_content_proposal(candidates: tuple[ProductCandidate, ...], observations: tuple[ProviderObservation, ...],
                           context: str, *, as_of: datetime, config: AffiliatePhase0Config | None = None,
                           reviewed_assets: tuple[RightsProvenance, ...] = (),
                           headline: ContextHeadline = ContextHeadline.LIFESTYLE):
    config=config or load_phase0_config()
    headline=ContextHeadline(headline)
    if as_of.tzinfo is None or not context.strip() or not candidates or len({c.product_id for c in candidates})!=len(candidates):
        raise ValueError("bounded unique products, explicit context and aware evaluation time required")
    if len(headline.value)>config.visual.max_slide1_headline_characters:
        raise ValueError("short context headline exceeds its independent character limit")
    ids=tuple(c.product_id for c in candidates)
    identity=hashlib.sha256((context+"|"+"|".join(ids)).encode()).hexdigest()[:16]
    set_id="discovery-set-"+identity
    product_set=ProductSet(product_set_id=set_id,theme=context,shared_scene_id="overview-"+identity,
        items=tuple(ProductSetItem(product_id=c.product_id,slide_order=i+1,featured=True) for i,c in enumerate(candidates))) if len(candidates)>=2 else None
    reviewed={a.product_id:a for a in reviewed_assets}
    if len(reviewed)!=len(reviewed_assets) or set(reviewed)-set(ids):
        raise ValueError("reviewed assets must belong to the exact supplied products")
    claims=[];products=[];assets=[];rights=[];labels=[]
    for candidate in candidates:
        quote=candidate.offer.price
        identities=sorted((e for e in candidate.evidence if e.evidence_type==EvidenceType.PRODUCT_IDENTITY and e.value_text==candidate.name),
                          key=lambda e:(-e.observed_at.timestamp(),e.evidence_id))
        if quote is None or not identities:
            raise ValueError("content requires original identity and exact price evidence")
        identity_record=identities[0]
        products.append(ContentProduct(product_id=candidate.product_id,service=candidate.service,provider_item_id=candidate.provider_item_id,
            canonical_product_name=candidate.name,price=quote.amount,currency=quote.currency,price_evidence_id=quote.evidence_id,
            identity_evidence_id=identity_record.evidence_id,affiliate_destination_reference=candidate.offer.affiliate_destination.destination_id,
            claim_evidence_ids=(identity_record.evidence_id,quote.evidence_id)))
        claims.extend((MarketingClaim(claim_id="identity-"+candidate.product_id,product_id=candidate.product_id,
            statement=candidate.name,claim_type=EvidenceType.PRODUCT_IDENTITY,evidence_ids=(identity_record.evidence_id,)),
            MarketingClaim(claim_id="price-"+candidate.product_id,product_id=candidate.product_id,
            statement=f"価格: {quote.amount} {quote.currency}",claim_type=EvidenceType.PRICE,evidence_ids=(quote.evidence_id,))))
        asset=reviewed.get(candidate.product_id)
        if asset is None:
            has_reference=any(o.assets and (o.candidate.service,o.candidate.provider_item_id)==
                              (candidate.service,candidate.provider_item_id) for o in observations)
            asset=RightsProvenance(asset_id="asset-"+candidate.product_id,product_id=candidate.product_id,
                service=candidate.service,provider_item_id=candidate.provider_item_id,
                source_class=AssetSourceClass.API_REFERENCE if has_reference else AssetSourceClass.UNKNOWN,
                source_reference=("api-reference:" if has_reference else "asset-required:")+candidate.product_id,
                acquisition_method="api_reference_only" if has_reference else "unknown")
        if (asset.service,asset.provider_item_id)!=(candidate.service,candidate.provider_item_id):
            raise ValueError("reviewed asset must match the exact service/item")
        rights.append(asset)
        eligible=asset_eligibility(asset,as_of=as_of) in ELIGIBLE_STATES
        from echo.models.affiliate import EvidenceStatus
        assets.append(VisualAsset(asset_id=asset.asset_id,kind=VisualAssetKind.PRODUCT,source_reference=asset.source_reference,
            provenance_status=EvidenceStatus.VERIFIED if eligible else EvidenceStatus.UNKNOWN,
            rights_status=RightsStatus.GRANTED if eligible else RightsStatus.UNKNOWN,
            official_asset=asset.source_class==AssetSourceClass.AFFILIATE_PORTAL if eligible else None,
            transformations_allowed=False if eligible else None,product_ids=(candidate.product_id,),source_content_sha256=asset.asset_content_sha256))
        labels.append(ProductVisualLabel(product_id=candidate.product_id,product_name=candidate.name,price=quote.amount,currency=quote.currency,
            price_evidence_id=quote.evidence_id,destination_id=candidate.offer.affiliate_destination.destination_id,product_asset_id=asset.asset_id))
    content=ContentProposalDetails(products=tuple(products),headline=headline)
    overview_id="context-"+identity
    detail_ids={c.product_id:"context-detail-"+c.product_id for c in candidates}
    from echo.models.affiliate import EvidenceStatus
    for aid in (overview_id,*detail_ids.values()):
        assets.append(VisualAsset(asset_id=aid,kind=VisualAssetKind.GENERATED_CONTEXT,source_reference="planned-not-rendered:"+aid,
                                 provenance_status=EvidenceStatus.UNKNOWN,rights_status=RightsStatus.UNKNOWN))
    slides=[CarouselSlide(slide_number=1,kind=SlideKind.OVERVIEW,scene=_scene("overview-"+identity,context,tuple(sorted({c.category for c in candidates}))),
        labels=tuple(labels),context_asset_id=overview_id,headline=headline.value,arrow_product_ids=ids)]
    protected=[_protected_slide(1,candidates,labels,context,headline.value)]
    for i,(candidate,label) in enumerate(zip(candidates,labels),2):
        slides.append(CarouselSlide(slide_number=i,kind=SlideKind.PRODUCT_DETAIL,
            scene=_scene("detail-"+candidate.product_id,context,(candidate.category,),detail=True),labels=(label,),context_asset_id=detail_ids[candidate.product_id]))
        protected.append(_protected_slide(i,(candidate,),(label,),context))
    proposal=SocialProposal(proposal_id="discovery-proposal-"+identity,product_set_id=set_id,canonical_message=content.body_copy,product_ids=ids,
        claims=tuple(claims),visual_assets=tuple(assets),carousel=CarouselPlan(product_set_id=set_id,slides=tuple(slides)),
        platform_variants=(PlatformVariant(platform=SocialPlatform.X,caption=content.x_caption,disclosure_text="PR",
            disclosure_placement=DisclosurePlacement.FIRST_VIEW,native_disclosure_requirement_known=True,native_paid_partnership_enabled=False),),
        created_at=as_of,content=content,visual_plan=RightsSafeVisualPlan(slides=tuple(protected),assets=tuple(rights)),webservice_credit=WebServiceCredit())
    return product_set,proposal
