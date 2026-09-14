# Project Echo Verification Gate

This is the repeatable offline closeout for STEP 3 + Core Efficiency Foundation.
Read `../PROJECT_STATE.json` for the approved branch, checkpoint parent, exact
checkpoint scope, evidence and handoff. Nothing here grants commit or live authority.

## Checkpoint lifecycle and State

`baseline_head` always means the **parent commit on which this checkpoint is
based**, before and after its commit. `approved_change_paths` is the persistent
checkpoint-owned path set, not a claim that these paths are currently dirty.
Neither field is automatically rewritten. No future/self commit hash belongs
inside the same commit's State. Runtime output reports the observed HEAD.

State schema 2 is a durable checkpoint contract with historical verification
evidence, not a mutable next-action cursor. `checkpoint_subject` identifies the
work being captured; `test_baseline.accepted` and `verification` record completed
offline observations. Old evidence and the LC-01/LC-02 failed review remain under
history, without being treated as active acceptance. Accepted evidence requires
PASS, nonempty consistent test counts, completed independent review and no
unresolved blockers. A historical FAIL does not invalidate resolved acceptance.

`handoff.resume_protocol` derives the next action from observed Git identity and
external authority using the three conditions below; any unsupported state means
STOP. Its method, lifecycle rules, external-authority requirement and prohibited
automatic actions are mandatory. Legacy current/readiness/next-action cursors are
rejected. This conditional next-action policy fulfills the AGENTS handoff rule.

| Lifecycle | Required identity/scope | Invocation / authority / stop condition |
|---|---|---|
| 1. WORKTREE VERIFIED | HEAD = baseline_head; clean index; only allowed modified/untracked paths | `python -B scripts/verify.py --mode worktree`; default mode; stop on unexpected scope/identity or first failure |
| 2. STAGED VERIFIED | HEAD = baseline_head; staged A/M path set exactly equals approved_change_paths; no unstaged drift/untracked files; index digest equals recorded PASS | After externally authorized staging: `python -B scripts/verify.py --mode staged`; stop on any mismatch |
| 3. LOCAL COMMIT | Reviewed staged candidate and separate explicit user/orchestrator authorization | One authorized Git commit; verifier/State never performs or authorizes it |
| 4. COMMITTED VERIFIED | Clean worktree/index; HEAD has exactly one parent, equal to baseline_head; HEAD change set exactly matches scope; committed digest matches recorded PASS | `python -B scripts/verify.py --mode committed`; full verification against the committed input; stop on wrong parent, extra/later commit, scope/digest mismatch or failure |
| 5. PUSH REVIEW | Inspect committed verification evidence and configured destination | Read-only review; push requires a separate explicit instruction, with no automatic network action |

`commit_authorized` remains `false`: authorization comes from the user or
orchestration, never from repository state. `true` is rejected in every mode.
Live authority remains false. A state-only handoff/evidence update before staging
must be part of authorized remediation and establishes a new digest. Once sealed,
the same State remains valid through review, staging, local commit, committed
verification and push review. No review/staging/post-commit State edit, predicted
commit hash or second state-sync commit is required. Future external review and
Git operations produce external observations; the historical State does not claim
they already happened, remain pending, or must happen next unconditionally.

## Invocation

From the repository root, use the existing Python with the project's dev
dependencies already installed:

```powershell
python -B scripts/verify.py
```

If `python` is not on PATH, use that interpreter's absolute path. On the current
host the verified invocation is:

```powershell
& 'C:\Users\syuya\AppData\Local\Python\pythoncore-3.14-64\python.exe' -B scripts/verify.py
```

The script inserts this repository's `src`, disables bytecode, pytest cache,
external plugin autoload and dotenv loading, and removes inherited `ECHO_*`
overrides in worker processes. It uses only the existing standard library and
pytest. No install, fetch, smoke test, database migration or remote command runs.
The installed `project-echo` entrypoint must resolve to this repository.

