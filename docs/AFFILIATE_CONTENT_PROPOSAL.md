# Affiliate Phase 1.2 Real Content Proposal Foundation

Stage 6A extends the existing `SocialProposal`, `proposal_content_digest` and
Human Review binding. It adds no downloader, renderer, publisher, database
schema, API or approval framework. Selection, score weights, the .50 threshold,
confidence, freshness, conflict and exact-offer predicates remain unchanged.
Phase 1's offline fixture commands also exercise content planning.

## Identity and copy

`ContentProduct` retains the full original canonical name, service/item identity,
exact price/evidence and opaque destination reference. Names are never shortened
to meet the 24-character headline limit. A separate typed `ContextHeadline`
supplies a neutral context frame. The body renders original identity and price
facts; X derives a first-view `PR` variant. Destination references are planning
placeholders, not created or shortened affiliate URLs. No X card or reply-based
disclosure is assumed. Future Instagram/Threads variants remain separate.

Copy, identity, price, destination, asset/source/content identity, composition and
platform changes invalidate the existing digest-bound Human Approval. Approval
is not publication authorization and cannot replace rights or credit compliance.

## Protected visual planning

Lifestyle Context Style remains: a room/use-context overview, then detail/context
slides. Level 1 places the unchanged whole product image using `contain` and
preserved aspect ratio in a protected bounding box, with a separately planned
background. Text, full names, prices, annotations and arrows remain outside every
product image box. Generated context excludes product pixels. Crop, direct
overlay, redraw and appearance alteration are rejected. Long names wrap without
truncation. Pixel fit and legibility need a future renderer's independent check;
metadata does not prove a finished image's compliance.

Level 2 integrated composition needs a separate license or user-owned photo with
explicit stronger permission. Normal Portal permission does not establish it.
Shape, colour, proportion, material, components, controls, connectors, design
and branding must remain unchanged; no generator may recreate the product.

## Rights and manual handoff

| Source/review outcome | State | Product render prerequisite |
| --- | --- | --- |
| API reference | `API_REFERENCE_ONLY` | Blocked |
| Portal without review | `AFFILIATE_PORTAL_ASSET_UNVERIFIED` | Blocked |
| Portal with unknown subjects/permissions | `AFFILIATE_PORTAL_ASSET_MANUAL_REVIEW_REQUIRED` | Blocked |
| Complete Portal attestation | `AFFILIATE_PORTAL_ASSET_ELIGIBLE` | Eligible with local asset/hash |
| Proven separate license | `SEPARATELY_LICENSED` | Within explicit permissions |
| Proven user-owned photo | `USER_OWNED_PHOTO` | Within explicit permissions |
| Restricted, invalid, future, expired or unknown | `REJECTED` | Blocked |

Provenance records acquisition/download source, rights basis/proof reference,
SHA-256, crop/resize/overlay/context permissions, person/creative-photography/
distinctive-design classification, reviewer and review/expiry times. Restricted
Portal images are rejected; unknown categories or permissions stay blocked.

A future separately authorized workflow may let the user download an official
Portal asset and submit it to controlled intake with evidence. Stage 6A provides
no intake or download. `local_asset_available` and SHA-256 are reviewed metadata
attestations; future intake/render must independently verify bytes and permission
evidence. Tests use synthetic attestations only. Background assets remain
planned with rights unknown.

`content_ready`, `visual_plan_ready`, `visual_render_ready` and `publish_ready`
are separate. No eligible local asset means plan ready, render blocked, Human
Approval required and `can_publish=false`. A passing product-image prerequisite
alone does not make the complete carousel publishable.

## Official policy review (2026-10-03)

- [Rakuten Affiliate guidelines](https://affiliate.rakuten.co.jp/guideline/rule/):
  official Portal assets under applicable conditions, whole-image preservation,
  resizing/surrounding design, no crop/direct overlays; restrictions on portraits,
  creative photos/design. API references are not rights.
- [Rakuten SNS guidance](https://affiliate.rakuten.co.jp/know-how/susumeru/):
  preserve names/destinations under applicable rules. Echo conservatively retains
  complete names, without automatically applying a platform omission exception
  or third-party shortening.
- [Rakuten PR guidance](https://affiliate.rakuten.co.jp/guideline/stealth_marketing_regulation/):
  Echo always requires first-view PR as a conservative project rule.
- [Rakuten Web Service credit](https://webservice.rakuten.co.jp/guide/credit):
  applications need credit under supplied badge/HTML rules. A compliant social-only
  placement is not established here. `required=true` and
  `UNRESOLVED_FOR_SOCIAL_ONLY` express a fail-closed project inference, not an
  official exemption or invented placement.
- [X Paid Partnerships policy](https://help.x.com/en/rules-and-policies/paid-partnerships-policy.html):
  affiliate commissions are paid partnerships. PR alone does not replace native
  Paid Partnership disclosure. Requirement known, native enablement false;
  Stage 6A makes no X call.

Before Stage 7 publish readiness, credit needs an officially clarified method or
appropriate documented public application surface, alongside asset/render
verification, platform disclosure and current Human Approval. This pass does
not implement that surface or authorize publishing. Project State stores only
sanitized aggregate runtime results, never real names/copy, URLs or API bodies.
