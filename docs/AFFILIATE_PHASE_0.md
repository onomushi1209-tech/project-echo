# Project Echo Zero — Affiliate Phase 0

## Scope and status

This document describes the accepted Phase 0 baseline. Its no-HTTP/no-credential
statements apply to that implementation. The separately scoped
[Phase 1 discovery candidate](AFFILIATE_PHASE_1.md) adds guarded readonly adapters;
it preserves these signal, scoring, rights and approval contracts.

This is an offline foundation for Project Echo Zero's Rakuten-first affiliate
workflow. It defines product/evidence, offer, room-bundle, scoring, proposal,
visual provenance, compliance, existing Human Review, attribution and KPI
contracts. The implementation contains no HTTP client, credential handling,
account access, affiliate-link creation, social publisher, database writes or
live authority. `echo affiliate demo` uses synthetic fixtures only.

Affiliate Phase 0 has no persistence requirement. Its models are immutable
inputs/outputs; SQL remains in `echo.storage`, and no schema or migration is
added. Existing STEP 1/2 storage and CLI interfaces remain unchanged. The
existing `ReviewDecision` is the only approval decision: a future proposal
bridge must bind the proposal ID to that review record (`draft_id`) and its
content digest. This phase creates neither a second review queue nor an
approval decision. A passing score or compliance report is never publish
authority; `ComplianceReport.can_publish` is always false.

## Official capability inventory

Sources below were checked on **2026-09-28**. “Verified” records only the
capability stated by the linked official documentation; it does not claim that
Project Echo has credentials, access, permission, or a live integration.

