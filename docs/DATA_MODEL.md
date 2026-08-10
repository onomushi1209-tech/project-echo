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
sequence allocation, plus three STEP 2 acquisition-audit tables:

```
trace_sequences(vertical, seq_date, last_seq)          PK (vertical, seq_date)
trends(trend_id, trace_id, vertical, topic, ..., freshness, source_quality,
       source_count, cross_source_confirmation)        PK trend_id, trace_id UNIQUE
research(research_id, trend_id, trace_id, ...)          PK research_id, FK trend_id -> trends
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
```

List/dict-valued fields (`keywords`, `sources`, `key_facts`,
`compliance_flags`) are stored as JSON text columns. All SQL lives in
`echo.storage` -- see [ARCHITECTURE.md](ARCHITECTURE.md#storage).

The **Human Review Gate queue** (`echo review`) is computed, not stored: it
is every row in `drafts` with no matching row in `reviews`
(`EchoRepository.list_drafts_pending_review`).

### STEP 2 schema migration

`echo.storage.db._migrate_schema` additively upgrades any older database
in place via `ALTER TABLE ... ADD COLUMN`, guarded by checking
`PRAGMA table_info(<table>)` first per table (SQLite has no `ADD COLUMN IF
NOT EXISTS`). This runs every `init_db()` call and is a no-op once the
columns exist. Nothing is ever dropped or renamed. Two generations of
additive columns exist so far:

- The `trends` table's four STEP 2 columns (`freshness`, `source_quality`,
  `source_count`, `cross_source_confirmation`).
- The `source_fetch_runs` table's two Pre-Commit Hardening columns
  (`items_age_filtered`, `items_item_limit_filtered`), added when the
  ingestion upper bounds (above) were introduced.

A database created by an older version of this schema upgrades in place
the next time `echo init` runs against it, in either case.
