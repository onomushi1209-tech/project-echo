"""Safety boundaries of the small project verification entrypoint."""

from pathlib import Path
from copy import deepcopy
import json
import os
import runpy
from types import SimpleNamespace

import pytest

VERIFY = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "verify.py"))


def test_verification_scope_rejects_unrelated_and_staged_changes():
    check = VERIFY["check_scope"]
    check(" M src/echo/cli.py\n?? tests/test_new.py\n", ["src/echo/cli.py", "tests/test_new.py"])
    for status in (" M unrelated.py\n", "M  src/echo/cli.py\n", " D src/echo/cli.py\n"):
        with pytest.raises(VERIFY["VerificationFailure"]):
            check(status, ["src/echo/cli.py"])


def test_verification_write_boundary_rejects_siblings_and_parent_escape(tmp_path):
    allowed = VERIFY["allowed_write"]
    assert allowed(tmp_path / "database.db", tmp_path)
    assert not allowed(tmp_path / ".." / "outside.db", tmp_path)
    assert not allowed(Path(str(tmp_path) + "-sibling") / "data.db", tmp_path)
    assert not allowed(Path(__file__), tmp_path)


def test_verification_detects_changed_existing_file_and_new_artifact(tmp_path):
    path = tmp_path / "existing.txt"
    path.write_text("before", encoding="utf-8")
    before = VERIFY["snapshot"](tmp_path)
    path.write_text("after", encoding="utf-8")
    assert VERIFY["snapshot"](tmp_path) != before
    path.write_text("before", encoding="utf-8")
    (tmp_path / "unexpected.pyc").write_bytes(b"fixture")
    assert "unexpected.pyc" in VERIFY["snapshot"](tmp_path)


@pytest.mark.parametrize("filename", ["source.yaml", "settings.txt"])
def test_secret_pattern_check_includes_config_text_without_disclosing_fixture(tmp_path, monkeypatch, filename):
    # Synthetic invalid detector fixture, never a usable credential.
    marker = "sk-" + "x" * 40
    (tmp_path / filename).write_text(marker, encoding="utf-8")
    check = VERIFY["input_digest"]
    monkeypatch.setitem(check.__globals__, "ROOT", tmp_path)
    with pytest.raises(VERIFY["VerificationFailure"]) as caught:
        check([filename])
    assert filename in str(caught.value)
    assert marker not in str(caught.value)


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    """Real isolated Git history; never stage/commit the Project Echo repository."""
    root = tmp_path / "checkpoint"
    root.mkdir()
    monkeypatch.setitem(VERIFY["git_bytes"].__globals__, "ROOT", root)

    def write(name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    git = VERIFY["git"]
    git("init", "--initial-branch=main", "--template=")
    initial = ["AGENTS.md", "docs/VERIFICATION_GATE.md", "engine.py", ".gitattributes"]
    for name in initial:
        write(name, "*.py text eol=lf\n" if name == ".gitattributes" else "baseline\n")
    git("add", "--", *initial)
    git("commit", "-m", "fixture checkpoint")
    parent = git("rev-parse", "HEAD").strip()
    scope = sorted(["PROJECT_STATE.json", "engine.py", "new.txt"])
    state = {
        "schema_version": 2, "state_model": "durable_checkpoint", "checkpoint_subject": "checkpoint fixture",
        "project": "Project Echo", "branch": "main", "baseline_head": parent,
        "completed_steps": ["fixture"], "known_blockers": [],
        "test_baseline": {"accepted": {stage: {"passed": 1, "failed": 0, "skipped": 0, "warnings": 0, "collected": 1}
                                       for stage in VERIFY["TEST_STAGES"]}},
        "live_authority": {key: False for key in VERIFY["LIVE_AUTHORITIES"]},
        "commit_authorized": False, "approved_change_paths": scope,
        "handoff": {"resume_protocol": deepcopy(VERIFY["RESUME_PROTOCOL"]),
                    "prohibited_automatic_actions": list(VERIFY["PROHIBITED_AUTOMATIC_ACTIONS"])},
        "verification": {"status": "PASS", "digest_algorithm": VERIFY["DIGEST_ALGORITHM"], "input_digest": "0" * 64,
                         "mode": "worktree", "evidence_type": "guarded_offline_workers", "verified_at_utc": "2026-09-06T00:00:00Z",
                         "imported_modules": 1, "cli_help_routes": 1,
                         "independent_review": {"status": "PASS", "reviewed_at_utc": "2026-09-06T00:00:00Z",
                                                "reviewers": [{"name": "fixture reviewer", "scope": "fixture contract", "status": "PASS"}]}},
    }
    write("engine.py", "checkpoint implementation\n")
    write("new.txt", "checkpoint addition\n")

    def save_state():
        write("PROJECT_STATE.json", json.dumps(state, indent=2) + "\n")

    def seal():
        save_state()
        state["verification"]["input_digest"] = VERIFY["input_digest"](initial + scope)
        save_state()

    def stage(*extra):
        git("add", "--", *scope, *extra)

    def commit():
        git("commit", "-m", "fixture checkpoint")

    seal()
    return SimpleNamespace(root=root, state=state, parent=parent, scope=scope, write=write,
                           git=git, save_state=save_state, seal=seal, stage=stage, commit=commit,
                           check=VERIFY["verify_checkpoint"])


def test_worktree_accepts_parent_and_authorized_changes(checkpoint):
    result = checkpoint.check("worktree")
    assert result["head"] == checkpoint.parent
    assert result["input_digest"] == checkpoint.state["verification"]["input_digest"]


def test_worktree_rejects_wrong_head(checkpoint):
    checkpoint.stage()
    checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="HEAD differs"):
        checkpoint.check("worktree")


