# Project Echo agent contract

Project identity: **Project Echo**, this repository only. Begin with
`PROJECT_STATE.json`, then `docs/VERIFICATION_GATE.md`. The state is the
canonical handoff; README is the product guide. Verify branch, HEAD and
working-tree scope against state before editing. Preserve existing user work.

## Phase and authority

- Accepted baseline: Affiliate Phase 1.1 Ranked Candidate Hydration, Affiliate
  Phase 0/1, STEP 1/2/3 and the Efficiency Foundation at
  `9a45fa5df980148e8c1433411a1ceb6624334ae4`. The checkpoint subject is Affiliate
  Phase 1.2 Real Content Proposal Foundation on that parent. Project State records the
  completed bounded readonly validation; it grants no continuing runtime authority.
- No authority for STEP 4, live affiliate integration, account/API access,
  affiliate-link creation, social posting, live execution, Scheduler, plugins,
  installs or OS/global configuration. A PASS never grants any of these.
- Default to offline work. Never inspect or print secret values, create
  credentials, or read a real `.env` during verification. Presence checks only.
- Phase 1's live-readonly factory requires explicit intent plus
  `ECHO_RAKUTEN_LIVE_READONLY=1` before environment-only credential lookup.
  Implementing this guard grants no authority to supply credentials or call APIs.
  Rakuyoko has no authorized automated integration; image URLs are references,
  never rights proof or permission to download/render.
- Preserve `data/echo.db`. Use external temporary fixture databases for tests;
  schema migration tests do not authorize migrating the existing database.

## Invariants

- Follow `docs/DEVELOPMENT_RULES.md`: Core and stage services do not import
  vertical implementations. Research does not import source acquisition.
  Generic reliability/text helpers live in Core; registry facts are injected.
- Keep affiliate adapter details out of Core/STEP 1/2. SQL stays in storage;
  Phase 0 adds no persistence. Keep public STEP 1/2 interfaces compatible.
  Human Review remains the only approval gate; research status is informational.
- Preserve full canonical product names separately from short context headlines.
  API image references are not rights. Whole product images have protected regions;
  unresolved Web Service credit and native platform disclosure block publishing.
- Minimal scoped changes; no unrelated refactor or extra dependencies.
  New files must be necessary for the authorized fix or its verification.
- No parallel writes. Subagents may perform read-only reviews when requested;
  the main agent alone edits, integrates findings and runs verification.

## Git and verification

- Never discard user work. Stop on unexpected unrelated changes or when the
  approved path set no longer explains the worktree. Do not auto-clean artifacts.
- `git add`, commit and push require explicit authority for that action.
  No reset, clean, rebase, amend or force operations in this implementation pass.
- Use the existing interpreter/dependencies. Do not repair or replace the
  environment silently. Use `python -B scripts/verify.py` from the repo root;
  it is offline, keeps test output outside the repository and grants no Git authority.
- First fresh failure: stop the current gate sequence and record the failing
  stage. Diagnose within scope; never continue later gates or retry unchanged
  commands to conceal failure. An authorized corrective edit permits a fresh
  verification sequence. Distinguish runner/environment failures from test failures.
- Keep deterministic clocks in time-sensitive tests. Preserve production
  filtering and every existing regression case; never weaken a predicate to pass.
- Disable bytecode/cache or route artifacts outside the repo. Compare existing
  artifacts, database, index and worktree before/after verification.

## Completion and handoff

- Completion needs the complete Verification Gate, independent review when
  available, and synchronized code, config samples, docs and Project State.
- Record what changed, exact results, blockers, input digest and next action
  in state; do not create duplicate handoff narratives or claim unrun checks.
- Record limitations separately from blockers. Passing tests means technical
  verification, not commit approval or execution authority.
- Report results and stop. Do not advance to live Affiliate integration or
  another application phase automatically.
