"""CLI tests for STEP 3 `echo research` commands -- fixture-only, fully
offline, no network access. See docs/RESEARCH_INTELLIGENCE.md."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from typer.testing import CliRunner

from echo.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "ECHO_DATABASE_PATH": str(tmp_path / "cli_research_test.db"),
        "ECHO_CONFIG_DIR": str(PROJECT_ROOT / "config"),
        "ECHO_FIXTURES_DIR": str(PROJECT_ROOT / "tests" / "fixtures" / "sources"),
    }


def _seed_trend(env: dict[str, str]) -> str:
    """init -> ingest --fixture -> trends detect, then return a trend_id."""
    assert runner.invoke(app, ["init"], env=env).exit_code == 0
    assert runner.invoke(app, ["ingest", "--fixture"], env=env).exit_code == 0
    result = runner.invoke(app, ["trends", "detect"], env=env)
    assert result.exit_code == 0
    match = re.search(r"trend_id=(trend-[a-f0-9]+)", result.stdout)
    assert match, result.stdout
    return match.group(1)


def test_cli_research_run_completes_and_persists(tmp_path: Path) -> None:
    env = _env(tmp_path)
    trend_id = _seed_trend(env)

    result = runner.invoke(app, ["research", "run", trend_id], env=env)

    assert result.exit_code == 0
    assert result.exception is None
    assert "Research complete" in result.stdout
    assert "Status:" in result.stdout
    assert "Confidence:" in result.stdout
    assert "Research ID:" in result.stdout


def test_cli_research_run_unknown_trend_fails_cleanly(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    result = runner.invoke(app, ["research", "run", "does-not-exist"], env=env)

    assert result.exit_code == 1
    assert "no trend found" in result.stdout.lower()


def test_cli_research_show_after_run(tmp_path: Path) -> None:
    env = _env(tmp_path)
    trend_id = _seed_trend(env)
    run_result = runner.invoke(app, ["research", "run", trend_id], env=env)
    research_id = _extract_research_id(run_result.stdout)

    result = runner.invoke(app, ["research", "show", research_id], env=env)

    assert result.exit_code == 0
    assert "Status:" in result.stdout
    assert research_id in result.stdout


def test_cli_research_show_unknown_id_fails_cleanly(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    result = runner.invoke(app, ["research", "show", "does-not-exist"], env=env)

    assert result.exit_code == 1


def test_cli_research_claims_lists_claims(tmp_path: Path) -> None:
    env = _env(tmp_path)
    trend_id = _seed_trend(env)
    run_result = runner.invoke(app, ["research", "run", trend_id], env=env)
    research_id = _extract_research_id(run_result.stdout)

    result = runner.invoke(app, ["research", "claims", research_id], env=env)

    assert result.exit_code == 0
    assert "claim(s) for research" in result.stdout


def test_cli_research_conflicts_reports_none_when_no_conflict(tmp_path: Path) -> None:
    env = _env(tmp_path)
    trend_id = _seed_trend(env)
    run_result = runner.invoke(app, ["research", "run", trend_id], env=env)
    research_id = _extract_research_id(run_result.stdout)

    result = runner.invoke(app, ["research", "conflicts", research_id], env=env)

    assert result.exit_code == 0


def test_cli_step1_and_step2_commands_still_work_unmodified(tmp_path: Path) -> None:
    """Regression guard: STEP 3 additions must not break STEP 1/2 commands."""
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    demo_result = runner.invoke(app, ["demo"], env=env)
    assert demo_result.exit_code == 0

    review_result = runner.invoke(app, ["review"], env=env)
    assert review_result.exit_code == 0

    ingest_result = runner.invoke(app, ["ingest", "--fixture"], env=env)
    assert ingest_result.exit_code == 0

    detect_result = runner.invoke(app, ["trends", "detect"], env=env)
    assert detect_result.exit_code == 0


def _extract_research_id(stdout: str) -> str:
    match = re.search(r"Research ID:\s*\n(research-[a-f0-9]+)", stdout)
    assert match, f"could not find Research ID in output:\n{stdout}"
    return match.group(1)


@pytest.mark.parametrize("command", ["detect", "list"])
def test_cli_handoff_uses_only_displayed_ids(tmp_path, command):
    env = _env(tmp_path)
    assert runner.invoke(app, ["init"], env=env).exit_code == 0
    assert runner.invoke(app, ["ingest", "--fixture"], env=env).exit_code == 0
    detected = runner.invoke(app, ["trends", "detect"], env=env)
    result = detected if command == "detect" else runner.invoke(app, ["trends", "list"], env=env)
    assert result.exit_code == 0
    assert "ECHO-AI-" in result.stdout
    match = re.search(r"trend_id=(trend-[a-f0-9]+)", result.stdout)
    assert match, result.stdout
    research = runner.invoke(app, ["research", "run", match.group(1)], env=env)
    assert research.exit_code == 0
    assert "Research complete" in research.stdout
