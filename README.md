# Project Echo

Project Echo is an AI Media Operating System for running independent,
vertical-specific X (Twitter) media accounts. **Echo Core** is the shared,
vertical-agnostic pipeline engine; each **vertical** (AI, Tech, Crypto,
Business, Entertainment, ...) plugs into it through config and swappable
"brains" without Core ever hard-coding vertical-specific behavior.

This repository implements **STEP 1: Echo Foundation**, **STEP 2: Source &
Trend Intelligence**, **STEP 3: Research Intelligence**, the **Efficiency
Foundation**, and the offline **Project Echo Zero Affiliate Phase 0**.
Live affiliate integration and publishing remain out of scope.

## Quick start

For agent work, start with [PROJECT_STATE.json](PROJECT_STATE.json) and
[AGENTS.md](AGENTS.md). The repeatable offline closeout is
[docs/VERIFICATION_GATE.md](docs/VERIFICATION_GATE.md).

In **PowerShell**, `echo` is normally the `Write-Output` alias. With this
project installed into the selected Python, use **`python -B -m echo.cli`**
as the canonical CLI invocation, for example:

```powershell
python -B -m echo.cli --help
python -B -m echo.cli research --help
python -B -m echo.cli affiliate demo
python -B scripts/verify.py
```

Use the same interpreter for installation and execution; if it is not on
PATH, supply its absolute path. The `echo = echo.cli:main` console entrypoint
is retained. In the examples below, replace `echo` with `python -B -m echo.cli`
when using PowerShell. Operational commands such as `init`, `ingest` and
`sources check` have DB/network effects and require their own authorized scope.

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

# STEP 3: research intelligence for a detected trend
echo research run <trend_id>     # build a ResearchPacket (claims/evidence/conflicts/confidence)
echo research show <research_id> # show a persisted ResearchPacket's summary
echo research claims <research_id>    # list its claims
echo research conflicts <research_id> # list its detected conflicts
```

Run tests (fully offline -- no network access required):

```bash
pytest
```

For repository-clean verification, use `python -B scripts/verify.py`; it runs
targeted, STEP 3 and full tests in external temporary directories with cache
and bytecode disabled. See the Verification Gate for evidence and stopping rules.

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

**STEP 3** -- a `TrendCandidate` and the `SourceItem`s behind it become a
structured `ResearchPacket`:

```
TrendCandidate -> Relevant Source Collection -> Fact/Claim Extraction
                -> Claim Grouping -> Conflict Detection
                -> Source Independence + Confidence Calculation -> ResearchPacket
```

`echo research run <trend_id>` groups same-fact sentences from multiple
sources into claims (`CONFIRMED`/`SUPPORTED`/`SINGLE_SOURCE`/
`UNVERIFIED`/`CONFLICTED`), traces every claim back to the original
`SourceItem`/URL via `EvidenceItem`s, flags contradictions with
deterministic heuristics (opposite-status keywords, negation, differing
numbers, differing dates) rather than asserting them silently as
agreement, and computes a config-driven `confidence` plus a
`research_status` (`READY`/`NEEDS_MORE_SOURCES`/`CONFLICTED`/
`LOW_CONFIDENCE`/`INSUFFICIENT_EVIDENCE`) -- informational only, never a
publish decision. `RealResearchBrain` coexists with STEP 1's
`DummyResearchBrain`. See
[docs/RESEARCH_INTELLIGENCE.md](docs/RESEARCH_INTELLIGENCE.md) for
details.

**Affiliate Phase 0** adds an offline Rakuten-shaped item fixture, an explicit
Rakuyoko capability boundary, evidence-backed BuyNow signals, explainable
Opportunity Score v0, multi-item room bundles, visual/provenance contracts,
fail-closed compliance bound to the existing Human Review Gate, and nullable
revenue/KPI models. The demo is synthetic and does not contact a service,
create links, read a database, generate images or publish content. See
[docs/AFFILIATE_PHASE_0.md](docs/AFFILIATE_PHASE_0.md) and
[docs/AFFILIATE_VISUAL_POLICY.md](docs/AFFILIATE_VISUAL_POLICY.md).

## Documentation

**Affiliate Phase 1** adds Rakuten Item Search, Genre Search and Ranking adapters
behind an injectable, bounded HTTPS transport. Discovery preserves independent
observations, uses the existing score/signals and selects only qualifying items.
The default command uses synthetic fixtures:

```powershell
echo affiliate discover --keyword 照明 --top 5
echo affiliate discover --source ranking --genre-id 990001
echo affiliate discover --source genres --genre-id 0
```

Results and visual plans require Human Approval. No image generation, downloads
or posting occur. Live-readonly execution requires separate authorization and
the documented double guard; it has not been executed in this implementation.
See [docs/AFFILIATE_PHASE_1.md](docs/AFFILIATE_PHASE_1.md).

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- Core vs. Vertical separation, package layout, extension points
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) -- data models and SQLite schema
- [docs/SOURCE_INTELLIGENCE.md](docs/SOURCE_INTELLIGENCE.md) -- Source Registry, fetch/dedup/clustering/scoring, adding a new source
- [docs/RESEARCH_INTELLIGENCE.md](docs/RESEARCH_INTELLIGENCE.md) -- claims, evidence, conflicts, confidence, research status
- [docs/AFFILIATE_PHASE_0.md](docs/AFFILIATE_PHASE_0.md) -- offline affiliate architecture, official capability inventory, compliance and KPI contracts
- [docs/AFFILIATE_PHASE_1.md](docs/AFFILIATE_PHASE_1.md) -- Rakuten discovery contracts, safety limits, offline CLI and future live-readonly boundary
- [docs/AFFILIATE_VISUAL_POLICY.md](docs/AFFILIATE_VISUAL_POLICY.md) -- product-first lifestyle visual and carousel policy
- [docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) -- rules every contributor (human or AI) must follow

## Scope

Neither STEP 1/2/3 nor Affiliate Phase 0 implement: X/Instagram/Threads
posting, browser automation, external AI APIs or LLM-generated content, a
production Content brain, a dashboard, live affiliate integration or link
creation, a newsletter, "Echo Hub", automated self-learning, or running
multiple verticals in production. See
[docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) for the full rule
and rationale.
