# Project Echo Zero: Affiliate Phase 1 Discovery Foundation

The original Phase 1 Foundation was based on the accepted Phase 0 commit
`9faec201c0285bdb9307993b0bac9460f51131de`. The Phase 1.1 ranked hydration checkpoint
is based on the accepted Phase 1 commit `42a344ae68e67b890f35ec9167a0f53850c33326`.
It implements discovery and guarded live-readonly boundaries. Implementation and synthetic tests authorize no live
requests, credential provisioning, image runtime, publishing or Git mutation.
Project State records the exact checkpoint, measured results and handoff,
including the separately authorized bounded live observation. It supplies no
continuing live authority.

## Official contract reviewed on 2026-09-29

Only public official documentation was browsed. No API endpoint was called.

| API | Version | Fixed HTTPS endpoint | Implemented subset |
|---|---|---|---|
| [Item Search](https://webservice.rakuten.co.jp/documentation/ichiba-item-search) | 2026-07-01 | `https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701` | keyword, genreId, itemCode, shopCode, hits 1..30, page 1..100, validated sort, availability, hasReviewFlag, price bounds |
| [Genre Search](https://webservice.rakuten.co.jp/documentation/ichiba-genre-search) | 2026-07-01 | `https://openapi.rakuten.co.jp/ichibagt/api/IchibaGenre/Search/20260701` | genreId (root 0); ancestors, genre, siblings, children using genreId/nameJa/level |
| [Ranking](https://webservice.rakuten.co.jp/documentation/ichiba-item-ranking) | 2022-06-01 | `https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601` | optional genreId, page 1..34; item rank and raw lastBuildDate; no demographics or period selector |

Shared requests use JSON and formatVersion 2. Flat `items` is normalized; the
legacy capitalized envelope is accepted only when unambiguous. Search requires
an explicit selector; keyword validation uses a conservative 128 UTF-8 byte cap
and supported token lengths. Search pages and price bounds are validated before
transport. Unknown extra response fields are ignored; malformed consumed fields,
ambiguous envelopes and missing item identity fail closed.

Authentication requires applicationId plus accessKey. The adapter sends accessKey
only in the header; affiliateId is optional for Search/Ranking. Credentials come
only from `RAKUTEN_APPLICATION_ID`, `RAKUTEN_ACCESS_KEY`, and optional
`RAKUTEN_AFFILIATE_ID`, after explicit `live_readonly=True` / `--live-readonly`
and `ECHO_RAKUTEN_LIVE_READONLY=1` both pass. The flag is checked again per request,
cache access and retry. Fixture mode loads no environment credentials. Credential
repr/presence are redacted/Boolean; console output excludes names, URLs and bodies.

Official itemUrl may alias affiliateUrl when affiliateId is supplied. Both roles
are preserved separately; no URL is rewritten or fabricated. Missing affiliateId
or missing affiliateUrl never produces an affiliate destination. An authorized
live response can produce verified URL evidence bound to the exact itemCode;
synthetic fixtures retain FIXTURE evidence and unverified typed destinations.
Mocked live-factory tests exercise these contracts with synthetic credentials and
responses; they are not evidence of real Rakuten verification.

HTTP 400/401/403 and malformed data fail immediately; 404 is an explicit empty
result. Ranking can report not-found when too few items exist. Only 429, 500,
503 and timeouts retry, at most three total attempts with bounded backoff.
Source documentation warns against identical URLs in a short interval; one
execution's transport memoizes identical requests and failures without persistence.

The official [Rakuyoko guide](https://rakuyoko.rakuten.co.jp/guide/) describes the
consumer service. No verified developer API or automation contract was found.
Rakuyoko adapter, login, scraper, private endpoint and URL automation stay deferred.

## Layers, bounds and normalization

`models.discovery` contains source-neutral immutable contracts.
`monetization.discovery` consumes a provider Protocol and Phase 0 functions.
`monetization.rakuten` owns official field mappings and credentials.
`monetization.transport` owns GET/JSON I/O. CLI composes these layers; Core,
STEP 1/2/3 and storage remain unchanged. No dependency or persistence is added.

The wire sender uses standard-library HTTPS, exact endpoint allowlisting, no
redirect following, timeouts (default 10s, cap 30s), payload bounds (default 1MiB,
cap 2MiB) and strict JSON (no duplicate keys/nonfinite numbers). Request and error
diagnostics omit values. Discovery defaults to five queries and one page each;
configuration caps queries at ten and pages per query at five. Cache lifetime is
one execution; create a new provider for another execution. No scheduler or
unbounded crawl exists. Generic transport authorization callbacks and injected
senders are trusted-code seams, not a sandbox against malicious callers.

Product identity is service plus official shop:itemCode, with a stable internal
ID. Each source observation retains its own evidence and provenance. Product
dedup never erases Search/Ranking contradictions. Each offer field selects the
latest current known value with its original evidence linkage; a sparse Ranking
record cannot erase a current exact Search quote, stock or destination. Stale
known values do not fill missing current fields. Offers include exact itemPrice,
availability, review count/average and percent-to-ratio affiliateRate; price-range
Ranking records do not create exact quotes. Rank is informational evidence,
not a fabricated sales count. Shop/genre metadata and image references are kept
without treating them as rights or conversion evidence.

Official wall-time fields specify `YYYY-MM-DD HH:MM`, but a timezone was not
verified in the reviewed contract. Raw values are retained. Naive/ambiguous sale
or point windows yield no positive timing claim. Offset-aware bounded times are
supported; lastBuildDate is preserved and parsed only if timezone-aware. This
conservative limitation needs official timezone clarification before live timing
claims. Stale ranking observations cannot replace current offers or poison current
evidence; ambiguous/future rank dates have no positive ranking authority.

## Selection and proposal metadata

Discovery reuses BuyNow semantics, conflict/current-window predicates and score
v0. It supplies six explicit assessments: observed exact price (default .50,
not a discount claim), rank/review demand, review trust, affiliate economics,
active sale/point urgency and named-product contextual fit (default .50).
Evidence confidence and freshness remain derived by Phase 0. Missing/invalid
support is zero; original weights and regressions are preserved.

Top-N defaults to five with minimum score .50. Candidates also need current
exact price and positive availability, no current evidence conflict, and explicit
stock. Sort is score descending then stable product ID. Insufficient candidates
produce fewer items, including zero; there is no weak-product filler. Selected
items can have no verified affiliate destination, which remains visible and
blocks downstream approval. Selection is research metadata, never execution.

Each supported selected item receives a planned overview/detail carousel using
existing visual models. Multi-item RoomBundle requires one explicit shared
lifestyle context, distinct complementary roles and separately verified individual
evidence/destinations. An arbitrary Top-N is not a coherent room bundle. Headlines
use supported product identity; long names or missing source assets do not force
unsupported visuals. Product URLs remain references; all asset rights and
transformation permissions stay UNKNOWN, and generated-context assets are plans
only. No downloads, image generation, likeness/people or imitation is performed.

Compliance reuses PR disclosure, exact price/destination/claim and scene history
checks. Without verified rights and recent-scene history it fails closed.
Human Approval remains required and `can_publish=false`. Nothing is posted.

## Ranked candidate hydration (Phase 1.1)

Official contracts were rechecked on 2026-10-03. Ranking `lastBuildDate` is the
overall ranking's time of last update, not a per-item merchant modification time.
Its parsed value is retained as `ranking_snapshot_at`; the raw string and each
source observation remain available. Ranking values keep their conservative
snapshot applicability anchor. An old snapshot cannot satisfy a current offer
merely because the HTTP response was retrieved now.

The official Item Search contract supports exact `itemCode` lookup. With hydration
enabled, discovery preselects at most five ranked products lacking eligible
current price/availability, ordered by eligible rank then stable service/item
identity. A suitable current Search observation in the same execution avoids
redundant hydration. Each selected item gets one exact lookup, including unavailable
products so a negative availability response remains visible. A different returned
itemCode or multiple records are rejected. Empty/not-found results and incomplete
offers have fixed outcomes; no replacement loop seeks a sixth product. Malformed
responses and transport failures abort acquisition.

Search `observed_at` records when Project Echo observed the returned values, not
when a merchant changed them. Hydrated observations retain their own evidence IDs;
Ranking rank and historical fields are not replaced. The existing field-wise merge,
typed evidence windows and conflict predicates decide applicability. Different
prices with overlapping eligible windows still conflict; only declared expiry or
the existing freshness policy can make an older fact historical. There is no
latest-value or provider-name exception to canonical conflict detection.

Configuration bounds hydration top K and requests to five and all discovery
logical requests to eight. Duplicate intents are memoized within the execution.
Acquisition is sequential; the live transport spaces wire attempts by at least
one second, including internal retries. No pagination is added by hydration.
Generic explicit discovery page settings remain bounded by the total request cap.

Score v0, minimum score .50, weights, confidence, freshness, exact-price and
availability gates are unchanged. Negative/missing hydrated fields do not become
positive support. Human Approval and unknown image rights remain fail-closed;
no product history, persistence, publishing or image rendering is introduced.

The synthetic fixture demonstrates an old Ranking offer plus a current exact
Search response, earning a qualifying score from unchanged legitimate components:

```powershell
python -B -m echo.cli affiliate discover --source ranking --fixture tests/fixtures/affiliate/ranked_hydration.json
```

Ordinary CLI mode remains offline. Live use still requires separate explicit
authority and the process-local live flag. The Phase 1.1 implementation/live gate
may checkpoint only after at least one real candidate qualifies; a zero-yield
runtime stops before staging. VIS-01, CP-01 and CP-02 remain deferred.

## Offline use and deferred runtime

`echo affiliate discover` defaults to `tests/fixtures/affiliate/rakuten_phase1.json`,
containing only synthetic `.invalid` references. `--source genres --genre-id 0`
tests root taxonomy; `--source ranking` tests ranking. `--fixture` can select an
explicit synthetic JSON file; it cannot be combined with live-readonly mode.
`config/affiliate_phase1.yaml` contains bounds/assessments, no credentials.

Next authority remains checkpoint review of the sealed unstaged candidate.
Real runtime, credential provisioning, official timezone clarification, Rakuyoko
integration, persistence/attribution, publication and image rights/runtime need
separate future scope. VIS-01, CP-01 and CP-02 remain deferred as recorded in State.
