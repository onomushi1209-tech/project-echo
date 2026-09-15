"""Ordinary CI identity and fail-closed execution; all Git writes are fixtures."""

import hashlib
import json
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import zlib

import pytest
import yaml

SOURCE = Path(__file__).resolve().parents[1]
CI = runpy.run_path(str(SOURCE / "scripts/ci_verify.py"))
GATE = CI["gate"]


def success(stage):
    result = dict(stage=stage, exit=0, blocked_count=0)
    result.update(dict(modules=2, cli_help_checks=1) if stage == "sanity"
                  else dict(collected=3, passed=3, failed=0, skipped=0, warnings=0))
    return result


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setitem(CI["run"].__globals__, "ROOT", root)
    monkeypatch.setattr(GATE, "ROOT", root)
    monkeypatch.chdir(root)
    GATE.git("init", "--initial-branch=main", "--template=")
    (root / "pyproject.toml").write_text('[project]\nname="project-echo"\n', encoding="utf-8")
    # Deliberately not a checkpoint manifest: ordinary CI does not validate it.
    (root / "PROJECT_STATE.json").write_text(json.dumps({"baseline_head": "historical",
        "commit_authorized": False, "live_authority": {"network": False}}), encoding="utf-8")
    (root / "engine.py").write_text("value = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("data/*.db\n", encoding="utf-8")
    GATE.git("add", "--", "pyproject.toml", "PROJECT_STATE.json", "engine.py", ".gitignore")
    GATE.git("commit", "-m", "fixture checkpoint")
    head = GATE.git("rev-parse", "HEAD").strip()
    calls = []

    def run_stage(stage, temporary_root):
        calls.append(stage)
        return success(stage)

    monkeypatch.setitem(CI["run"].__globals__, "run_stage", run_stage)
    original_temp = CI["tempfile"].TemporaryDirectory
    monkeypatch.setattr(CI["tempfile"], "TemporaryDirectory",
                        lambda **kwargs: original_temp(dir=tmp_path, **kwargs))
    return SimpleNamespace(root=root, head=head, calls=calls)


def test_ci_01_15_clean_commit_passes_once_without_state_or_authority_changes(checkout):
    state = (checkout.root / "PROJECT_STATE.json").read_bytes()
    result = CI["run"](checkout.head)
    assert result["result"] == "PASS" and result["tested_sha"] == checkout.head
    assert checkout.calls == ["sanity", "full"]
    assert all(result[key] is False for key in ("checkpoint_approval", "git_authority", "live_authority"))
    assert (checkout.root / "PROJECT_STATE.json").read_bytes() == state


def test_ci_02_detached_head(checkout):
    (checkout.root / ".git/HEAD").write_text(checkout.head + "\n", encoding="ascii")
    assert GATE.git("branch", "--show-current").strip() == ""
    assert CI["run"](checkout.head)["result"] == "PASS"


def test_ci_03_real_merge_commit(checkout):
    # Create-only loose commit objects in the fixture, using its real tree.
    # This needs no expanded Git subprocess allowlist or real index mutation.
    objects = checkout.root / ".git/objects"
    original = zlib.decompress((objects / checkout.head[:2] / checkout.head[2:]).read_bytes())
    content = original.split(b"\0", 1)[1]
    tree = content.splitlines()[0]

    def commit(parents, message):
        body = tree + b"\n" + b"".join(b"parent " + p.encode() + b"\n" for p in parents)
        body += b"author Fixture <fixture@example.invalid> 1 +0000\ncommitter Fixture <fixture@example.invalid> 1 +0000\n\n" + message
        raw = b"commit " + str(len(body)).encode() + b"\0" + body
        oid = hashlib.sha1(raw).hexdigest()
        path = objects / oid[:2] / oid[2:]
        path.parent.mkdir(exist_ok=True)
        with path.open("xb") as stream:
            stream.write(zlib.compress(raw))
        return oid

    side = commit([checkout.head], b"side\n")
    merge = commit([checkout.head, side], b"PR merge\n")
    (checkout.root / ".git/HEAD").write_text(merge + "\n", encoding="ascii")
    assert GATE.git("rev-list", "--parents", "-n", "1", "HEAD").split() == [merge, checkout.head, side]
    assert CI["run"](merge)["tested_sha"] == merge


def test_ci_04_wrong_sha(checkout):
    with pytest.raises(GATE.VerificationFailure, match="SHA differs"):
        CI["run"]("0" * 40)
    assert checkout.calls == []


@pytest.mark.parametrize("name", ["engine.py", "unexpected.txt"])
def test_ci_05_06_dirty_or_untracked(checkout, name):
    (checkout.root / name).write_text("drift\n", encoding="utf-8")
    with pytest.raises(GATE.VerificationFailure, match="clean checkout"):
        CI["run"](checkout.head)
    assert checkout.calls == []


def test_ci_07_worker_nonzero_stops_immediately(checkout, monkeypatch):
    def failed(stage, temporary_root):
        checkout.calls.append(stage)
        return CI["read_worker_result"](SimpleNamespace(returncode=2, stdout="", stderr=""), stage)
    monkeypatch.setitem(CI["run"].__globals__, "run_stage", failed)
    with pytest.raises(CI["CIStageFailure"], match="sanity"):
        CI["run"](checkout.head)
    assert checkout.calls == ["sanity"]


def test_worker_failure_and_drift_preserve_first_stage_and_identity(checkout, monkeypatch, capsys):
    def failed(stage, temporary_root):
        checkout.calls.append(stage)
        (checkout.root / "engine.py").write_text("fixture drift\n", encoding="utf-8")
        return CI["read_worker_result"](SimpleNamespace(returncode=2, stdout="", stderr=""), stage)
    monkeypatch.setitem(CI["run"].__globals__, "run_stage", failed)
    assert CI["main"](["--expected-sha", checkout.head]) == 1
    result = json.loads(capsys.readouterr().out.split("CI_RESULT=", 1)[1])
    assert result["stage"] == "sanity" and result["tested_sha"] == checkout.head
    assert result["hygiene_failed"] is True
    assert checkout.calls == ["sanity"]


@pytest.mark.parametrize("case", ["collection", "zero", "skip", "pass"])
def test_ci_08_09_full_worker_collection_and_all_pass_policy(tmp_path, monkeypatch, case):
    monkeypatch.setattr(GATE, "install_worker_guard", lambda root: [])
    calls = []
    def pytest_main(args, plugins):
        calls.append(args)
        plugin = plugins[0]
        items = [] if case in ("collection", "zero") else [object()]
        plugin.pytest_collection_finish(SimpleNamespace(items=items))
        if items:
            plugin.pytest_runtest_logreport(SimpleNamespace(when="call", outcome="skipped" if case == "skip" else "passed"))
        return 2 if case == "collection" else 0
    monkeypatch.setattr(pytest, "main", pytest_main)
    result = CI["worker"]("full", tmp_path)
    assert (result["exit"] == 0) == (case == "pass")
    assert len(calls) == 1 and calls[0][-1] == "tests"


@pytest.mark.parametrize("event", ["repository", "database", "network", "dotenv"])
def test_ci_10_11_12_worker_uses_real_guard_and_rejects_caught_side_effects(tmp_path, monkeypatch, event):
    hooks = []
    monkeypatch.setattr(GATE.sys, "addaudithook", hooks.append)
    # Capture the actual production hook without permanently adding it to pytest.
    def attack():
        try:
            if event == "repository":
                hooks[0]("open", (SOURCE / "PROJECT_STATE.json", "w", os.O_WRONLY))
            elif event == "database":
                hooks[0]("sqlite3.connect", (str(SOURCE / "data/echo.db"),))
            elif event == "dotenv":
                hooks[0]("open", (SOURCE / ".env", "r", os.O_RDONLY))
            else:
                hooks[0]("socket.connect", (None, ("business.invalid", 443)))
        except GATE.VerificationFailure:
            pass  # Swallowing an attempted side effect must still fail the worker.
        return dict(modules=1, cli_help_checks=1)
    monkeypatch.setattr(GATE, "sanity", attack)
    result = CI["worker"]("sanity", tmp_path)
    assert result["exit"] != 0 and result["blocked_count"] == 1


@pytest.mark.parametrize("drift", ["ignored_db", "index", "head"])
def test_ci_13_post_run_drift(checkout, monkeypatch, drift):
    (checkout.root / "data").mkdir()
    database = checkout.root / "data/echo.db"
    database.write_bytes(b"fixture database")
    def mutate(stage, temporary_root):
        if drift == "ignored_db":
            database.write_bytes(b"changed")
        elif drift == "index":
            with (checkout.root / ".git/index").open("ab") as stream:
                stream.write(b"drift")
        else:
            GATE.git("commit", "--allow-empty", "-m", "fixture checkpoint")
        return success(stage)
    monkeypatch.setitem(CI["run"].__globals__, "run_stage", mutate)
    with pytest.raises(GATE.VerificationFailure):
        CI["run"](checkout.head)


def test_ci_14_failure_report_never_echoes_environment_or_worker_output(checkout, monkeypatch, capsys):
    marker = "sk-" + "synthetic" * 8
    monkeypatch.setenv("ECHO_TEST_SECRET", marker)
    def failed(stage, temporary_root):
        completed = SimpleNamespace(returncode=1, stdout=marker, stderr=marker)
        return CI["read_worker_result"](completed, stage)
    monkeypatch.setitem(CI["run"].__globals__, "run_stage", failed)
    assert CI["main"](["--expected-sha", checkout.head]) == 1
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    assert '"stage": "sanity"' in output.out and checkout.head in output.out


def test_worker_discards_prints_and_exception_values(tmp_path, monkeypatch, capsys):
    marker = "fixture-confidential-value"
    monkeypatch.setenv("BUSINESS_TOKEN", marker)
    monkeypatch.setattr(GATE, "install_worker_guard", lambda root: [])
    def fail():
        print(os.environ["BUSINESS_TOKEN"])
        raise RuntimeError(marker)
    monkeypatch.setattr(GATE, "sanity", fail)
    assert CI["worker"]("sanity", tmp_path)["exit"] == 1
    assert marker not in str(capsys.readouterr())


def test_ci_16_checkpoint_verifier_is_independent(checkout):
    assert CI["run"](checkout.head)["result"] == "PASS"
    with pytest.raises(GATE.VerificationFailure, match="State identity/schema"):
        GATE.verify_checkpoint("committed")
    # The existing test_verification suite separately exercises valid lifecycle
    # manifests, all three modes, digest integrity and their rejection cases.


@pytest.mark.parametrize("change", ["missing", "zero", "boolean", "secret_field", "skipped"])
def test_parent_rejects_false_success_evidence(change):
    result = success("full")
    if change == "missing": result.pop("collected")
    if change == "zero": result.update(collected=0, passed=0)
    if change == "boolean": result["passed"] = True
    if change == "secret_field": result["untrusted"] = "fixture"
    if change == "skipped": result.update(passed=2, skipped=1)
    completed = SimpleNamespace(returncode=0, stdout="CI_STAGE_RESULT=" + json.dumps(result), stderr="")
    with pytest.raises(GATE.VerificationFailure):
        CI["read_worker_result"](completed, "full")


def test_stderr_warning_with_exit_zero_is_not_failure():
    result = success("full")
    completed = SimpleNamespace(returncode=0, stdout="CI_STAGE_RESULT=" + json.dumps(result), stderr="warning")
    assert CI["read_worker_result"](completed, "full") == result


def test_workflow_and_skill_metadata_contract():
    # BaseLoader preserves GitHub's 'on' key (YAML 1.1 treats it as a Boolean).
    workflow = yaml.load((SOURCE / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"pull_request": {"branches": ["main"]}, "push": {"branches": ["main"]}}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"regression"}
    job = workflow["jobs"]["regression"]
    assert job["runs-on"] == "windows-2025" and job["timeout-minutes"] == "10"
    actions = [step for step in job["steps"] if "uses" in step]
    assert len(actions) == 2
    for action, family in zip(actions, ("actions/checkout", "actions/setup-python")):
        name, sha = action["uses"].split("@")
        assert name == family and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    assert actions[0]["with"] == {"persist-credentials": "false"}
    assert actions[1]["with"] == {"python-version": "3.14.6", "architecture": "x64"}
    last = job["steps"][-1]
    assert last["env"] == {"EXPECTED_CI_SHA": "${{ github.sha }}"}
    assert last["run"] == "python -B scripts/ci_verify.py --expected-sha $env:EXPECTED_CI_SHA"
    assert all("continue-on-error" not in step for step in job["steps"])
    skill = SOURCE / ".agents/skills/echo-checkpoint-review"
    header = (skill / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    metadata = yaml.safe_load(header)
    assert metadata["name"] == skill.name and isinstance(metadata["description"], str)
    policy = yaml.safe_load((skill / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert policy == {"policy": {"allow_implicit_invocation": False}}
