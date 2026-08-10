# Architecture

## Core vs. Vertical

Project Echo's central design constraint: **Echo Core knows nothing about
any specific vertical.** A vertical (AI, Tech, Crypto, Business,
Entertainment, ...) is defined entirely by:

1. A YAML file under `config/verticals/<id>.yaml`, validated against
   `echo.verticals.base.VerticalConfig` -- including, since STEP 2,
   `topic_keywords` (per-topic keyword/alias lists used for relevance
   scoring).
2. A YAML file under `config/sources/<id>.yaml` (STEP 2), validated
   against `echo.source.config.SourceConfig` -- the vertical's Source
   Registry.
3. Optional dummy/fixture data and helper code under
   `echo.verticals.<id>` (e.g. `echo.verticals.ai`).
4. A set of "brain" implementations satisfying the Protocols in
   `echo.core.interfaces` (`echo.brains`). STEP 1 shipped only dummy
   brains; STEP 2 adds `RealTrendBrain`, which is still not vertical-
   specific in code -- all vertical/source data is injected into it at
   construction time (see "Source & Trend Intelligence" below).

Nothing in `echo.core`, `echo.trend`, `echo.research`, `echo.scoring`,
`echo.content`, `echo.compliance`, or `echo.review` may import from
`echo.verticals` or branch on a vertical id. The only thing that crosses
that boundary is data: a `vertical: str` field on the models, and
`VerticalConfig`/`SourceConfig` objects loaded at the edges (CLI, future
scheduler). `echo.brains` and `echo.source` are the two places allowed to
translate that config-driven data into behavior.

## Package layout

```
src/echo/
  core/         Vertical-agnostic engine: trace IDs, ID allocation, brain
                Protocols, the pipeline orchestrator, shared text utils
                (echo.core.text, used by dedup/clustering/relevance).
  brains/       Swappable stage logic. DummyTrendBrain (STEP 1) and
                RealTrendBrain (STEP 2, source-intelligence-aware) both
                satisfy the same TrendBrain Protocol -- no external AI
                APIs in either.
  source/       STEP 2: Source Registry, Fetch, Normalize, Deduplicate --
                everything up to a clean SourceItem in storage. See
                docs/SOURCE_INTELLIGENCE.md.
  trend/        DISCOVER stage service (thin: brain call + persistence)
                *plus* the STEP 2 signal algorithm modules RealTrendBrain
                composes: clustering, freshness, velocity, novelty,
                relevance, source_quality, cross_source. Each is
                independent and individually testable.
  research/     RESEARCH stage service.
  scoring/      SCORE stage service + the threshold gate.
  content/      CREATE stage service.
  compliance/   COMPLIANCE stage service (informational only -- see
                docs/DEVELOPMENT_RULES.md).
  review/       Human Review Gate service (APPROVE/REJECT/EDIT/SKIP).
  performance/  Reserved for a future step (post-performance ingestion).
  audience/     Reserved for a future step.
  monetization/ Reserved for a future step.
  memory/       Reserved for a future step (long-term learning).
  verticals/    Vertical registry + per-vertical fixtures (e.g. ai/).
  models/       Pydantic data models shared by every package above.
  storage/      SQLite schema + repository. All SQL lives here.
  config/       Env-based settings (echo.config.settings).
  cli.py        Typer CLI: `echo init` / `echo demo` / `echo review` /
                `echo sources` / `echo ingest` / `echo trends`.

tests/          pytest suite (fully offline -- no network access).
scripts/        Standalone scripts not run by pytest, e.g.
                smoke_test_sources.py (real-source connectivity check).
data/           SQLite database file lives here (gitignored).
config/verticals/  Vertical YAML configs (e.g. ai.yaml).
config/sources/    Source Registry YAML configs (e.g. ai.yaml), STEP 2.
docs/           This documentation.
```

## Pipeline

```
DISCOVER -> RESEARCH -> SCORE -> threshold check -> CREATE -> COMPLIANCE -> (queued for) HUMAN REVIEW
```

`echo.core.pipeline.EchoPipeline` sequences this by calling into the
per-stage service modules, which each do exactly two things: call the
injected brain, and persist the result via `EchoRepository`. Each stage is
independently swappable:

