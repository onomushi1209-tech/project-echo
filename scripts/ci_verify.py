"""Ordinary checkout regression gate; never checkpoint approval or Git authority."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_echo_ci_guard", ROOT / "scripts/verify.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class CIStageFailure(gate.VerificationFailure):
    def __init__(self, stage: str, identity: dict, *, hygiene_failed: bool = False):
        super().__init__("CI stage failed: " + stage)
        self.stage = stage
        self.identity = identity
        self.hygiene_failed = hygiene_failed


def checkout_identity(expected_sha: str) -> dict:
    """Bind execution files to HEAD, without interpreting checkpoint State."""
    gate.require(bool(re.fullmatch(r"[0-9a-f]{40}", expected_sha)), "Invalid expected SHA")
    gate.require(Path(gate.git("rev-parse", "--show-toplevel").strip()).resolve() == ROOT,
                 "Checkout root mismatch")
    # Linked worktrees are deliberately outside this initial CI adapter's scope.
    gate.require((ROOT / ".git").is_dir() and not (ROOT / ".git").is_symlink(),
                 "CI needs a standalone checkout")
    head = gate.git("rev-parse", "HEAD").strip()
    gate.require(head == expected_sha, "Expected SHA differs from HEAD")
    gate.require(not gate.status_entries(), "CI needs a clean checkout and index")
    contents = gate.git_contents("committed")
    gate.require(bool(contents) and gate.git_contents("staged") == contents,
                 "Index differs from tested tree")
    for name, content in contents.items():
        path = ROOT / name
        gate.require(path.is_file() and not path.is_symlink() and gate.inside(path, ROOT),
                     "Unsafe checkout input")
        # Use the existing text normalization, but no State acceptance/digest check.
        gate.require(gate.canonical_content(name, path.read_bytes()) == gate.canonical_content(name, content),
                     "Filesystem differs from tested tree")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    gate.require(project.get("project", {}).get("name") == "project-echo", "Project identity mismatch")
    return {"tested_sha": head, "tree_entries": len(contents)}


class TestResults:
    """Count collection as well as execution, so empty/skipped suites fail closed."""

    def __init__(self):
        self.counts = dict(collected=0, passed=0, failed=0, skipped=0, warnings=0)

    def pytest_collection_finish(self, session):
        self.counts["collected"] = len(session.items)

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when != "call" and report.outcome != "passed"):
            self.counts[report.outcome] += 1

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.counts["warnings"] += 1


def worker(stage: str, temporary_root: Path) -> dict:
    gate.require(stage in ("sanity", "full"), "Invalid CI worker stage")
    gate.require(not gate.inside(temporary_root, ROOT) and not gate.inside(ROOT, temporary_root),
                 "Worker needs an external temporary root")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / "src"))
    blocked = gate.install_worker_guard(temporary_root)
    result = {"stage": stage, "exit": 1}
    # Pytest tracebacks/test prints can contain environment values. Only typed,
    # valueless summary fields cross the worker boundary, even on exceptions.
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            if stage == "sanity":
                sanity = gate.sanity()
                result.update(modules=sanity["modules"], cli_help_checks=sanity["cli_help_checks"], exit=0)
            else:
                import pytest
                results = TestResults()
                code = int(pytest.main([
                    "-q", "-ra", "-x", "--capture=sys", "-p", "no:cacheprovider",
                    "--basetemp", str(temporary_root / "pytest"), "tests",
                ], plugins=[results]))
                result.update(results.counts)
                result["exit"] = code if code else int(
                    results.counts["collected"] == 0
                    or results.counts["passed"] != results.counts["collected"]
                    or results.counts["failed"] != 0 or results.counts["skipped"] != 0)
        except Exception:
            result["exit"] = 1
    result["blocked_count"] = len(blocked)
    if blocked:
        result["exit"] = 1
    return result


def read_worker_result(completed, stage: str) -> dict:
    """Never relay raw stdout/stderr or exception text to a CI failure report."""
    gate.require(completed.returncode == 0, "CI worker failed: " + stage)
    try:
        lines = [line for line in completed.stdout.splitlines() if line.startswith("CI_STAGE_RESULT=")]
        gate.require(len(lines) == 1, "Missing/ambiguous CI worker result")
        result = json.loads(lines[0].split("=", 1)[1])
        keys = {"stage", "exit", "blocked_count"} | (
            {"modules", "cli_help_checks"} if stage == "sanity"
            else {"collected", "passed", "failed", "skipped", "warnings"})
        gate.require(isinstance(result, dict) and set(result) == keys and result["stage"] == stage,
                     "Invalid CI worker result")
        gate.require(all(type(value) is int and value >= 0 for key, value in result.items() if key != "stage"),
                     "Invalid CI worker counts")
        gate.require(result["exit"] == result["blocked_count"] == 0, "CI worker reported failure")
        if stage == "sanity":
            gate.require(result["modules"] > 0 and result["cli_help_checks"] > 0, "Empty CI sanity")
        else:
            gate.require(result["collected"] > 0 and result["passed"] == result["collected"]
                         and result["failed"] == result["skipped"] == 0, "Incomplete CI test evidence")
        return result
    except (ValueError, TypeError, KeyError):
        raise gate.VerificationFailure("Invalid CI worker result") from None


def run_stage(stage: str, temporary_root: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", stage,
         "--temporary-root", str(temporary_root)],
        cwd=ROOT, env=gate.isolated_environment(), capture_output=True, text=True, encoding="utf-8",
    )
    return read_worker_result(completed, stage)


def run(expected_sha: str) -> dict:
    gate.require(Path.cwd().resolve() == ROOT, "Run CI from the Project Echo checkout root")
    identity = checkout_identity(expected_sha)
    before = gate.snapshot(ROOT)
    index = (ROOT / ".git/index").read_bytes()
    results = []
    failure = None
    hygiene_failed = False
    stage = "setup"
    try:
        with tempfile.TemporaryDirectory(prefix="project-echo-ci-") as directory:
            temporary_root = Path(directory).resolve()
            gate.require(not gate.inside(temporary_root, ROOT) and not gate.inside(ROOT, temporary_root),
                         "CI needs external temporary storage")
            for stage in ("sanity", "full"):
                results.append(run_stage(stage, temporary_root))
    except Exception:
        failure = CIStageFailure(stage, identity)
    finally:
        try:
            gate.require(gate.snapshot(ROOT) == before and (ROOT / ".git/index").read_bytes() == index,
                         "Repository/index changed during CI; do not auto-clean")
            gate.require(checkout_identity(expected_sha) == identity, "Checkout identity changed during CI")
        except Exception:
            hygiene_failed = True
    if failure is not None:
        failure.hygiene_failed = hygiene_failed
        raise failure
    if hygiene_failed:
        raise CIStageFailure("hygiene", identity, hygiene_failed=True)
    return {"result": "PASS", **identity, "stages": results, "repository_unchanged": True,
            "checkpoint_approval": False, "git_authority": False, "live_authority": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", help="Full SHA supplied by the CI event, including PR merge SHA")
    parser.add_argument("--worker", choices=("sanity", "full"), help=argparse.SUPPRESS)
    parser.add_argument("--temporary-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            gate.require(args.temporary_root is not None, "Missing temporary root")
            result = worker(args.worker, args.temporary_root.resolve())
            print("CI_STAGE_RESULT=" + json.dumps(result))
            return result["exit"]
        gate.require(args.expected_sha is not None, "Expected SHA is required")
        result = run(args.expected_sha)
        print("CI_RESULT=" + json.dumps(result))
        return 0
    except Exception as error:
        # Exception text (including OS paths and external worker output) is untrusted.
        result = {"result": "FAIL", "stage": "checkout_or_hygiene", "checkpoint_approval": False,
                  "git_authority": False, "live_authority": False}
        if isinstance(error, CIStageFailure):
            result.update(stage=error.stage, hygiene_failed=error.hygiene_failed, **error.identity)
        print("CI_RESULT=" + json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
