# Source & Trend Intelligence (STEP 2)

This document covers everything added in STEP 2: acquiring real
`SourceItem`s from public sources and turning them into `TrendCandidate`s
without any external AI API. For the pipeline this feeds into (SCORE,
CREATE, COMPLIANCE, Human Review), see [ARCHITECTURE.md](ARCHITECTURE.md).

## Pipeline

```
Source Registry -> Fetch -> Normalize -> Deduplicate -> Source Quality
                                                             |
                                                             v
                              Topic/Event Clustering -> Trend Signal Calculation -> TrendCandidate
```

- **`echo.source`** owns everything up to a clean, deduplicated
  `SourceItem` in storage (Source Registry, Fetch, Normalize, Deduplicate).
- **`echo.trend`** + **`echo.brains.RealTrendBrain`** own clustering and
  scoring those `SourceItem`s into `TrendCandidate`s.

## Source lifecycle

1. A source is declared in `config/sources/<vertical>.yaml`
   (`echo.source.config.SourceConfig`) with an id, name, url, `source_type`,
   `reliability_tier`, `vertical`, `language`, `polling_interval` (minutes),
   `primary_source`, and `enabled`.
2. `echo ingest` (or `echo ingest --fixture`) loads `enabled_sources()` for
   a vertical and runs each through `echo.source.ingest.ingest_sources`:
   fetch -> parse (format adapter) -> normalize -> deduplicate -> persist
   to `source_items`. One row per fetch attempt is recorded in
   `source_fetch_runs`; failures are recorded in `source_failures` (see
   "Failure handling" below). One source's failure never stops the others.
3. `echo trends detect` loads persisted `SourceItem`s for a vertical,
   clusters them, scores each cluster, and persists the results as
   `TrendCandidate`s (`trends` table) -- from there STEP 1's pipeline
   (threshold check, CREATE, COMPLIANCE, Human Review) takes over
   unchanged.

A source stays registered even when `enabled: false` -- see "Adding a new
source" for why STEP 2 shipped several sources disabled rather than
guessing at unverified URLs.

## Ingestion upper bounds

Per-source, config-driven caps on `SourceConfig` (Pre-Commit Hardening),
enforced in `echo.source.ingest._apply_source_bounds` -- at the
normalize/ingest boundary, never in a format adapter, which knows nothing
about a source's config:

- `max_items_per_fetch` (default `200`): after normalization, items are
  sorted newest-first by `published_at` and only the first
  `max_items_per_fetch` are kept. Bounds the work one large feed (e.g. a
  full-history blog feed returning over a thousand items) can push through
  dedup/clustering in a single `echo ingest` run.
- `max_item_age_hours` (default `168`, i.e. 7 days): items older than this
  (by `published_at`) are dropped.
- Either bound can be set to `null` in YAML to disable it for that source
  -- see `dummy_fixture` in `config/sources/ai.yaml` for an example (a
  static, fixed-date fixture that must keep working regardless of
  wall-clock time).
- An item whose `published_at` fell back to `retrieved_at` (missing or
  malformed timestamp -- see "Normalization" below) has age 0 at the
  moment it's bounded, so it is never dropped by `max_item_age_hours`;
  the existing "never drop for a bad date" fallback policy is preserved.
- Observability: `SourceIngestReport` (per source) and `IngestReport`
  (totals) carry `items_fetched`, `items_normalized`, `items_age_filtered`,
  `items_item_limit_filtered`, `items_deduplicated`, `items_stored` --
  printed by `echo ingest` and recorded per fetch run in
  `source_fetch_runs` (see `docs/DATA_MODEL.md`).

## Reliability tiers

`echo.models.enums.ReliabilityTier`: `tier_a` (official/primary),
`tier_b` (high-quality secondary), `tier_c` (discovery-only). Mapped to a
numeric weight in `echo.source.reliability.TIER_SCORES` (A=1.0, B=0.7,
C=0.4). This mapping is generic -- it is never keyed by a company name in
code, only by tier, and the tier itself is assigned per source in the
YAML registry.

## Deduplication

`echo.source.dedup`:

- **URL canonicalization**: lowercases scheme/host, drops default ports
  and the fragment, strips known tracking params (`utm_*`, `gclid`,
  `fbclid`, `ref`, ...), sorts remaining query params.
- **Content fingerprint**: `sha256` of normalized title + a normalized
  content prefix -- catches syndicated/mirrored articles at different
  URLs with identical text.
- **Exact duplicate**: canonical URL already seen, or fingerprint already
  seen.
- **Near duplicate**: title token-overlap (Jaccard similarity, see
  `echo.core.text`) at or above `Deduplicator`'s configurable threshold
  (default 0.8), when neither exact-match check fired.