- Swap a **brain** (e.g. replace `DummyResearchBrain` with a real one) by
  implementing the matching Protocol in `echo.core.interfaces` and passing
  it into `PipelineBrains` -- no change to `echo.core.pipeline` or any
  stage service required.
- Swap a **stage's orchestration** (e.g. add caching, retries) by editing
  only that stage's `service.py` -- other stages are unaffected.

The threshold check sits between SCORE and CREATE: if
`OpportunityScore.final_score` is below `PipelineDependencies.score_threshold`,
the pipeline stops for that item (trend/research/score are still persisted
for audit purposes) and CREATE/COMPLIANCE never run.

COMPLIANCE never rejects content on its own -- it only annotates the draft
(`compliance_risk_score`, `compliance_flags`). The Human Review Gate
(`echo.review`) is the only place a piece of content is ever finally
approved, rejected, edited, or skipped, and that decision is always made by
a human via `echo review decide`.

## Source & Trend Intelligence (STEP 2)

DISCOVER's input (`SourceItem`s) can now come from real sources, not just
`echo.verticals.ai.dummy_data`. See
[SOURCE_INTELLIGENCE.md](SOURCE_INTELLIGENCE.md) for the full pipeline
(Source Registry -> Fetch -> Normalize -> Deduplicate -> Clustering ->
Trend Signal Calculation), reliability tiers, dedup strategy, and how to
add a new source. In architectural terms, the only things that changed:

- `echo.source` is a new package, analogous in spirit to the stage
  service packages (thin orchestration + `EchoRepository` calls) but for
  acquisition rather than a pipeline stage.
- `RealTrendBrain` (`echo.brains`) satisfies the *same*
  `TrendBrain` Protocol as `DummyTrendBrain` -- `echo.core.pipeline` and
  `echo.trend.service.discover_trends` did not change at all.
  Vertical/source data (topic keywords, source reliability, recent
  trends for novelty comparison) is injected into `RealTrendBrain` at
  construction time by the CLI, so `echo.brains` still never imports
  `echo.verticals` or `echo.storage`.

## Traceability

`echo.core.trace` generates IDs of the form
`ECHO-<VERTICAL>-<YYYYMMDD>-<sequence:06d>` (e.g. `ECHO-AI-20260809-000001`).
One trace ID is assigned per detected trend (in `TrendBrain.detect`, via an
injected `IdFactory`) and is carried unchanged through
`ResearchPacket.trace_id`, `OpportunityScore.trace_id`,
`ContentDraft.trace_id`, and `ReviewDecision.trace_id`. `PublishedPost` and
`PerformanceSnapshot` carry the same field so a future step can join
Trend -> Research -> Score -> Draft -> Review -> Publish -> Performance ->
Memory by trace ID alone.

ID *formatting/parsing* (`format_trace_id` / `parse_trace_id`) is pure and
unit-testable. Sequence *allocation* is injected via a `SequenceProvider`
callable -- production code uses
`EchoRepository.next_trace_sequence` (atomic SQLite upsert), tests use
`InMemorySequenceProvider`.

## Storage

All SQL lives in `echo.storage` (`db.py` for schema/connection,
`repository.py` for queries and model<->row mapping). No other package
issues raw SQL. See [DATA_MODEL.md](DATA_MODEL.md) for the schema itself.

## Extension points for later steps

- Replace entries in `echo.brains` (or add vertical-specific brains) to use
  real AI APIs -- without touching `echo.core`.
- Add a new vertical by adding `config/verticals/<id>.yaml` and, if needed,
  a fixture/data module under `echo.verticals.<id>` -- without touching
  `echo.core`.
- Add a new source (or source type) via `config/sources/<id>.yaml` and,
  if needed, one adapter function in `echo.source.adapters` -- see
  docs/SOURCE_INTELLIGENCE.md "Adding a new source".
- Swap `echo.trend.clustering`'s token-overlap similarity for an
  embedding-based one later without changing its call signature or any
  caller.
- Implement `echo.performance`, `echo.audience`, `echo.monetization`, and
  `echo.memory` once their steps are scoped; the models and storage tables
  they'll write to already exist (`PublishedPost`, `PerformanceSnapshot`).
