---
name: echo-checkpoint-review
description: Read-only review of Project Echo checkpoint lifecycle state and verification evidence, when explicitly invoked.
---

# Project Echo checkpoint review

Use only within the Project Echo repository. Confirm the Git root and Project
Echo identity from `PROJECT_STATE.json` and the project contract before proceeding;
if the repository is another project or identity cannot be confirmed, STOP. Do
not search other repositories to recover missing context.

Read `PROJECT_STATE.json`, `docs/VERIFICATION_GATE.md`, and `AGENTS.md` at the
confirmed root. These are the canonical State, lifecycle protocol and authority
boundaries. Observe branch, HEAD, parent relationship, worktree and index without
changing them. Derive the supported mode from the documented resume protocol and
the observed Git evidence, rather than assuming every clean checkout is a valid
checkpoint. A changed HEAD needs a fresh identity assessment; an unsupported
identity or unexplained path means STOP, not a State repair.

When the request justifies verification, invoke the existing interpreter with
`-B scripts/verify.py --mode <derived-mode>` from that root. Use `--checks-only`
for the documented identity/scope/digest and sanity review when full verification
is not requested. It is not fresh full-suite evidence. Delegate State validation,
path scope and digest computation to that verifier; never reproduce its predicates
or calculate a replacement digest in this Skill. Read a real `.env` only as a
presence check; do not open its contents. Follow the verifier's offline temporary
fixture rules and preserve the existing database.

Report historical State evidence separately from fresh command results, including
the actual mode, observed identity, digest emitted by the verifier and exact exit
status. CI regression PASS is not checkpoint approval. A stderr warning with exit
0 does not alone establish failure; examine the command's declared result and
exit status. On the first fresh verifier/runner failure, STOP the gate sequence,
record the failing stage and distinguish environment/runner failure from a test
failure. Do not run later gates, retry unchanged commands, weaken checks or edit
State to reconcile inconsistent evidence.

Remain read-only, including when asked to stage, commit or push: identify the
concrete reviewed input and the separately required external authority, and STOP
this review before any mutation. Existing user authorization can be reported as
external evidence; the Skill itself neither supplies authority nor performs those
operations. Insufficient authority never becomes permission because checks pass.
Do not edit files/State, install anything, contact remotes, modify Git configuration,
stage, commit, push or begin any application/live phase through this Skill.

Conclude with identity/mode, historical versus fresh evidence, blockers versus
limitations, and the conditional next action under the canonical resume protocol.
Do not create a duplicate handoff document or embed checkpoint-specific values.
