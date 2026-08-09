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

2. **Never hard-code vertical-specific logic into Core.** Topics, content
   types allowed, review policy, prompts, etc. for a vertical belong in
   `config/verticals/<id>.yaml` and/or `echo.verticals.<id>` -- not in
   `echo.core`, `echo.brains`, or any stage service.

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
   step's scope guard before adding a feature. As of STEP 1: no X API
   posting, no browser automation, no OpenAI/Anthropic API calls, no real
   trend scraping, no dashboard, no affiliate/monetization system, no
   newsletter, no "Echo Hub", no automated self-learning, no multi-vertical
   production runs. Reserved packages (`echo.performance`, `echo.audience`,
   `echo.monetization`, `echo.memory`) stay as placeholder `__init__.py`
   files until their step is scoped.

8. **Don't add unnecessary dependencies.** STEP 1's dependency set is
   deliberately small (pydantic, typer, pyyaml, python-dotenv, pytest).
   Adding a new dependency should be a deliberate, visible decision, not a
   side effect of an unrelated change.

9. **Don't break the tests.** `pytest` must pass before and after your
   change. Add tests for new behavior; don't delete or weaken a test to
   make it pass without fixing the underlying issue.

10. **Keep SQL in the storage layer.** All SQL statements live in
    `echo.storage` (`db.py`, `repository.py`). Other packages call
    `EchoRepository` methods -- they never open a `sqlite3` connection or
    write raw SQL themselves.
