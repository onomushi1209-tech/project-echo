"""Offline verification: python -B scripts/verify.py (no repository writes).

Prints evidence to stdout; never edits state, stages, commits, fetches or
migrates the existing database. See docs/VERIFICATION_GATE.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import pkgutil
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GIT_EXECUTABLE = shutil.which("git")
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".example", ".yaml", ".yml", ".txt", ".xml"}
DIGEST_ALGORITHM = "sha256-path-content-lf-state-v2"
TEST_STAGES = ("verification", "targeted", "step3", "full")
LIVE_AUTHORITIES = ("network", "external_api", "x_posting", "affiliate_integration",
                    "step4", "existing_database_mutation", "scheduler")
RESUME_PROTOCOL = {
    "method": "derive_from_git_and_external_authority",
    "lifecycle_derivation": {
        "worktree": "HEAD == baseline_head; clean index; approved dirty subset: verify worktree, then external review and staging authorization",
        "staged": "HEAD == baseline_head; exact staged scope; no drift: verify staged, then external commit authorization",
        "committed": "clean HEAD with single parent == baseline_head and exact scope: verify committed, then external push review",
    },
    "external_authority_required": ["stage", "commit", "push"],
    "otherwise": "STOP",
}
PROHIBITED_AUTOMATIC_ACTIONS = ["stage", "commit", "push", "network", "external_api",
                                "step4", "affiliate_phase0", "database_migration", "install", "scheduler"]
GIT_PREFIX = ["--no-optional-locks", "--literal-pathspecs", "-c", "core.hooksPath=" + os.devnull,
              "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
              "-c", "commit.gpgsign=false", "-c", "user.name=Echo Verification Fixture",
              "-c", "user.email=fixture@example.invalid"]
TARGETED = [
    "tests/test_ingest.py", "tests/test_research_conflicts.py",
    "tests/test_real_research_brain.py", "tests/test_cli_research.py",
    "tests/test_research_extraction.py", "tests/test_research_source_selection.py",
    "tests/test_architecture.py", "tests/test_verification.py",
]
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
]


class VerificationFailure(RuntimeError):
    pass


def isolated_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in tuple(env):
        if name.startswith(("ECHO_", "GIT_")) or name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"):
            del env[name]
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHON_DOTENV_DISABLED="1", GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_TERMINAL_PROMPT="0")
    return env


def git_environment(fixture: bool = False) -> dict[str, str]:
    env = isolated_environment()
    if fixture:
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return env


def git_bytes(*args: str) -> bytes:
    if GIT_EXECUTABLE is None:
        raise VerificationFailure("Existing Git executable is unavailable")
    fixture = ROOT.resolve() != Path(__file__).resolve().parents[1]
    result = subprocess.run([GIT_EXECUTABLE, *GIT_PREFIX, *args], cwd=ROOT,
                            executable=GIT_EXECUTABLE, env=git_environment(fixture), capture_output=True)
    if result.returncode:
        raise VerificationFailure(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout


def git(*args: str) -> str:
    return git_bytes(*args).decode("utf-8")


def fixture_git_allowed(args: tuple, temporary_root: Path) -> bool:
    """Only bounded Git commands in an isolated test repo may spawn in workers."""
    executable, argv, cwd, env = args
    # Windows audits the serialized command line, POSIX the argument array.
    # Accept only strings that round-trip through Python's own quoting rules.
    if os.name == "nt" and isinstance(argv, str):
        try:
            words = shlex.split(argv, posix=False)
        except ValueError:
            return False
        parsed = [word[1:-1] if word.startswith('"') and word.endswith('"') else word for word in words]
        if subprocess.list2cmdline(parsed) != argv:
            return False
        argv = parsed
    if executable != GIT_EXECUTABLE or not isinstance(argv, (list, tuple)):
        return False
    if list(argv[:1 + len(GIT_PREFIX)]) != [GIT_EXECUTABLE, *GIT_PREFIX]:
        return False
    if not cwd or not inside(cwd, temporary_root) or inside(cwd, Path(__file__).resolve().parents[1]):
        return False
    expected_env = git_environment(True)
    if env is None or {k: v for k, v in env.items() if k.startswith("GIT_")} != {
        k: v for k, v in expected_env.items() if k.startswith("GIT_")
    }:
        return False
    command = list(argv[1 + len(GIT_PREFIX):])
    repository = Path(cwd).resolve()
    git_dir = repository / ".git"
    if command == ["init", "--initial-branch=main", "--template="]:
        return not git_dir.exists()
    if not git_dir.is_dir() or not inside(git_dir, repository) or git_dir.is_symlink():
        return False
    if (git_dir / "commondir").exists() or (git_dir / "objects/info/alternates").exists():
        return False
    if command[:2] == ["add", "--"]:
        return len(command) > 2 and all(
            safe_path(name) and inside(repository / name, repository)
            and (repository / name).is_file() and not (repository / name).is_symlink()
            for name in command[2:]
        )
    if command in (["commit", "-m", "fixture checkpoint"],
                   ["commit", "--allow-empty", "-m", "fixture checkpoint"]):
        return True
    if command in (["branch", "--show-current"], ["rev-parse", "HEAD"],
                   ["rev-parse", "--show-toplevel"], ["rev-list", "--parents", "-n", "1", "HEAD"],
                   ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                   ["ls-files", "--stage", "-z"], ["ls-tree", "-r", "-z", "--full-tree", "HEAD"]):
        return True
    if len(command) == 3 and command[:2] == ["cat-file", "blob"]:
        return bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", command[2]))
    prefix = ["diff", "--no-ext-diff", "--no-textconv", "--no-renames"]
    if command[:4] == prefix:
        tail = command[4:]
        return tail in (["--check"], ["--cached", "--check"], ["--cached", "--name-status", "-z"],
                        ["--name-status", "-z", "HEAD^", "HEAD"])
    return False


def snapshot(root: Path) -> dict[str, tuple]:
    """Preserve ignored artifacts too; secret/local settings get metadata only."""
    result = {}
    def unreadable(error):
        raise VerificationFailure("Cannot inspect repository path: " + str(error.filename))
    for directory, dirs, names in os.walk(root, onerror=unreadable):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            stat = path.stat()
            private = name.startswith(".env") or ".claude" in path.parts or any(
                word in name.lower() for word in ("credential", "secret")
            )
            result[relative] = (stat.st_size, stat.st_mtime_ns,
                                None if private else hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def inside(path, root: Path) -> bool:
    return isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).resolve().is_relative_to(root.resolve())


def allowed_write(path, temporary_root: Path) -> bool:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    name = os.fsdecode(path)
    return os.path.normcase(os.path.abspath(name)) == os.path.normcase(os.path.abspath(os.devnull)) or inside(name, temporary_root)


def install_worker_guard(temporary_root: Path) -> list[str]:
    blocked = []
    def reject(event):
        blocked.append(event)
        raise VerificationFailure("Blocked verification side effect: " + event)
    def guard(event, args):
        if event == "open":
            path, mode, flags = args
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            if writes and not allowed_write(path, temporary_root):
                reject(event)
            if not writes and isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).name == ".env":
                reject(".env read")
        elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"):
            if not inside(args[0], temporary_root):
                reject(event)
        elif event in ("os.rename", "os.link", "os.symlink"):
            if not all(inside(path, temporary_root) for path in args[:2]):
                reject(event)
        elif event == "sqlite3.connect":
            if args[0] != ":memory:" and not inside(args[0], temporary_root):
                reject(event)
        elif event == "subprocess.Popen":
            if not fixture_git_allowed(args, temporary_root):
                reject(event)
        elif event.startswith("socket.") or event in ("os.system", "os.exec", "os.posix_spawn"):
            reject(event)
    sys.addaudithook(guard)
    return blocked


def check_scope(status: str, allowed: list[str]) -> None:
    for line in status.splitlines():
        if line[:3] not in (" M ", "?? ") or line[3:] not in allowed:
            raise VerificationFailure("Unexpected Git scope/status: " + line)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def timestamp(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%dT%H:%M:%SZ") == value
    except ValueError:
        return False


def parse_state(content: bytes) -> dict:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate State JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise VerificationFailure("Non-finite State JSON number")
    try:
        state = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=invalid_constant)
        require(isinstance(state, dict), "State JSON must be an object")
        return state
    except (UnicodeError, ValueError) as error:
        raise VerificationFailure("Invalid State JSON") from error


def state_content(content: bytes, *, projection: bool = False) -> bytes:
    state = parse_state(content)
    if projection:
        require(isinstance(state.get("verification"), dict) and "input_digest" in state["verification"],
                "Missing State self-digest field")
        # Mask this exact value only. Historical digests and all unknown metadata remain bound.
        state["verification"]["input_digest"] = "__SELF_DIGEST__"
    try:
        return json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError) as error:
        raise VerificationFailure("State cannot be canonicalized") from error


def check_state(state: dict) -> None:
    required = ("schema_version", "state_model", "project", "branch", "baseline_head", "checkpoint_subject",
                "completed_steps", "test_baseline", "known_blockers", "live_authority", "handoff",
                "approved_change_paths", "verification", "commit_authorized")
    require(isinstance(state, dict) and all(key in state for key in required), "Project State identity/schema mismatch")
    require(type(state["schema_version"]) is int and state["schema_version"] == 2
            and state["state_model"] == "durable_checkpoint" and state["project"] == "Project Echo",
            "Project State identity/schema mismatch")
    require(not any(key in state for key in ("current_step", "current_readiness", "next_authorized_action", "working_tree_checkpoint")),
            "Ephemeral State cursor is unsupported")
    authority = state["live_authority"]
    require(isinstance(authority, dict) and set(authority) == set(LIVE_AUTHORITIES)
            and all(value is False for value in authority.values()) and state["commit_authorized"] is False,
            "This offline gate cannot grant live or commit authority")
    require(nonempty(state["branch"]) and isinstance(state["baseline_head"], str)
            and re.fullmatch(r"[0-9a-f]{40}", state["baseline_head"]), "Invalid checkpoint parent/branch")
    require(nonempty(state["checkpoint_subject"]) and isinstance(state["completed_steps"], list)
            and state["completed_steps"] and all(nonempty(item) for item in state["completed_steps"]),
            "Invalid checkpoint description")
    allowed = state["approved_change_paths"]
    require(isinstance(allowed, list) and allowed and all(safe_path(name) for name in allowed), "Invalid checkpoint path set")
    require(allowed == sorted(allowed) and len({name.casefold() for name in allowed}) == len(allowed)
            and "PROJECT_STATE.json" in allowed, "Invalid checkpoint path set")
    require(type(state["known_blockers"]) is list and not state["known_blockers"], "Unresolved checkpoint blockers")
    baseline = state["test_baseline"]
    require(isinstance(baseline, dict) and "current" not in baseline and isinstance(baseline.get("accepted"), dict),
            "Missing accepted test evidence")
    accepted = baseline["accepted"]
    for stage in TEST_STAGES:
        counts = accepted.get(stage)
        require(isinstance(counts, dict) and all(type(counts.get(key)) is int and counts[key] >= 0
                for key in ("passed", "failed", "skipped", "warnings")), "Invalid test evidence: " + stage)
        require(counts["passed"] > 0 and counts["failed"] == 0, "Non-passing test evidence: " + stage)
        for total in ("collected", "total"):
            if total in counts:
                require(type(counts[total]) is int and counts[total] == counts["passed"] + counts["failed"] + counts["skipped"],
                        "Inconsistent test total: " + stage)
    full_total = accepted["full"]["passed"] + accepted["full"]["skipped"]
    require(all(accepted[stage]["passed"] + accepted[stage]["skipped"] <= full_total for stage in TEST_STAGES),
            "Test subset exceeds full test total")
    verification = state["verification"]
    require(isinstance(verification, dict) and verification.get("status") == "PASS"
            and verification.get("mode") in ("worktree", "staged", "committed")
            and verification.get("evidence_type") == "guarded_offline_workers"
            and timestamp(verification.get("verified_at_utc")), "Invalid accepted verification evidence")
    require(verification.get("digest_algorithm") == DIGEST_ALGORITHM
            and isinstance(verification.get("input_digest"), str)
            and re.fullmatch(r"[0-9a-f]{64}", verification["input_digest"]), "Invalid verification digest/algorithm")
    for metric in ("imported_modules", "cli_help_routes"):
        require(type(verification.get(metric)) is int and verification[metric] > 0, "Invalid sanity evidence")
    for metric in ("repository_unchanged_during_gate", "index_unchanged_during_gate", "existing_database_unchanged"):
        if metric in verification:
            require(verification[metric] is True, "Contradictory hygiene evidence")
    if "worker_blocked_side_effects" in verification:
        require(type(verification["worker_blocked_side_effects"]) is list
                and not verification["worker_blocked_side_effects"], "Contradictory worker evidence")
    review = verification.get("independent_review")
    require(isinstance(review, dict) and review.get("status") == "PASS" and timestamp(review.get("reviewed_at_utc")),
            "Invalid acceptance review")
    reviewers = review.get("reviewers")
    require(isinstance(reviewers, list) and reviewers and all(isinstance(item, dict)
            and nonempty(item.get("name")) and nonempty(item.get("scope")) and item.get("status") == "PASS"
            for item in reviewers), "Invalid acceptance reviewers")
    handoff = state["handoff"]
    require(isinstance(handoff, dict) and not any(key in handoff for key in ("exact_next_action", "what_remains", "next_action"))
            and handoff.get("resume_protocol") == RESUME_PROTOCOL
            and handoff.get("prohibited_automatic_actions") == PROHIBITED_AUTOMATIC_ACTIONS, "Invalid durable handoff/resume protocol")
    for name in ("AGENTS.md", "docs/VERIFICATION_GATE.md", "PROJECT_STATE.json"):
        if not (ROOT / name).is_file():
            raise VerificationFailure("Missing foundation document: " + name)
    for name in state["approved_change_paths"]:
        if not inside(ROOT / name, ROOT) or not (ROOT / name).is_file() or (ROOT / name).is_symlink():
            raise VerificationFailure("Invalid approved path: " + name)


def safe_path(name) -> bool:
    if not isinstance(name, str) or not name or any(c in name for c in ('\\', ':', '"', "'")) or any(ord(c) < 32 for c in name):
        return False
    parts = name.split("/")
    return not any(part.casefold() in ("", ".", "..", ".git", ".env", "__pycache__", ".pytest_cache", ".claude")
                   or part.endswith((".", " ")) for part in parts)


def canonical_content(name: str, content: bytes) -> bytes:
    # Only UTF-8 text has CRLF normalized. No whitespace/BOM/content is discarded.
    if Path(name).suffix in TEXT_SUFFIXES or Path(name).name in (".gitignore", ".gitattributes"):
        text = content.decode("utf-8")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise VerificationFailure("Potential secret pattern in " + name + " (value suppressed)")
        if name == "PROJECT_STATE.json":
            return state_content(content)  # Semantic equality includes the unmasked digest value.
        return content.replace(b"\r\n", b"\n")
    return content


def input_digest(paths: list[str], contents: dict[str, bytes] | None = None) -> str:
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        if not safe_path(name):
            raise VerificationFailure("Unsafe input path")
        content = canonical_content(name, (ROOT / name).read_bytes() if contents is None else contents[name])
        if name == "PROJECT_STATE.json":
            content = state_content(content, projection=True)
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def git_contents(mode: str) -> dict[str, bytes]:
    listing = git("ls-tree", "-r", "-z", "--full-tree", "HEAD") if mode == "committed" else git("ls-files", "--stage", "-z")
    contents = {}
    for entry in listing.split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        fields = metadata.split()
        file_mode, oid = (fields[0], fields[2]) if mode == "committed" else fields[:2]
        if file_mode not in ("100644", "100755") or (mode != "committed" and fields[2] != "0") or not safe_path(name):
            raise VerificationFailure("Unsupported Git entry: " + name)
        if name in contents:
            raise VerificationFailure("Duplicate Git entry: " + name)
        contents[name] = git_bytes("cat-file", "blob", oid)
    return contents


def status_entries() -> list[tuple[str, str]]:
    entries = []
    for entry in git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if entry:
            if len(entry) < 4 or entry[2] != " ":
                raise VerificationFailure("Unsupported Git status")
            entries.append((entry[:2], entry[3:]))
    return entries


def changed_paths(*refs: str) -> set[str]:
    parts = git("diff", "--no-ext-diff", "--no-textconv", "--no-renames", *refs).split("\0")
    changes = {}
    for index in range(0, len(parts) - 1, 2):
        status, name = parts[index:index + 2]
        if status not in ("A", "M") or not safe_path(name):
            raise VerificationFailure("Unsupported checkpoint change: " + status)
        changes[name] = status
    return set(changes)


def verify_checkpoint(mode: str) -> dict:
    """Same read-only lifecycle predicate for CLI and real temporary Git tests."""
    if mode not in ("worktree", "staged", "committed"):
        raise VerificationFailure("Unknown lifecycle mode")
    if Path(git("rev-parse", "--show-toplevel").strip()).resolve() != ROOT.resolve():
        raise VerificationFailure("Git root mismatch")
    state = parse_state((ROOT / "PROJECT_STATE.json").read_bytes())
    check_state(state)
    branch = git("branch", "--show-current").strip()
    head = git("rev-parse", "HEAD").strip()
    if branch != state["branch"]:
        raise VerificationFailure("Branch differs from checkpoint state")
    if mode == "committed":
        identity = git("rev-list", "--parents", "-n", "1", "HEAD").split()
        if len(identity) != 2 or identity[0] != head or identity[1] != state["baseline_head"]:
            raise VerificationFailure("Checkpoint must have exactly one parent equal to baseline_head")
    elif head != state["baseline_head"]:
        raise VerificationFailure("HEAD differs from checkpoint parent")
    entries = status_entries()
    allowed = set(state["approved_change_paths"])
    if mode == "worktree":
        if any(status not in (" M", "??") or name not in allowed for status, name in entries):
            raise VerificationFailure("Unexpected worktree scope/status")
    elif mode == "staged":
        if any(status not in ("M ", "A ") or name not in allowed for status, name in entries):
            raise VerificationFailure("Unexpected staged scope or unstaged drift")
        if changed_paths("--cached", "--name-status", "-z") != allowed:
            raise VerificationFailure("Staged path set differs from checkpoint scope")
    else:
        if entries:
            raise VerificationFailure("Committed mode requires clean worktree and index")
        if changed_paths("--name-status", "-z", "HEAD^", "HEAD") != allowed:
            raise VerificationFailure("Committed path set differs from checkpoint scope")
    git("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--check")
    git("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--cached", "--check")
    contents = git_contents(mode)
    if mode == "worktree":
        paths = set(contents) | allowed
        if any(not inside(ROOT / name, ROOT) or not (ROOT / name).is_file() or (ROOT / name).is_symlink() for name in paths):
            raise VerificationFailure("Unsafe worktree input")
        contents = {name: (ROOT / name).read_bytes() for name in paths}
    else:
        # State equality includes its active digest; only projection hashing masks it.
        if "PROJECT_STATE.json" not in contents:
            raise VerificationFailure("Checkpoint State is missing from Git content")
        check_state(parse_state(contents["PROJECT_STATE.json"]))
        for name, content in contents.items():
            path = ROOT / name
            if path.is_symlink() or not inside(path, ROOT) or not path.is_file() or canonical_content(name, path.read_bytes()) != canonical_content(name, content):
                raise VerificationFailure("Filesystem differs from checkpoint content: " + name)
        if mode == "committed" and git_contents("staged") != contents:
            raise VerificationFailure("Index differs from committed content")
    digest = input_digest(list(contents), contents)
    if digest != state["verification"]["input_digest"]:
        raise VerificationFailure("Checkpoint digest/approval evidence mismatch")
    return {"mode": mode, "head": head, "branch": branch, "input_digest": digest,
            "digest_algorithm": DIGEST_ALGORITHM, "state": state, "status": entries}


def sanity() -> dict:
    import echo
    from importlib.metadata import distribution
    from typer.testing import CliRunner
    modules = ["echo"] + [m.name for m in pkgutil.walk_packages(echo.__path__, "echo.")]
    for name in modules:
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(ROOT / "src"):
            raise VerificationFailure("Import resolved outside project: " + name)
    from echo.cli import app
    commands = [[], ["research"], ["research", "run"], ["research", "show"], ["research", "claims"],
                ["research", "conflicts"], ["sources"], ["trends"], ["review"]]
    for command in commands:
        result = CliRunner().invoke(app, [*command, "--help"])
        if result.exit_code or result.exception:
            raise VerificationFailure("CLI help failed: " + " ".join(command))
    entrypoint = next(e for e in distribution("project-echo").entry_points if e.name == "echo")
    from echo.cli import main
    if entrypoint.value != "echo.cli:main" or entrypoint.load() is not main:
        raise VerificationFailure("Installed CLI entrypoint mismatch")
    return {"modules": len(modules), "cli_help_checks": len(commands), "entrypoint": entrypoint.value}


def worker(stage: str, temporary_root: Path) -> int:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / "src"))
    blocked = install_worker_guard(temporary_root)
    if stage == "sanity":
        result = sanity()
        code = 0
    else:
        import pytest
        paths = ["tests/test_verification.py"] if stage == "verification" else TARGETED if stage == "targeted" else (
            sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_research_*.py"))
            + ["tests/test_real_research_brain.py", "tests/test_cli_research.py"] if stage == "step3" else ["tests"]
        )
        class Results:
            def __init__(self):
                self.counts = {"passed": 0, "failed": 0, "skipped": 0, "warnings": 0}
            def pytest_runtest_logreport(self, report):
                if report.when == "call" or (report.when != "call" and report.outcome != "passed"):
                    self.counts[report.outcome] += 1
            def pytest_warning_recorded(self, warning_message, when, nodeid, location):
                self.counts["warnings"] += 1
        results = Results()
        code = int(pytest.main(["-q", "-ra", "-x", "--capture=sys", "-p", "no:cacheprovider", "--basetemp",
                                str(temporary_root / stage), *paths], plugins=[results]))
        result = results.counts
    if blocked:
        code = 1
    print("STAGE_RESULT=" + json.dumps({"stage": stage, "exit": code, "blocked": blocked, **result}))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("worktree", "staged", "committed"), default="worktree",
                        help="Checkpoint lifecycle; baseline_head always names the parent commit")
    parser.add_argument("--checks-only", action="store_true", help="Git/docs/hygiene/import/CLI checks; not full test approval")
    parser.add_argument("--worker", choices=("sanity", "verification", "targeted", "step3", "full"), help=argparse.SUPPRESS)
    parser.add_argument("--temporary-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.temporary_root is None or inside(args.temporary_root, ROOT) or inside(ROOT, args.temporary_root):
            raise VerificationFailure("Worker needs an external temporary root")
        return worker(args.worker, args.temporary_root)
    if Path.cwd().resolve() != ROOT:
        raise VerificationFailure("Run verification from the Project Echo repository root")
    checkpoint = verify_checkpoint(args.mode)
    digest = checkpoint["input_digest"]
    before = snapshot(ROOT)
    index_before = (ROOT / ".git" / "index").read_bytes()
    stages = ["sanity"] if args.checks_only else ["verification", "sanity", "targeted", "step3", "full"]
    code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="project-echo-verify-") as directory:
            temporary_root = Path(directory).resolve()
            if inside(temporary_root, ROOT) or inside(ROOT, temporary_root):
                raise VerificationFailure("System temporary directory is inside the repository")
            for stage in stages:
                completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", stage,
                                            "--temporary-root", str(temporary_root)], cwd=ROOT, env=isolated_environment())
                if completed.returncode:
                    code = 1
                    break  # First fresh failure: never run later gates or retry.
    finally:
        if snapshot(ROOT) != before or (ROOT / ".git" / "index").read_bytes() != index_before:
            raise VerificationFailure("Repository/index changed during verification; do not auto-clean")
        final_checkpoint = verify_checkpoint(args.mode)
        if final_checkpoint != checkpoint:
            raise VerificationFailure("Git identity/content/state changed during verification")
        print("FINAL_GIT_STATUS\n" + "\n".join(status + " " + name for status, name in final_checkpoint["status"]))
    print("VERIFICATION_RESULT=" + json.dumps({"result": "PASS" if code == 0 else "FAIL", "checks_only": args.checks_only,
          "mode": args.mode, "head": checkpoint["head"], "baseline_head": checkpoint["state"]["baseline_head"],
          "input_digest": digest, "digest_algorithm": DIGEST_ALGORITHM,
          "python": sys.version.split()[0], "repository_unchanged": True,
          "commit_authorized": False, "live_authorized": False, "env_present": (ROOT / ".env").exists()}))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationFailure as error:
        print("VERIFICATION_FAILED: " + str(error), file=sys.stderr)
        raise SystemExit(1)