Tests use a unique directory in the OS temporary area, cleaned when the run
finishes. Workers block writes outside that directory (apart from the null
device), real `.env` reads, non-test SQLite connections, sockets and subprocesses.
The sole subprocess exception is an exact Git command allowlist in isolated
fixture repositories under that external temporary directory. It permits fixture
init/add/commit and bounded local reads, with inherited GIT_* selectors removed,
global/system config and hooks disabled, and protocols prohibited. It rejects
the real repository, linked Git directories, remote commands, shell commands,
arbitrary options and environment injection. Fixture Git history tests grant no
staging/commit authority in Project Echo. The verifier itself only reads real Git.
This is a guard for trusted repository tests, not an OS sandbox for malicious code.
Existing ignored artifacts, including `data/echo.db`, are compared before/after;
secret/local settings use metadata only. Git runs with optional locks disabled.
The script writes evidence only to stdout and never updates Project State itself.

## Ordered gates and commit eligibility

| Order | Gate | PASS evidence |
|---|---|---|
| 1 | Git scope | State semantics, branch, mode-specific HEAD/parent relation and exact scope rules above pass |
| 2 | Diff checks | Unstaged and staged `git diff --check` succeed |
| 3 | Verifier regressions | Temporary Git lifecycle, digest, scope and worker-guard regressions pass |
| 4 | Import and CLI sanity | Every Echo module resolves under this `src`; nine help routes and installed `echo.cli:main` mapping succeed |
| 5 | Targeted regressions | H1/H2/H3/M1/M2/M3/M4 and verifier regressions pass |
| 6 | STEP 3 and full pytest | All STEP 3 tests, then all repository tests pass; failed=0; report skips/warnings |
| 7 | Hygiene | No added/changed/removed repo files, existing DB/cache/index unchanged during execution |
| 8 | Secrets | `.env` presence only; approved/tracked text has no recognized high-confidence secret pattern; manually review diffs without disclosing secrets |
| 9 | Authority | No external network, live API, posting, affiliate execution, dependency or Git mutation |
| 10 | Docs/state | Config docs and semantics match implementation; State binds historical results/review, resolved blockers and durable resume protocol |
| 11 | Final Git status | HEAD, branch, State, content digest, index and filesystem snapshot match pre-run; report scope/stat |
| 12 | Checkpoint review | All technical checks pass, independent review resolved, exact changes reviewed by user; explicit staging/commit authorization remains separate |

The first failed worker ends the sequence. No later tests or automatic retries
run. Read-only failure diagnosis and hygiene inspection remain necessary. Fixes
within an authorized remediation may be followed by a fresh verification run;
report both the failure and subsequent result. Do not weaken tests or switch
interpreters to hide a failure.

`--checks-only` is independent of lifecycle mode: for example,
`python -B scripts/verify.py --mode committed --checks-only` repeats that mode's
complete identity/scope/digest and sanity checks without pytest. Omitting it runs
the full verifier in all modes. It does **not** replace full-test evidence.

## Digest and execution input contract

`verification.digest_algorithm = "sha256-path-content-lf-state-v2"` uses sorted,
case-sensitive POSIX relative path names and the existing path/NUL/content-hash
construction. UTF-8 source/docs/config/fixture text (the verifier's explicit
TEXT_SUFFIXES plus .gitignore/.gitattributes) normalizes CRLF to LF. No other
whitespace or BOM is discarded; binary bytes remain exact. This makes Git's
normal text line-ending conversion consistent across all modes. Raw-byte and v1
digests are historical and must not be mixed with this algorithm.

- Worktree input: every tracked file plus approved additions, read from filesystem.
- Staged input: every stage-0 regular-file blob read from the Git index.
- Committed input: every regular-file blob read from HEAD; index must match HEAD.

Before staged/committed tests run from filesystem, every corresponding file must
match the Git content under the same text-only normalization, including State.
Symlinks, conflicts, renames/deletions/type changes and escaping paths are rejected.
Git blob reads never invoke content filters or external diff tools.

