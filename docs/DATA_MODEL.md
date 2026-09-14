# Data Model

All models are Pydantic (`echo.models`). Enums are `str, Enum` subclasses
in `echo.models.enums` so they serialize as plain strings in SQLite and
JSON. Every model that represents a stage of the pipeline carries
`trace_id` -- see [ARCHITECTURE.md](ARCHITECTURE.md#traceability).

## SourceItem

Raw material discovered from the outside world. Immutable (`frozen=True`).

| field | type | notes |
|---|---|---|
| source_id | str | unique per item |
| source_key | str | STEP 2: `SourceConfig.id` this item came from -- the Source Registry entry, not a display name |
| url | HttpUrl | validated |
| source_name | str | |
| title | str | |
| published_at | datetime | |
| retrieved_at | datetime | |
| content | str | |
| language | str | ISO-ish code, default `"en"` |
| vertical | str | vertical id, e.g. `"ai"` |

## TrendCandidate

Output of DISCOVER.

| field | type | notes |
|---|---|---|
| trend_id | str | |
| trace_id | str | `ECHO-<VERTICAL>-<YYYYMMDD>-<seq>` |
| topic | str | |
| keywords | list[str] | |
| sources | list[str] | `SourceItem.source_id` references |
| detected_at | datetime | |
| velocity, novelty, relevance | float [0,1] | |
| vertical | str | |
| freshness | float [0,1] | STEP 2, default 0.5 -- see docs/SOURCE_INTELLIGENCE.md |
| source_quality | float [0,1] | STEP 2, default 0.5 |
| source_count | int >= 1 | STEP 2, default 1 -- total SourceItems in the cluster |
| cross_source_confirmation | float [0,1] | STEP 2, default 0.0 -- distinct-source diversity, not raw count |

The STEP 2 fields all default so a `TrendCandidate` built the STEP 1 way
(`DummyTrendBrain`, one item per candidate) still validates and persists
unchanged.

## ResearchPacket

Output of RESEARCH.

| field | type | notes |
|---|---|---|
| research_id | str | |
| trend_id | str | |
| trace_id | str | |
| summary | str | |
| key_facts | list[str] | |
| sources | list[str] | |
| source_quality | float [0,1] | |
| conflicting_information | bool | |
| confidence | float [0,1] | |
| claims | list[ResearchClaim] | STEP 3, default `[]` |
| evidence | list[EvidenceItem] | STEP 3, default `[]` |
| conflicts | list[ConflictRecord] | STEP 3, default `[]` |
| source_assessments | list[SourceAssessment] | STEP 3, default `[]` |
| primary_source_present | bool | STEP 3, default `false` |
| independent_source_count | int >= 0 | STEP 3, default `0` -- distinct `source_key` count, see docs/RESEARCH_INTELLIGENCE.md "Source independence" |
| research_status | ResearchStatus | STEP 3, default `ready` -- `ready` \| `needs_more_sources` \| `conflicted` \| `low_confidence` \| `insufficient_evidence` |
| researched_at | datetime \| None | STEP 3, default `None` (unset for STEP 1 `DummyResearchBrain` output) |

The STEP 3 fields all default so a `ResearchPacket` built the STEP 1 way
(`DummyResearchBrain`) still validates and persists unchanged.

Packet `source_quality`, `primary_source_present` and `independent_source_count`
describe sources contributing actual evidence. `sources` and `source_assessments`
retain the selected pool, including zero-evidence entries for provenance. No
database schema change is needed for this distinction.

## ResearchClaim (STEP 3)

One extracted fact, grouped from every evidence sentence found to be
about it -- claim-level, not article-level. Not persisted standalone;
lives under a `ResearchPacket.claims` / the `research_claims` table.

| field | type | notes |
|---|---|---|
| claim_id | str | |
| text, normalized_text | str | representative surface text (earliest-published fact candidate in the group) |
| claim_type | str | free-form; STEP 3 always uses `"general"` |
| evidence_ids | list[str] | `EvidenceItem.evidence_id` references |
| supporting_source_ids | list[str] | distinct `SourceConfig.id` agreeing |
| contradicting_source_ids | list[str] | distinct `SourceConfig.id` conflicting |
| confidence | float [0,1] | |
| status | ClaimStatus | `confirmed` \| `supported` \| `single_source` \| `unverified` \| `conflicted` -- see docs/RESEARCH_INTELLIGENCE.md "Claim status ladder" |

## EvidenceItem (STEP 3)

One piece of traceable evidence backing a claim -- always resolvable back
to the `SourceItem` (and URL) it came from.

| field | type | notes |
|---|---|---|
| evidence_id | str | |
| source_item_id | str | `SourceItem.source_id` this evidence came from |
| source_key | str | `SourceConfig.id` |
| url | str | original `SourceItem.url` -- provenance, never re-fetched |
| title | str | |
| published_at | datetime | |
| excerpt | str | bounded to `ResearchConfig.max_excerpt_length` (default 240 chars) -- never a full article body |
| is_primary_source | bool | default `false` |
| reliability_tier | ReliabilityTier | |

## ConflictRecord (STEP 3)

A detected (or potential) contradiction between two pieces of evidence
for the same claim -- see docs/RESEARCH_INTELLIGENCE.md "Conflict
detection".

| field | type | notes |
|---|---|---|
| conflict_id | str | |
| claim_id | str \| None | `ResearchClaim` this conflict was found within |
| evidence_id_a, evidence_id_b | str | |
| source_key_a, source_key_b | str | |
| conflict_type | str | `status_keyword` \| `negation` \| `numeric` \| `date` |
| reason | str | human-readable |
| severity | ConflictSeverity | `potential` \| `minor` \| `major` |

## SourceAssessment (STEP 3)

Per-`source_key` rollup of what a Research run saw for one source.

| field | type | notes |
|---|---|---|
| source_key, source_name | str | |
| reliability_tier | ReliabilityTier | |
| reliability_score | float [0,1] | |
| is_primary_source | bool | default `false` |
| item_count | int >= 0 | SourceItems selected from this source |
| evidence_count | int >= 0 | EvidenceItems contributed by this source |

## OpportunityScore

Output of SCORE; `final_score` drives the threshold gate.

| field | type |
|---|---|
| score_id, trend_id, trace_id | str |
| attention_score, relevance_score, novelty_score, timeliness_score, source_score, monetization_score, risk_score, final_score | float [0,1] |
| scored_at | datetime |

## ContentDraft

Output of CREATE, annotated by COMPLIANCE.

| field | type | notes |
|---|---|---|
| draft_id, trend_id, trace_id | str | |
| content_type | ContentType | `breaking` \| `explain` \| `signal` \| `evergreen` |
| hook, body | str | |
| cta | str \| None | |
| sources | list[str] | |
| confidence | float [0,1] | |
| generated_at | datetime | |
| vertical | str | |
| compliance_risk_score | float [0,1] | set by COMPLIANCE, default 0.0 |
| compliance_flags | list[str] | set by COMPLIANCE, default `[]` |

`compliance_*` fields live on the draft (rather than a separate table) so
the Human Review Gate always sees compliance context when deciding --
compliance never auto-rejects.

## ReviewDecision

Output of the Human Review Gate. Persisted for **every** reviewed draft,
including REJECT/SKIP.

| field | type | notes |
|---|---|---|
| review_id, draft_id, trace_id | str | |
| decision | DecisionType | `approve` \| `reject` \| `edit` \| `skip` |
| review_reason | RejectReason \| None | **required when decision is `reject`** (enforced by a model validator) |
| reviewer_note | str \| None | free-text, e.g. detail for `OTHER` |
| reviewed_at | datetime | |

`RejectReason`: `LOW_SOURCE_CONFIDENCE`, `DUPLICATE_TOPIC`, `TOO_LATE`,
`LOW_RELEVANCE`, `LOW_VALUE`, `HIGH_COMPLIANCE_RISK`, `CLICKBAIT_ONLY`,
`NO_NEW_INFORMATION`, `OTHER`.

## PublishedPost

Model + storage table only in STEP 1 -- no code path writes to it yet (no
X API integration exists).

| field | type |
|---|---|
| post_id, draft_id, trace_id, x_post_id | str |
| published_at | datetime |

## PerformanceSnapshot

Model + storage table only in STEP 1 -- no collector exists yet.

| field | type |
|---|---|
| snapshot_id, post_id, trace_id | str |
| captured_at | datetime |
| impressions, likes, replies, reposts, bookmarks, profile_visits, followers_gained, link_clicks | int >= 0 |

## ComplianceResult

Internal-only output of a `ComplianceBrain` (`echo.models.compliance`),
not persisted as its own table -- see `ContentDraft.compliance_*`.

| field | type |
|---|---|
| draft_id, trace_id | str |
| risk_score | float [0,1] |
| flags | list[str] |

## SourceConfig (STEP 2)

One entry per `config/sources/<vertical>.yaml` item (`echo.source.config`).
Not itself persisted to SQLite -- it's config, loaded fresh each run via
`echo.source.registry.load_source_registry`.

| field | type | notes |
|---|---|---|
| id | str | stable registry key, e.g. `"nvidia_blog"` -- this is `SourceItem.source_key` |
| name | str | human-readable display name |
| url | HttpUrl | |
| source_type | SourceType | `rss` \| `atom` \| `json` \| `static_fixture` |
| enabled | bool | default `true` |
| vertical | str | |
| reliability_tier | ReliabilityTier | `tier_a` (official) \| `tier_b` (secondary) \| `tier_c` (discovery-only) |
| language | str | default `"en"` |
| polling_interval | int | minutes, default 60 |
| primary_source | bool | default `false` |
| max_items_per_fetch | int \| None | Pre-Commit Hardening, default `200`. Cap on items accepted per fetch (newest by `published_at` kept), applied at the normalize/ingest boundary. `None` disables the cap. Per-source override. |
| max_item_age_hours | int \| None | Pre-Commit Hardening, default `168` (7 days). Items older than this (by `published_at`, or `retrieved_at` when the timestamp was missing/malformed) are dropped. `None` disables the bound. Per-source override. |

## SQLite schema

One table per persisted model, plus `trace_sequences` for atomic trace-ID
sequence allocation, plus three STEP 2 acquisition-audit tables and three
STEP 3 research-detail tables:

```
trace_sequences(vertical, seq_date, last_seq)          PK (vertical, seq_date)
trends(trend_id, trace_id, vertical, topic, ..., freshness, source_quality,
       source_count, cross_source_confirmation)        PK trend_id, trace_id UNIQUE
research(research_id, trend_id, trace_id, ..., source_assessments_json,
         primary_source_present, independent_source_count,
         research_status, researched_at)                PK research_id, FK trend_id -> trends
scores(score_id, trend_id, trace_id, ...)                PK score_id, FK trend_id -> trends
drafts(draft_id, trend_id, trace_id, ..., compliance_*)  PK draft_id, FK trend_id -> trends
reviews(review_id, draft_id, trace_id, decision, ...)     PK review_id, draft_id UNIQUE, FK draft_id -> drafts
published_posts(post_id, draft_id, trace_id, ...)         PK post_id, FK draft_id -> drafts
performance(snapshot_id, post_id, trace_id, ...)          PK snapshot_id, FK post_id -> published_posts

-- STEP 2 --
source_items(source_item_id, source_key, vertical, url, canonical_url,
             content_fingerprint, ...)                    PK source_item_id, UNIQUE canonical_url
source_fetch_runs(run_id, source_key, vertical, started_at,
                   finished_at, status, items_fetched,
                   items_normalized, items_age_filtered,
                   items_item_limit_filtered,
                   items_deduplicated)                     PK run_id
source_failures(failure_id, source_key, vertical, occurred_at,
                 stage, error_type, message)                PK failure_id

-- STEP 3 --
research_claims(claim_id, research_id, text, normalized_text, claim_type,
                 evidence_ids_json, supporting_source_ids_json,
                 contradicting_source_ids_json, confidence,
                 status)                                    PK claim_id, FK research_id -> research
research_evidence(evidence_id, research_id, source_item_id, source_key,
                   url, title, published_at, excerpt,
                   is_primary_source, reliability_tier)     PK evidence_id, FK research_id -> research
research_conflicts(conflict_id, research_id, claim_id, evidence_id_a,
                    evidence_id_b, source_key_a, source_key_b,
                    conflict_type, reason, severity)         PK conflict_id, FK research_id -> research
```

`save_research` persists the `research` row plus every claim/evidence/
conflict it carries in one connection. Like `save_trend`, there is never
an UPDATE path for claims/evidence/conflicts -- their ids are always
freshly allocated (`echo.core.ids.IdFactory`), so a re-run of research for
the same trend produces an entirely new `research_id` and its own fresh
child rows, never mutating a prior run's (`INSERT ... ON CONFLICT DO
NOTHING`). `EchoRepository.get_research(research_id)` returns a fully
hydrated `ResearchPacket` (claims/evidence/conflicts attached);
`get_research_by_trend(trend_id)` returns the latest run.

List/dict-valued fields (`keywords`, `sources`, `key_facts`,
`compliance_flags`) are stored as JSON text columns. All SQL lives in
`echo.storage` -- see [ARCHITECTURE.md](ARCHITECTURE.md#storage).

The **Human Review Gate queue** (`echo review`) is computed, not stored: it
is every row in `drafts` with no matching row in `reviews`
(`EchoRepository.list_drafts_pending_review`).

### Schema migration

`echo.storage.db._migrate_schema` additively upgrades any older database
in place via `ALTER TABLE ... ADD COLUMN`, guarded by checking
`PRAGMA table_info(<table>)` first per table (SQLite has no `ADD COLUMN IF
NOT EXISTS`). New tables use `CREATE TABLE IF NOT EXISTS` in `SCHEMA`
directly. This runs every `init_db()` call and is a no-op once the
columns/tables exist. Nothing is ever dropped or renamed. Three
generations of additive changes exist so far:

- The `trends` table's four STEP 2 columns (`freshness`, `source_quality`,
  `source_count`, `cross_source_confirmation`).
- The `source_fetch_runs` table's two Pre-Commit Hardening columns
  (`items_age_filtered`, `items_item_limit_filtered`), added when the
  ingestion upper bounds (above) were introduced.
- STEP 3: the `research` table's five new columns
  (`source_assessments_json`, `primary_source_present`,
  `independent_source_count`, `research_status`, `researched_at`), plus
  the three new `research_claims` / `research_evidence` /
  `research_conflicts` tables.

A database created by an older version of this schema upgrades in place
the next time `echo init` runs against it, in every case.