def test_worktree_rejects_staged_index(checkpoint):
    checkpoint.stage()
    with pytest.raises(VERIFY["VerificationFailure"], match="worktree scope/status"):
        checkpoint.check("worktree")


def test_staged_accepts_exact_index_and_matching_filesystem(checkpoint):
    checkpoint.stage()
    result = checkpoint.check("staged")
    assert result["input_digest"] == checkpoint.state["verification"]["input_digest"]


def test_staged_rejects_extra_path(checkpoint):
    checkpoint.write("extra.txt", "unapproved\n")
    checkpoint.stage("extra.txt")
    with pytest.raises(VERIFY["VerificationFailure"], match="staged scope"):
        checkpoint.check("staged")


def test_staged_rejects_unstaged_drift(checkpoint):
    checkpoint.stage()
    checkpoint.write("engine.py", "unstaged change\n")
    with pytest.raises(VERIFY["VerificationFailure"], match="unstaged drift"):
        checkpoint.check("staged")


def test_staged_checks_filesystem_even_when_status_hides_drift(checkpoint, monkeypatch):
    checkpoint.stage()
    entries = VERIFY["status_entries"]()
    checkpoint.write("engine.py", "hidden filesystem change\n")
    monkeypatch.setitem(checkpoint.check.__globals__, "status_entries", lambda: entries)
    with pytest.raises(VERIFY["VerificationFailure"], match="Filesystem differs"):
        checkpoint.check("staged")


def test_staged_rejects_index_digest_mismatch(checkpoint):
    checkpoint.write("engine.py", "different from approved evidence\n")
    checkpoint.stage()
    with pytest.raises(VERIFY["VerificationFailure"], match="digest/approval"):
        checkpoint.check("staged")


def test_staged_rejects_missing_scope_path(checkpoint):
    checkpoint.git("add", "--", "engine.py", "PROJECT_STATE.json")
    # The new untracked file is also rejected, before the exact-set check.
    with pytest.raises(VERIFY["VerificationFailure"], match="staged scope"):
        checkpoint.check("staged")


def test_committed_accepts_single_parent_without_self_hash(checkpoint):
    checkpoint.stage()
    staged = checkpoint.check("staged")
    state_bytes = (checkpoint.root / "PROJECT_STATE.json").read_bytes()
    checkpoint.commit()
    result = checkpoint.check("committed")
    assert result["head"] != checkpoint.parent
    assert result["state"]["baseline_head"] == checkpoint.parent
    assert result["input_digest"] == staged["input_digest"]
    assert result["head"].encode() not in state_bytes
    assert (checkpoint.root / "PROJECT_STATE.json").read_bytes() == state_bytes


def test_committed_rejects_parent_without_checkpoint(checkpoint):
    with pytest.raises(VERIFY["VerificationFailure"], match="exactly one parent"):
        checkpoint.check("committed")


def test_committed_rejects_wrong_parent(checkpoint):
    checkpoint.git("commit", "--allow-empty", "-m", "fixture checkpoint")
    checkpoint.stage()
    checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="exactly one parent"):
        checkpoint.check("committed")