- `Deduplicator` can be seeded with previously-seen canonical
  URLs/fingerprints (`EchoRepository.list_known_canonical_urls` /
  `list_known_content_fingerprints`) so duplicates are caught across
  ingest runs, not just within one batch.

No ML/embeddings -- deliberately deterministic and unit-testable (see
`tests/test_dedup.py`).

## Clustering

`echo.trend.clustering.cluster_source_items`: greedy single-pass grouping
using title token-overlap + shared capitalized "entity-like" terms (a
crude proper-noun heuristic, not NER) + a time-proximity window
(`TrendSignalConfig.cluster_time_window_hours`). No embeddings/LLM in
STEP 2; the function's signature (`list[SourceItem], TrendSignalConfig ->
list[Cluster]`) is deliberately stable so a future step can swap the
similarity function for an embedding-based one without touching callers.

## Trend score definitions

All scores are `float` in `[0.0, 1.0]` -- STEP 2 never mixes a 0-100 scale
into the codebase. Each is its own small, documented, independently
testable module under `echo.trend/`:

| Score | Module | Definition |
|---|---|---|
| `freshness` | `freshness.py` | Exponential decay from the cluster's earliest item's `published_at`; halves every `freshness_half_life_hours` (default 6h). |
| `velocity` | `velocity.py` | Time-windowed (15m/1h/6h/24h, configurable), recency-weighted item count / `velocity_saturation`. An item older than every window contributes 0 -- volume from *old* articles alone cannot produce high velocity. |
| `novelty` | `novelty.py` | 1.0 minus a penalty proportional to the highest title-token similarity against `TrendCandidate`s detected within `novelty_lookback_hours`. This is the signal a human reviewer's `DUPLICATE_TOPIC` / `NO_NEW_INFORMATION` judgement can be informed by -- STEP 2 never assigns a `RejectReason` itself. |
| `relevance` | `relevance.py` | Keyword matches against `VerticalConfig.topic_keywords` / `relevance_saturation_matches`, returned with the list of matched topic ids. |
| `source_quality` | `source_quality.py` | Mean reliability score across the cluster's *distinct* `source_key`s (so one low-tier source posting 5 near-identical stories can't drown out a single tier-A confirmation). |
| `source_count` | (on `TrendCandidate` directly) | Total `SourceItem` count in the cluster. |
| `cross_source_confirmation` | `cross_source.py` | `(distinct_source_count - 1) / (cross_source_saturation - 1)`, clamped to `[0, 1]` -- a single contributing source scores 0. |

Tunable defaults live in `echo.trend.signal_config.TrendSignalConfig`; a
few of the most likely-to-need-tuning knobs are also overridable via env
var through `Settings.trend_signal_config()` (see `.env.example`).

## Trend persistence guard

Running `echo trends detect` repeatedly over unchanged `SourceItem`s
re-detects the same clusters every time (by design -- STEP 2 does no
storage-level cluster deduplication). Without a guard this would grow the
`trends` table without bound. Instead (Pre-Commit Hardening):
`echo.trend.service.partition_trends_by_novelty(candidates,
trend_persistence_novelty_threshold)` splits detected candidates into
"persist" (`novelty >= threshold`) and "skip" (`novelty < threshold`,
default threshold `0.10`, overridable via
`ECHO_TREND_PERSISTENCE_NOVELTY_THRESHOLD` /
`TrendSignalConfig.trend_persistence_novelty_threshold`) -- only the
former are written to `trends`. This works because `novelty` is already
computed against recently detected trends (see "novelty" above), so a
near-exact repeat naturally scores near 0 on the second run.

Properties:

- No already-persisted `trends` row is ever modified or deleted -- a
  skip is purely "don't write a new row", never a mutation.
- If new `SourceItem`s later push a topic's novelty back up (genuinely
  new information), it becomes eligible to persist again on a later run.
- No crash: `trend_id`/`trace_id` are always freshly allocated per
  detected candidate regardless of the persist/skip decision, so there is
  no `UNIQUE` collision risk either way.
- `echo trends detect` still *detects* and prints every cluster (skipped
  ones are marked `[SKIPPED -- already-known, low novelty, not
  persisted]`) and reports a skipped count -- only SQLite persistence is
  gated, not detection itself.
- Known trade-off: `RealTrendBrain.detect()` (unchanged, so as not to
  touch the `TrendBrain` Protocol shared with STEP 1's `DummyTrendBrain`)
  still allocates a `trace_id` -- which consumes a monotonic
  `trace_sequences` slot -- for every detected cluster, including ones
  that end up skipped. Skipped candidates therefore leave gaps in the
  trace-ID sequence; this is a soft, accepted cost (comparable to
  auto-increment gaps in any database), not a correctness issue.

## Relevance is config-driven, not hard-coded

`RealTrendBrain` never imports `echo.verticals` and never contains a
vertical-specific word. Topic keywords/aliases (e.g. what counts as
"LLM"-relevant) come from `VerticalConfig.topic_keywords`
(`config/verticals/<id>.yaml`), loaded by the CLI and passed into
`RealTrendBrain`'s constructor. Adding or renaming keywords is a config
change, never a code change -- see `docs/DEVELOPMENT_RULES.md` rule 2.

## Failure handling

`echo.source.http_client.fetch` never raises: every failure (timeout,
connection error, HTTP status >= 400, disallowed content-type, oversized
response) becomes a `FetchOutcome(ok=False, error_type=..., message=...)`.
`echo.source.ingest` catches format/adapter errors the same way. One
source's failure is recorded to `source_failures` and never stops
ingestion of the remaining sources in the same `echo ingest` run. Retries
are bounded (`max_retries`, default 2 => 3 total attempts) and only apply
to network-level failures -- an HTTP status error is never retried.

## Redirect scheme security

`echo.source.http_client` only ever opens `http`/`https` URLs -- enforced
explicitly in code (Pre-Commit Hardening), not left to whatever a given
Python version's `urllib` defaults happen to allow for other schemes
(observed to differ across versions):

- `fetch()` rejects an unsupported *initial* URL scheme (e.g. `ftp://`,
  `file://`) immediately, before any I/O, as `error_type="invalid_url"`.
