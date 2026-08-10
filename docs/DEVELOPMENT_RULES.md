# Development Rules

These rules apply to every contributor, human or AI. When in doubt, prefer
the smallest, safest change consistent with these rules over asking; if a
rule genuinely blocks the work, stop and ask rather than working around it.

1. **Separate Echo Core from Verticals.** `echo.core` (and the stage
   service packages `echo.trend`/`research`/`scoring`/`content`/
   `compliance`/`review`) must never import from `echo.verticals` or branch
   on a vertical id. Vertical behavior enters only through data:
   `VerticalConfig` (loaded from `config/verticals/*.yaml`) and the
   `vertical: str` field on models. See `docs/ARCHITECTURE.md`.

2. **Never hard-code vertical- or source-specific logic into Core.**
   Topics, content types allowed, review policy, prompts, topic
   keywords/aliases, etc. for a vertical belong in
   `config/verticals/<id>.yaml` and/or `echo.verticals.<id>` -- not in
   `echo.core`, `echo.brains`, or any stage service. `topic_keywords` keys
   must be a subset of `topics`, enforced by a `VerticalConfig` model
   validator (Pre-Commit Hardening) rather than left as an unchecked
   convention. Likewise, no company
   or product name (e.g. a specific source's identity) belongs in
   `echo.source` or `echo.trend` code -- sources are entirely
   config-driven via `config/sources/<vertical>.yaml`
   (`echo.source.config.SourceConfig`), including their `reliability_tier`.
   `echo.brains.RealTrendBrain` gets vertical/source data injected at
   construction time by its caller (the CLI) precisely so it never needs
   to import `echo.verticals` itself.

3. **All content passes through the Human Review Gate.** No pipeline stage
   may publish or auto-approve content. COMPLIANCE is informational only
   (it annotates `ContentDraft.compliance_risk_score` /
   `compliance_flags`); only a human decision recorded via
   `echo.review.service.record_decision` (APPROVE/REJECT/EDIT/SKIP)
   finalizes a draft's fate.

4. **Persist decisions not to publish, with their reason.** Every
   `ReviewDecision` -- including REJECT and SKIP -- is saved to SQLite,
   and REJECT requires a `RejectReason` (enforced by a Pydantic
   validator on `ReviewDecision`). Content that is never published must
   remain queryable, next to the reason it wasn't published.

5. **Maintain traceability.** Every new stage output that represents "the
   same piece of content, further along the pipeline" must carry the same
   `trace_id` (see `echo.core.trace`). Don't invent parallel ID schemes.

6. **Never commit secrets.** No API keys, tokens, or credentials in code
   or in git history. Real values go in `.env` (gitignored); `.env.example`
   documents the variable names only, with no real values.

7. **Don't implement outside the current STEP's scope.** Check the active
   step's scope guard before adding a feature. As of STEP 2: no X API
   posting/automation, no browser automation, no OpenAI/Anthropic/Gemini
   API calls, no LLM-generated content, no production Research/Content
   brain, no dashboard, no affiliate/monetization system, no newsletter,
   no "Echo Hub", no automated self-learning, no multi-vertical production
   runs. Reserved packages (`echo.performance`, `echo.audience`,
   `echo.monetization`, `echo.memory`) stay as placeholder `__init__.py`
   files until their step is scoped.

8. **Don't add unnecessary dependencies.** The dependency set is
   deliberately small (pydantic, typer, pyyaml, python-dotenv, pytest).
   STEP 2's HTTP fetch layer and RSS/Atom/JSON parsing use the standard
   library only (`urllib.request`, `xml.etree.ElementTree`, `json`) --
   no HTTP client or feed-parsing library was added. Adding a new
   dependency should be a deliberate, visible decision, not a side effect
   of an unrelated change.

9. **Don't break the tests.** `pytest` must pass before and after your
   change. Add tests for new behavior; don't delete or weaken a test to
   make it pass without fixing the underlying issue. `pytest` must never
   depend on network access -- HTTP-dependent code is tested against a
   monkeypatched `urlopen`/`fetch` or static fixture files (see
   `docs/SOURCE_INTELLIGENCE.md` "Network tests vs. offline tests"). Real
   connectivity is checked separately, manually, via `echo sources check`
   or `scripts/smoke_test_sources.py` -- never inside `pytest`.

10. **Keep SQL in the storage layer.** All SQL statements live in
    `echo.storage` (`db.py`, `repository.py`). Other packages call
    `EchoRepository` methods -- they never open a `sqlite3` connection or
    write raw SQL themselves.

11. **Never bypass access controls to fetch a source.** No robots.txt
    bypass, no WAF/Cloudflare/CAPTCHA bypass, no login/authentication
    bypass, no rate-limit evasion, no browser-automation "stealth" mode.
    If a source can't be fetched with a plain, well-behaved HTTP request
    (see `echo.source.http_client`), it stays `enabled: false` in the
    registry -- see `docs/SOURCE_INTELLIGENCE.md` "Adding a new source".
    `echo.source.http_client` only ever opens `http`/`https` URLs --
    enforced explicitly in code for the initial request *and* every
    redirect hop (see `docs/SOURCE_INTELLIGENCE.md` "Redirect scheme
    security"), never left to an interpreter version's default behavior.

12. **Never guess a source URL.** A `config/sources/*.yaml` entry may only
    be `enabled: true` if the URL was actually verified (a real request
    returned valid content of the declared `source_type`). An unverified
    or currently-broken URL is registered `enabled: false` with a comment
    recording what was observed, not silently omitted and not enabled on
    a guess.

13. **Keep STEP 2 scoring/clustering deterministic.** No ML models or
    embeddings for deduplication, clustering, or trend signal
    calculation in STEP 2 -- use documented, testable, closed-form
    functions (token overlap, time decay, etc.), each in its own module
    under `echo.trend`/`echo.source.dedup`. A future step may swap in an
    embedding-based similarity function, but the call signature these
    modules expose should stay stable so that's a contained change.