def test_committed_rejects_extra_committed_path(checkpoint):
    checkpoint.write("extra.txt", "unapproved\n")
    checkpoint.stage("extra.txt")
    checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="Committed path set"):
        checkpoint.check("committed")


def test_committed_rejects_digest_mismatch(checkpoint):
    checkpoint.write("engine.py", "unapproved committed implementation\n")
    checkpoint.stage()
    checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="digest/approval"):
        checkpoint.check("committed")


@pytest.mark.parametrize("mode", ["worktree", "staged", "committed"])
def test_state_cannot_grant_commit_authority(checkpoint, mode):
    checkpoint.state["commit_authorized"] = True
    checkpoint.save_state()
    if mode != "worktree":
        checkpoint.stage()
    if mode == "committed":
        checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="cannot grant"):
        checkpoint.check(mode)


def test_committed_rejects_later_commit_with_old_state(checkpoint):
    checkpoint.stage()
    checkpoint.commit()
    checkpoint.git("commit", "--allow-empty", "-m", "fixture checkpoint")
    with pytest.raises(VERIFY["VerificationFailure"], match="exactly one parent"):
        checkpoint.check("committed")


@pytest.mark.parametrize("stage_drift", [False, True])
def test_committed_requires_clean_filesystem_and_index(checkpoint, stage_drift):
    checkpoint.stage()
    checkpoint.commit()
    checkpoint.write("engine.py", "later edit\n")
    if stage_drift:
        checkpoint.git("add", "--", "engine.py")
    with pytest.raises(VERIFY["VerificationFailure"], match="clean worktree and index"):
        checkpoint.check("committed")


def test_crlf_lf_normalization_is_identical_across_modes(checkpoint):
    checkpoint.write("engine.py", "checkpoint implementation\r\n")
    worktree = checkpoint.check("worktree")
    checkpoint.stage()
    staged = checkpoint.check("staged")
    checkpoint.commit()
    committed = checkpoint.check("committed")
    assert worktree["input_digest"] == staged["input_digest"] == committed["input_digest"]


def test_state_is_still_compared_to_index(checkpoint, monkeypatch):
    checkpoint.stage()
    entries = VERIFY["status_entries"]()
    checkpoint.state["handoff"]["review_note"] = "changed after staging"
    checkpoint.save_state()
    monkeypatch.setitem(checkpoint.check.__globals__, "status_entries", lambda: entries)
    with pytest.raises(VERIFY["VerificationFailure"], match="Filesystem differs.*PROJECT_STATE"):
        checkpoint.check("staged")


@pytest.mark.parametrize("checks_only", [False, True])
def test_cli_mode_validation_precedes_any_workers(checkpoint, monkeypatch, checks_only):
    monkeypatch.chdir(checkpoint.root)
    monkeypatch.setattr("sys.argv", ["verify.py", "--mode", "committed"] + (["--checks-only"] if checks_only else []))
    with pytest.raises(VERIFY["VerificationFailure"], match="exactly one parent"):
        VERIFY["main"]()


def test_fixture_git_permission_is_local_and_command_bounded(checkpoint, tmp_path):
    prefix = [VERIFY["GIT_EXECUTABLE"], *VERIFY["GIT_PREFIX"]]
    env = VERIFY["git_environment"](True)
    allowed = VERIFY["fixture_git_allowed"]
    args = (VERIFY["GIT_EXECUTABLE"], prefix + ["rev-parse", "HEAD"], str(checkpoint.root), env)
    assert allowed(args, tmp_path)
    for command in (["push"], ["fetch"], ["reset", "--hard"], ["clean", "-fd"], ["diff", "--output=outside"]):
        assert not allowed((args[0], prefix + command, args[2], env), tmp_path)
    assert not allowed((args[0], args[1], str(Path(__file__).resolve().parents[1]), env), tmp_path)
    assert not allowed((args[0], args[1], args[2], dict(env, GIT_DIR=str(Path(__file__).resolve().parents[1] / ".git"))), tmp_path)


