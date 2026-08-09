# Project Echo

Project Echo is an AI Media Operating System for running independent,
vertical-specific X (Twitter) media accounts. **Echo Core** is the shared,
vertical-agnostic pipeline engine; each **vertical** (AI, Tech, Crypto,
Business, Entertainment, ...) plugs into it through config and swappable
"brains" without Core ever hard-coding vertical-specific behavior.

This repository currently implements **STEP 1: Echo Foundation** only. See
[Scope](#scope) below for what is intentionally not implemented yet.

## Quick start

```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env       # optional -- defaults work without it

echo init                  # create the SQLite database
echo demo                  # run dummy AI-vertical data through the pipeline
echo review                # see what's waiting for a human decision
echo review decide <draft_id> approve
echo review decide <draft_id> reject --reason low_value --note "..."
```

Run tests:

```bash
pytest
```

## What STEP 1 does

Dummy AI-vertical source data flows through:

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

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- Core vs. Vertical separation, package layout, extension points
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) -- data models and SQLite schema
- [docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) -- rules every contributor (human or AI) must follow

## Scope

STEP 1 Foundation deliberately does **not** implement: X posting, browser
automation, OpenAI/Anthropic API calls, real trend scraping, a dashboard,
an affiliate/monetization system, a newsletter, "Echo Hub", automated
self-learning, or running multiple verticals in production. See
[docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) for the full rule
and rationale.