- Every redirect hop is scheme-checked by
  `_SchemeRestrictedRedirectHandler.redirect_request`, which refuses to
  follow a redirect to anything other than `http`/`https` (e.g. a
  compromised or malicious server 302-ing to `file:///etc/passwd` or a
  `data:`/`javascript:` URI) and surfaces it as the same `http_status`
  failure `fetch()` already handles for an ordinary non-2xx redirect
  target. A `http -> https` (or `https -> http`) redirect is unaffected.
- As defense in depth, the opener `fetch()` uses (installed once, at
  import time, as the process-wide default opener via
  `urllib.request.install_opener`) has no `FTPHandler`/`FileHandler` at
  all -- it cannot open a `file://`/`ftp://` URL even if the scheme check
  above had a bug. `echo.source` is the only place in this codebase that
  makes HTTP requests, so installing this process-wide is the intended
  policy, not an incidental side effect.
- Existing timeout/retry-bound/response-size-cap/content-type-allowlist
  behavior, and the monkeypatched-`urlopen` offline test strategy (see
  "Network tests vs. offline tests" below), are unchanged.

## Adding a new source

1. Verify the feed URL yourself with a single, plain HTTP request (no
   bypassing robots/WAF/rate limits, no login). `curl -sS -L --max-time 10
   -H "User-Agent: Project-Echo/0.1" "<url>"` and confirm it returns
   `200` with actual RSS/Atom/JSON content.
2. Add an entry to `config/sources/<vertical>.yaml` with `enabled: true`
   only if step 1 succeeded. If you can't verify it (blocked, wrong path,
   requires auth), add it with `enabled: false` and a comment recording
   what you observed and when -- don't guess a URL and don't silently
   leave it unregistered either; a disabled, documented entry is the
   honest STEP 2 default (see the AI vertical registry for examples of
   both).
3. Pick a `reliability_tier` based on whether it's an official/primary
   source (A), a high-quality secondary source (B), or discovery-only (C).
4. Run `python scripts/smoke_test_sources.py --vertical <id>` to confirm
   it fetches and parses through the real pipeline.
5. If the source needs a new fetch mechanism (not RSS/Atom/JSON/a local
   fixture), add a `SourceType` member (`echo.models.enums`) and one
   adapter function + `ADAPTERS` entry in `echo.source.adapters` -- never
   a Core change.

## Network tests vs. offline tests

`pytest` (`tests/`) never makes a real network call. Every HTTP-dependent
code path is tested with a monkeypatched `urllib.request.urlopen`
(`tests/test_http_client.py`) or a monkeypatched `echo.source.ingest.fetch`
(`tests/test_ingest.py`), and format adapters are tested against static
fixture files under `tests/fixtures/`. `echo ingest --fixture` and the
`STATIC_FIXTURE` source type give a fully offline, reproducible path
through the whole pipeline for demos.

Real-source connectivity is checked two other ways, neither of which is
part of `pytest`:

- `echo sources check` -- one real request per *enabled* source, for
  interactive/manual use.
- `python scripts/smoke_test_sources.py` -- the same, as a standalone
  script; reports per-source success/failure and always exits 0 (an
  external source outage is not a code defect and must never fail CI).
