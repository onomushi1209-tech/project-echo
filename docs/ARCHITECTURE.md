# Architecture

## Core vs. Vertical

Project Echo's central design constraint: **Echo Core knows nothing about
any specific vertical.** A vertical (AI, Tech, Crypto, Business,
Entertainment, ...) is defined entirely by:

1. A YAML file under `config/verticals/<id>.yaml`, validated against
   `echo.verticals.base.VerticalConfig`.
2. Optional dummy/fixture data and helper code under
   `echo.verticals.<id>` (e.g. `echo.verticals.ai`).
3. A set of "brain" implementations satisfying the Protocols in
   `echo.core.interfaces` (STEP 1 ships only dummy brains, shared across
   verticals, under `echo.brains`).

Nothing in `echo.core`, `echo.trend`, `echo.research`, `echo.scoring`,
`echo.content`, `echo.compliance`, or `echo.review` may import from
`echo.verticals` or branch on a vertical id. The only thing that crosses
that boundary is data: a `vertical: str` field on the models, and
`VerticalConfig` objects loaded at the edges (CLI, future scheduler).

## Package layout

```
src/echo/
  core/         Vertical-agnostic engine: trace IDs, ID allocation, brain
                Protocols, the pipeline orchestrator.
  brains/       Swappable stage logic. STEP 1 ships deterministic dummy
                implementations only -- no external AI APIs.
  trend/        DISCOVER stage service (thin: brain call + persistence).
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
  cli.py        Typer CLI: `echo init` / `echo demo` / `echo review`.

tests/          pytest suite.
data/           SQLite database file lives here (gitignored).
config/verticals/  Vertical YAML configs (e.g. ai.yaml).
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
- Implement `echo.performance`, `echo.audience`, `echo.monetization`, and
  `echo.memory` once their steps are scoped; the models and storage tables
  they'll write to already exist (`PublishedPost`, `PerformanceSnapshot`).