| Service / capability | Official evidence and confidence | Phase 0 treatment |
|---|---|---|
| Rakuten Ichiba item search returns item name/code, price, item URL, availability, reviews, affiliate rate, sale start/end, point multiplier and related fields | [Item Search API v2026-07-01](https://webservice.rakuten.co.jp/documentation/ichiba-item-search), high | Field-shaped synthetic fixture normalizer; verified live ingestion deferred. API requires application ID and access key. |
| Rakuten affiliate URL is returned when an `affiliateId` is supplied to Item Search | [Item Search API](https://webservice.rakuten.co.jp/documentation/ichiba-item-search), high | URL creation/use is not implemented. Fixture candidates keep product and affiliate destinations separate and uncreated. |
| Rakuten item ranking data is available through a ranking API | [Ichiba Item Ranking API v2022-06-01](https://webservice.rakuten.co.jp/documentation/ichiba-item-ranking), high | Ranking API adapter and evidence ingestion deferred; no ranking claim is fabricated by the current fixture. |
| Rakuten Product Search exposes structured product-search information | [Product Search API v2025-08-01](https://webservice.rakuten.co.jp/documentation/ichiba-product-search), high | Separate product-catalog adapter deferred. |
| Affiliate participation uses registered media and Rakuten's provided link-creation methods; reward conditions and rates vary by service/category and eligible tracked transactions | [Partner Terms](https://affiliate.rakuten.co.jp/guideline/terms/) and [Affiliate Guidelines](https://affiliate.rakuten.co.jp/guideline/rule/), high | Recorded as a future operational prerequisite. No fixed rate or guaranteed revenue is assumed. |
| Rakuyoko is a customer-facing store with product categories, R Select, and customer-facing app notices for sales, coupons and delivery | [Rakuyoko official guide](https://rakuyoko.rakuten.co.jp/guide/), high for those customer-facing facts | Boundary metadata only. No retailer/customer API call is made. |
| Rakuyoko external product search API, affiliate destinations/attribution, product bundling API, or content-workflow API | No official public contract for these capabilities was identified in the reviewed guide/materials | Explicitly `UNKNOWN / UNVERIFIED`; adapter refuses to require an unknown capability. |
| Clear advertising disclosure and affiliate conduct | [Rakuten Affiliate Guidelines](https://affiliate.rakuten.co.jp/guideline/rule/), [Rakuten PR guidance](https://affiliate.rakuten.co.jp/guideline/stealth_marketing_regulation/), and [Consumer Affairs Agency guidance](https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing) / [Q&A](https://www.caa.go.jp/policies/policy/representation/fair_labeling/faq/stealth_marketing/), high for the linked policy text | Project policy requires visible `PR` disclosure in the first view of every proposed platform variant. Platform-specific publication rules need a fresh review before live integration. |

## Domain and service boundaries

`echo.models.affiliate` defines source-neutral product identity, individual
offers and destinations, evidence, signals, score inputs and product sets.
`echo.monetization.adapters` contains only offline boundary/fixture adapters:
Rakuten-shaped item fixtures become `ProductCandidate` and provenance records;
Rakuyoko customer-facing facts are separated from unverified integration
capabilities. No Core or STEP 1/2 storage service imports a retailer
implementation.

Each product in a `ProductSet` has its own product ID, offer, price evidence,
product destination and affiliate destination. A set adds only a theme, shared
scene ID and ordering. `SocialProposal` carries item IDs and a `CarouselPlan`;
slide labels retain the item-level price, evidence ID and destination ID. There
is no bundle-level affiliate URL assumption. This leaves item-level attribution
available later.

A verified destination is accepted only when fresh evidence of the matching
destination type binds the exact HTTPS URL to the candidate's service and
provider item ID. Destination status alone is not proof. The current fixture
adapter creates no verified destinations; Phase 0 has no adapter that can
produce live destination evidence.

`ProductEvidence` records source, source field, observation time, optional
validity window, status and exactly one typed value. Fixture evidence exercises
the same code paths but is never accepted as publish evidence. Missing values
stay missing. The shared conflict layer compares one product/service/evidence
family using typed values and overlapping applicability intervals. Different
observation times do not hide a simultaneous contradiction; equivalent typed
values do not create one. Starts are inclusive and ends exclusive, so touching
or non-overlapping periods can represent normal historical succession.

## Buy-now signals and Opportunity Score v0

Signals are derived only from current, age-bounded evidence and retain its
evidence ID, type, normalized positive interpretation and interpretation basis,
plus the complete original evidence record (service, source, raw value,
observation and validity window). Simultaneously applicable conflicting evidence is
suppressed, and a signal explicitly carries `live_action_authorized=false`.
Fixture-status signals exist only for offline demonstration and are not
verified product facts. Supported evidence types include discounts, sale end,
coupons, point multipliers, ranking, review counts/ratings, availability,
seasonality and trend relevance. An adapter may populate only fields that its
source contract returns. For example, the current Rakuten item fixture
normalizes price, availability, reviews, affiliate rate, sale window and point
multiplier; it does not invent a discount, coupon or ranking value.

**Field presence is not a positive signal.** One source-neutral value contract
classifies positive, negative, neutral and unsupported values. Unsupported,
unknown, blank-provenance, non-current or conflicted support emits no signal.
The deterministic v0 positive contracts are:

| Evidence kind | Positive value contract |
|---|---|
| Availability | Boolean true, or exactly `available` / `in_stock` after trimming and case normalization; `unavailable` / `out_of_stock` are negative |
| Coupon | Positive numeric discount amount, or a percentage token greater than 0 and at most 100, with an explicit unexpired usage deadline; `none`, `no_coupon`, `not_applicable` are not positive |
| Discount | Numeric percentage greater than 0 and at most 100 |
| Points | Numeric multiplier greater than the ordinary 1-times baseline |
| Ranking | Integer rank 1 through 10 (the explicit top-ten v0 eligibility rule) |
| Reviews | Positive integer review count; numeric rating at least 4 and at most 5 |
| Sale end | ISO datetime text matching its explicit deadline; naive fixture datetime text means UTC, consistent with the existing fixture normalizer |
| Seasonality / trend relevance | Explicit boolean true, or normalized numeric strength greater than 0 and at most 1; arbitrary descriptive text is unsupported |

These are conservative eligibility rules, not predictions of sales or an
inferred closing deadline. Raw evidence remains unchanged. Fixture signals
continue to be explicitly distinguishable from verified source observations.
The public `BuyNowSignal` model enforces this same positive-value/provenance
contract and a non-empty bounded interval even during direct construction or
deserialization. `effective_start` is `valid_from` when supplied, otherwise
`observed_at`; expiry must exceed both this start and the observation time, and
may equal but never exceed an explicit `valid_until`. The interval is [start,
expiry), so equality with the start is rejected and evaluation at expiry is
inactive. A validity start before observation is permitted, while the stronger
observation floor prevents an already-ended signal from being constructed.
Current-time and cross-record conflict checks remain the derivation function's
contextual responsibility; no model validator depends on wall-clock now.

Signals and scoring pass explicit `as_of` and their existing age policy to the
same conflict helper. It checks the entire candidate evidence inventory, not
only cited IDs, and excludes stale, expired, future-observed or not-yet-active
records. Scoring also accepts the known offer inventory through
`evidence_candidates`; the offline demo supplies all its candidates. The scored
candidate is always included, and only siblings with the same product and service
can invalidate its support. Callers holding multiple offers must supply that
inventory; the single-candidate API cannot infer undisclosed evidence.
Conflict-to-support association retains evidence family, so a sibling's unrelated
family cannot invalidate a cited fact merely by reusing its evidence ID.
Each comparison window starts at `valid_from` (or observation), ends
at the earlier of `valid_until` and observation plus configured maximum age,
and uses the same exclusive-end rule. No missing deadline becomes unlimited
runtime support. Without `as_of`, the helper remains a structural history audit
of declared windows; an omitted end has no declared ceiling. The existing
compliance gate keeps this conservative history audit. Conflict output retains
sorted affected IDs and a deterministic contributing observation anchor; it
uses affected IDs to break cross-service ordering ties and does not erase or
replace the original evidence records.

Opportunity Score v0 is a weighted sum, not an ML prediction.
`config/affiliate_phase0.yaml` defines all eight normalized component weights.
Six product-level `ScoreFeature` values are normalized explicit assessments
with evidence IDs; the evaluator validates their factual support, not a
commercial forecast or a claim that a price is cheaper than another offer.
Missing, stale, future-dated, expired, unsupported or conflicted support
zeroes the entire feature, including when only one of several citations fails.
Current price evidence must identify the offer's actual price quote; affiliate
rate evidence uses percentage units and must match the offer's fractional rate.
The component-to-evidence contract is:

| Component | Eligible evidence families |
|---|---|
| commercial_attractiveness | Offer price, discount, usable coupon, enhanced points |
| urgency | Current sale deadline, discount, usable coupon, enhanced points |
| demand | Top-ten ranking, positive review count, explicit trend relevance |
| trust | Positive review count or qualifying review rating |
| affiliate_economics | Positive affiliate rate matching the offer |
| contextual_fit | Exact product-name identity or explicit positive seasonality |

Every citation must have an eligible status, nonblank provenance, comparable
current times and a supported value. Identity can support contextual fit only;
it cannot establish commercial facts or full confidence. Positive numeric
assessment values remain caller assessments in [0, 1] within this contract.

`evidence_confidence` and `freshness` ignore caller-supplied feature values and
are derived instead. Confidence is the fraction of the five factual components
(all six above except contextual fit) whose **positive weighted contribution**
is wholly supported by eligible VERIFIED evidence. It is 0/5 through 5/5:
unused evidence, identity, fixture evidence, rejected features and zero-weight
components cannot increase it. This measures verified contributing-component
coverage, not probabilistic confidence or commercial quality. Freshness uses
the oldest non-identity evidence actually supporting a positive weighted
contribution: `1 - age / configured maximum age`; no such support yields zero.
Weights are not renormalized when data is absent. Every output contains the
component value, weight, weighted contribution, sorted evidence IDs/types and
a validation/derivation basis, including a reason for a zeroed assessment. Invalid or
incomplete weights are rejected. Scores cannot authorize a proposal, link or
post.

## Proposal, compliance and approval

An offline proposal separates canonical message and visual plan from X,
Instagram and Threads caption/disclosure variants. The compliance evaluator
requires an X variant for the initial channel; Instagram and Threads variants
are supported but optional until separately enabled. Every supplied variant
must use exactly `PR` as its disclosure and begin its caption with that marker;
the `FIRST_VIEW` field alone cannot qualify a caption where `PR` is later or
missing. Canonical copy is the ordered join of typed claims, with the verified
product name prefixed to each non-identity claim, every supplied
caption must be exactly `PR` plus that copy, and any visible headline or
annotation must exactly equal one of those claims. Each displayed product name
must also match its own verified product-identity evidence. Claims bind one
evidence record of the same declared type and product. For example, a sale-end claim
must contain the exact supported end time; missing deadlines are rejected.
Freeform promotional copy is rejected because it cannot be tied to evidence.
Destination URL evidence must match the exact candidate item and service and
remain fresh.

Compliance also fails closed on missing per-product verified destinations,
missing disclosure, unsupported/stale claims, stale displayed prices or
promotion claims, conflicting facts, unknown rights/provenance, altered
product appearance, category-mismatched/non-primary/repeated scenes, duplicate
proposal digests and missing/future/mismatched Human Review. Scene evaluation
requires the caller to supply recent scene fingerprints; an omitted history
does not pass. Phase 0 has no persisted scene history, so callers must provide
it from an authorized future source before reusing this evaluator for a series.

The proposal digest covers the proposal and every referenced product/evidence
record. An Affiliate Phase 0 `HumanApproval` must wrap an `APPROVE`
`ReviewDecision` whose existing `reviewer_note` begins with
`Affiliate Phase 0 content SHA-256: <64 lowercase hex characters>` for that
exact digest. This binds the digest to the recorded review decision without a
schema migration; an older approval note cannot be rebound by constructing a
new wrapper. The first note line is reserved for this marker. A change to the
proposal or referenced evidence changes the digest and invalidates an earlier
approval. Even if every offline check passes, this
foundation has no publish adapter, its `can_publish` result remains false and
all live authorities remain false.

Visual provenance distinguishes fixed product assets from generated scene
context. Rights and provenance must be verified before the compliance report
can pass. Every used product asset must also explicitly state whether it is
official and whether transformations are allowed; product appearance must
remain unaltered. Unknown rights or omitted provenance metadata fail closed.
This is metadata validation and cannot inspect image pixels. The fixture
intentionally has unknown rights and uncreated links, so its report is not
ready for approval.

## Revenue and KPI observations

`AffiliateKPIObservation` preserves attribution dimensions for source/service,
platform, account, post, proposal, product, product set, creative format and time
slot. Impressions, clicks, orders, gross revenue, confirmed revenue,
rejected/cancelled revenue and actual costs are nullable when unavailable.
Metrics are null when their denominator or source values are absent (or a
denominator is zero): CTR = clicks / impressions, CVR = orders / clicks, EPC =
confirmed revenue / clicks and revenue per 1,000 impressions = confirmed
revenue / impressions × 1,000. Profit is computed only when both confirmed
revenue and actual costs exist. No attribution or cost data is generated by the
demo.

## Local workflow

Run the deterministic offline walkthrough with
`python -B -m echo.cli affiliate demo` or `echo affiliate demo` outside
PowerShell. It prints ranking and component totals, available signals, the
room-bundle carousel, compliance failures and Rakuyoko unknowns. It does not
create a database or files. Fixtures cover a normal item, missing price,
expired promotion, weak evidence, multiple individually identified items,
unknown visual rights and conflicting evidence.

Focused regressions live in `tests/test_affiliate_foundation.py`; the canonical
offline verifier includes them in its targeted stage and full pytest suite.