def test_git_environment_cannot_redirect_real_repository(checkpoint, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(Path(__file__).resolve().parents[1] / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(Path(__file__).resolve().parents[1] / ".git/index"))
    assert checkpoint.check("worktree")["head"] == checkpoint.parent


def test_durable_state_survives_review_staging_and_one_commit_without_sync(checkpoint):
    # T1-T7, T9: review is an external observation, not a persisted lifecycle cursor.
    frozen = (checkpoint.root / "PROJECT_STATE.json").read_bytes()
    worktree = checkpoint.check("worktree")
    VERIFY["check_state"](checkpoint.state)  # read-only contract review
    checkpoint.stage()
    staged = checkpoint.check("staged")
    checkpoint.commit()
    committed = checkpoint.check("committed")
    assert worktree["input_digest"] == staged["input_digest"] == committed["input_digest"]
    assert (checkpoint.root / "PROJECT_STATE.json").read_bytes() == frozen
    assert committed["head"].encode() not in frozen
    assert checkpoint.git("rev-list", "--parents", "-n", "1", "HEAD").split() == [committed["head"], checkpoint.parent]
    for key in ("current_step", "current_readiness", "next_authorized_action"):
        assert key not in committed["state"]
    assert "exact_next_action" not in committed["state"]["handoff"]


@pytest.mark.parametrize("location,key", [("root", "current_readiness"), ("root", "next_authorized_action"),
                                         ("handoff", "exact_next_action"), ("handoff", "what_remains")])
def test_old_temporal_cursor_rejected_even_after_resealing(checkpoint, location, key):
    destination = checkpoint.state if location == "root" else checkpoint.state["handoff"]
    destination[key] = "Next action is lifecycle read-only review"
    checkpoint.seal()
    with pytest.raises(VERIFY["VerificationFailure"], match="Ephemeral|durable handoff"):
        checkpoint.check("worktree")


SEMANTIC_FAILURES = [
    ("failed-test", lambda s: s["test_baseline"]["accepted"]["full"].update(failed=1)),
    ("empty-tests", lambda s: s.update(test_baseline={})),
    ("verification-fail", lambda s: s["verification"].update(status="FAIL")),
    ("high-blocker", lambda s: s["known_blockers"].append({"id": "fixture", "severity": "HIGH", "blocking": True})),
    ("missing-handoff", lambda s: s.update(handoff={})),
    ("commit-authority", lambda s: s.update(commit_authorized=True)),
    ("live-authority", lambda s: s["live_authority"].update(network=True)),
    ("review-fail", lambda s: s["verification"]["independent_review"].update(status="FAIL")),
]


@pytest.mark.parametrize("mode", ["worktree", "staged", "committed"])
@pytest.mark.parametrize("label,mutate", SEMANTIC_FAILURES, ids=[item[0] for item in SEMANTIC_FAILURES])
def test_invalid_state_cannot_be_legitimized_by_resealing(checkpoint, mode, label, mutate):
    # S1-S7 plus active review: reseal to ensure the semantic guard, not a stale digest, rejects it.
    mutate(checkpoint.state)
    checkpoint.seal()
    if mode != "worktree":
        checkpoint.stage()
    if mode == "committed":
        checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="evidence|blocker|handoff|cannot grant|review"):
        checkpoint.check(mode)


@pytest.mark.parametrize("label,mutate", [
    ("bool-passed", lambda s: s["test_baseline"]["accepted"]["full"].update(passed=True)),
    ("float-failed", lambda s: s["test_baseline"]["accepted"]["full"].update(failed=0.0)),
    ("negative-skipped", lambda s: s["test_baseline"]["accepted"]["full"].update(skipped=-1)),
    ("bad-total", lambda s: s["test_baseline"]["accepted"]["full"].update(collected=999)),
    ("subset-total", lambda s: s["test_baseline"]["accepted"]["targeted"].update(passed=2,collected=2)),
    ("bad-algorithm", lambda s: s["verification"].update(digest_algorithm="sha256-path-content-lf-v1")),
    ("bad-mode", lambda s: s["verification"].update(mode="unknown")),
    ("bad-time", lambda s: s["verification"].update(verified_at_utc="tomorrow")),
    ("bad-review-status", lambda s: s["verification"]["independent_review"].update(status="UNKNOWN")),
    ("missing-authority", lambda s: s["live_authority"].pop("external_api")),
    ("dirty-repo-evidence", lambda s: s["verification"].update(repository_unchanged_during_gate=False)),
    ("blocked-worker-evidence", lambda s: s["verification"].update(worker_blocked_side_effects=["fixture"])),
])
def test_invalid_evidence_types_and_consistency_rejected(checkpoint, label, mutate):
    mutate(checkpoint.state)
    checkpoint.seal()
    with pytest.raises(VERIFY["VerificationFailure"]):
        checkpoint.check("worktree")