`PROJECT_STATE.json` participates under its own path identity. Parse strict JSON
(duplicate keys and non-finite numbers fail), replace **only** the value at
`/verification/input_digest` with the deterministic `__SELF_DIGEST__` sentinel,
then serialize UTF-8 JSON with sorted keys and compact separators. All other
content, including unknown metadata, previous digests, test/review history,
authority, blockers, deferred findings and the resume protocol, stays in the
projection. State formatting/key order is immaterial. Other files keep the
existing text/binary rules. No State section or timestamp is excluded wholesale.

Filesystem/index/HEAD State equality uses complete semantic JSON, including the
unmasked input_digest. Both sides must pass the same State validation. Merely
staging/committing the same altered State cannot preserve the old approved digest.
All three modes, including worktree and every checks-only invocation, require
the computed digest to equal the recorded digest. This integrity check is not a
signature or permission grant; external review/authorization must bind the exact
reported digest and scope. Recomputing a digest never supplies that authority.

Evidence validation requires schema 2, a 40-hex parent, sorted unique normalized
scope, false authorities, valid evidence type/mode/timestamps and v2 64-hex digest.
Every required test stage must have positive integer passed counts, failed=0 and
nonnegative skipped/warnings, rejecting booleans or inconsistent totals/subsets.
Full pytest and independent PASS review evidence are mandatory. Empty evidence,
unresolved blockers, contradictory hygiene or missing durable handoff fail closed.

For authorized remediation, first collect actual results with the existing
guarded `--worker` stages using one external temporary directory and a supervising
read-only scope/identity/snapshot/index check. Run verification, targeted, STEP 3,
full and sanity workers, stopping at the first failure. This preliminary evidence
collection is not a checkpoint verification PASS; an unsealed/PENDING State is
rejected by normal modes. It permits bootstrapping truthful measured evidence
without fabricating future PASS counts or weakening the normal validator.

After completed independent reviews, record those historical observations in
State and finish all code/test/doc edits. Compute v2 input_digest from tracked
files plus approved additions using `input_digest`; fill only its masked State
field. Then run the full `--mode worktree` verifier against the frozen State,
followed by `--mode worktree --checks-only`. Report these final results externally;
do not append their timestamp/result/digest elsewhere in State afterward. Any
non-masked edit requires resealing and fresh full verification. Filling only the
self-digest leaves the projection unchanged. The same sealed State can be staged
and committed under separate authority, then fully verified without editing it.
For a later checkpoint, establish a new parent/scope under new authorization;
an extra commit cannot pass against this old manifest.

Before commit eligibility, the reviewer must also examine new-file contents:
normal `git diff --stat` / `--check` do not include untracked files. The verifier's
scope and input digest include them, but do not replace content review.

## Efficiency Foundation inventory

| Component | State | Rationale |
|---|---|---|
| Project AGENTS | ACTIVE | Small repository-specific invariants and authority boundaries |
| Verification Gate + `scripts/verify.py` | ACTIVE | One offline command reproduces safety, import, CLI and test checks |
| Project State / Handoff | ACTIVE | One JSON document binds checkpoint identity, historical evidence, limitations and Git-derived resume policy |
| Existing modules/config/stats | REUSED | Common text/reliability, clustering reuse, deterministic functions, bounded candidates and counts |
| Subagent read-only review | ACTIVE for this pass | Independent correctness, architecture and test review; single writer |
| Codex Skills | DEFER | No repeated cross-project procedure yet justifies a separate skill; reuse local verifier first |
| Global AGENTS | DEFER | Local contract suffices; changing other projects/global settings is outside scope |
| Git Worktree | DEFER until clean checkpoint | Preserve this known dirty implementation and avoid moving user work |
| GitHub Actions / CI | DEFER until clean checkpoint | First stabilize the local command; remote configuration/network is not authorized |
| Auto-review | DEFER as project automation | Human checkpoint and independent read-only review suffice; no new integration |
| Scheduled Tasks | NOT NEEDED now | Offline development has no recurring authorized runtime task |
| MCP / Plugins | NOT NEEDED now | No external service/data is needed for this phase |
| Model Routing | NOT NEEDED now | No application model calls; extra routing would not improve this offline gate |

No deferred component is installed or configured by this pass. Their state is
an adoption decision, not a claim about availability or current vendor features.
