# Project Echo

Project Echo is an AI Media Operating System for running independent,
vertical-specific X (Twitter) media accounts. **Echo Core** is the shared,
vertical-agnostic pipeline engine; each **vertical** (AI, Tech, Crypto,
Business, Entertainment, ...) plugs into it through config and swappable
"brains" without Core ever hard-coding vertical-specific behavior.

This repository currently implements **STEP 1: Echo Foundation** and
**STEP 2: Source & Trend Intelligence**. See [Scope](#scope) below for
what is intentionally not implemented yet.

## Quick start

```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env       # optional -- defaults work without it

echo init                  # create the SQLite database

# STEP 1: dummy pipeline demo
echo demo                  # run dummy AI-vertical data through the pipeline
echo review                # see what's waiting for a human decision
echo review decide <draft_id> approve
echo review decide <draft_id> reject --reason low_value --note "..."

# STEP 2: real source ingestion + trend detection
echo sources list           # see the AI vertical's Source Registry
echo sources check          # verify enabled sources are reachable (real network)
echo ingest                 # fetch enabled sources -> normalize -> dedup -> store
echo ingest --fixture       # same, but offline/reproducible (no network)
echo trends detect          # cluster stored SourceItems into TrendCandidates
echo trends list            # list detected TrendCandidates
```

Run tests (fully offline -- no network access required):

```bash
pytest
```

Real-source connectivity smoke test (separate from pytest, makes real
requests): `python scripts/smoke_test_sources.py`

## What's implemented

**STEP 1** -- dummy AI-vertical source data flows through:

```
DISCOVER -> RESEARCH -> SCORE -> threshold check -> CREATE -> COMPLIANCE -> Human Review queue
```

using deterministic, offline stub logic (`echo.brains`) -- there is no
external AI API, no real trend scraping, and nothing is ever posted to X.
Every stage's output is persisted to SQLite, and a `trace_id`
(`ECHO-<VERTICAL>-<YYYYMMDD>-<sequence>`) threads a single piece of content
through every stage so it stays traceable end to end. A human reviewer
(via `echo review`) then APPROVEs, REJECTs, EDITs, or SKIPs each draft --
including recording *why* content was not approved, which is persisted
alongside the content itself.

**STEP 2** -- real (but still non-AI) source acquisition and trend
detection sit in front of DISCOVER:

```
Source Registry -> Fetch -> Normalize -> Deduplicate -> Source Quality
                                             -> Topic/Event Clustering -> Trend Signal Calculation -> TrendCandidate
```

`echo ingest` fetches enabled sources (config-driven, see
`config/sources/ai.yaml`) with a bounded, stdlib-only HTTP layer
(timeout/retry cap/size cap/content-type check/http(s)-only, including
every redirect hop), normalizes, applies per-source ingestion upper
bounds (`max_items_per_fetch`, default 200; `max_item_age_hours`, default
168), and deduplicates them, then stores `SourceItem`s. `echo trends
detect` clusters them deterministically (no ML/embeddings) and scores
each cluster (freshness/velocity/novelty/relevance/source_quality/
cross-source confirmation, all on a 0.0-1.0 scale) via `RealTrendBrain`,
which coexists with STEP 1's `DummyTrendBrain`; a candidate that's a
near-exact repeat of an already-detected topic (low novelty) is still
detected and shown, but is not written to SQLite again. See
[docs/SOURCE_INTELLIGENCE.md](docs/SOURCE_INTELLIGENCE.md) for details.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- Core vs. Vertical separation, package layout, extension points
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) -- data models and SQLite schema
- [docs/SOURCE_INTELLIGENCE.md](docs/SOURCE_INTELLIGENCE.md) -- Source Registry, fetch/dedup/clustering/scoring, adding a new source
- [docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) -- rules every contributor (human or AI) must follow

## Scope

Neither STEP 1 nor STEP 2 implement: X posting, browser automation,
OpenAI/Anthropic/Gemini API calls, LLM-generated content, a production
Research/Content brain, a dashboard, an affiliate/monetization system, a
newsletter, "Echo Hub", automated self-learning, or running multiple
verticals in production. See
[docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) for the full rule
and rationale.