@pytest.mark.parametrize("mode", ["worktree", "staged", "committed"])
@pytest.mark.parametrize("field", ["tests", "review", "handoff", "deferred", "historical_digest"])
def test_semantically_valid_state_edit_cannot_reuse_approved_digest(checkpoint, mode, field):
    # S10-S12, S15: leave the old digest; State validation alone accepts these historical edits.
    if field == "tests":
        checkpoint.state["test_baseline"]["accepted"]["full"].update(passed=2,collected=2)
    elif field == "review":
        checkpoint.state["verification"]["independent_review"]["reviewers"][0]["scope"] = "different review scope"
    elif field == "handoff":
        checkpoint.state["handoff"]["limitations"] = ["different retained limitation"]
    elif field == "deferred":
        checkpoint.state["deferred_findings"] = [{"id": "fixture", "blocking": False}]
    else:
        checkpoint.state["verification_history"] = [{"status": "FAIL", "input_digest": "1" * 64}]
    VERIFY["check_state"](checkpoint.state)
    checkpoint.save_state()
    if mode != "worktree":
        checkpoint.stage()
    if mode == "committed":
        checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="digest/approval"):
        checkpoint.check(mode)


@pytest.mark.parametrize("mode", ["worktree", "staged", "committed"])
@pytest.mark.parametrize("field", ["baseline_head", "approved_change_paths"])
def test_identity_or_manifest_edit_cannot_reuse_approved_digest(checkpoint, mode, field):
    if field == "baseline_head":
        checkpoint.state[field] = "1" * 40
    else:
        checkpoint.state[field] = sorted([*checkpoint.scope, "AGENTS.md"])
    checkpoint.save_state()
    if mode != "worktree":
        checkpoint.stage()
    if mode == "committed":
        checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="parent|scope|digest/approval"):
        checkpoint.check(mode)


def test_state_formatting_is_semantic_and_digest_field_has_fixed_point(checkpoint):
    # S13-S14: the active digest is the sole self-reference exclusion.
    original = (checkpoint.root / "PROJECT_STATE.json").read_bytes()
    expected = checkpoint.state["verification"]["input_digest"]
    checkpoint.write("PROJECT_STATE.json", json.dumps(checkpoint.state, sort_keys=True, separators=(",", ":")))
    assert checkpoint.check("worktree")["input_digest"] == expected
    checkpoint.stage()
    checkpoint.commit()
    assert checkpoint.check("committed")["input_digest"] == expected
    altered = deepcopy(checkpoint.state)
    altered["verification"]["input_digest"] = "f" * 64
    changed = json.dumps(altered).encode()
    canonical = VERIFY["state_content"]
    assert canonical(original, projection=True) == canonical(changed, projection=True)
    assert canonical(original) != canonical(changed)


@pytest.mark.parametrize("mode", ["worktree", "staged", "committed"])
def test_changing_only_active_digest_still_rejects_checkpoint(checkpoint, mode):
    checkpoint.state["verification"]["input_digest"] = "f" * 64
    checkpoint.save_state()
    if mode != "worktree":
        checkpoint.stage()
    if mode == "committed":
        checkpoint.commit()
    with pytest.raises(VERIFY["VerificationFailure"], match="digest/approval"):
        checkpoint.check(mode)


def test_historical_failed_review_is_retained_without_blocking_resolved_acceptance(checkpoint):
    checkpoint.state["review_history"] = [{"status": "FAIL", "findings": ["LC-01", "LC-02"]}]
    checkpoint.seal()
    checkpoint.stage()
    checkpoint.commit()
    assert checkpoint.check("committed")["state"]["review_history"][0]["status"] == "FAIL"


@pytest.mark.parametrize("content", [b'{"verification":{},"verification":{}}', b'{"x":NaN}', b'{"x":Infinity}', b'[]'])
def test_ambiguous_or_non_json_state_is_rejected(content):
    with pytest.raises(VERIFY["VerificationFailure"]):
        VERIFY["state_content"](content, projection=True)


def test_symlink_reported_by_filesystem_is_rejected_before_digest(checkpoint, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == checkpoint.root / "new.txt" or original(path))
    with pytest.raises(VERIFY["VerificationFailure"], match="Invalid approved path"):
        checkpoint.check("worktree")
