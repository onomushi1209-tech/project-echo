"""CLI tests for the STEP 2 commands. Only network-free invocations are
exercised here (`--fixture` mode) -- pytest must never depend on internet
access. `echo sources check` / `echo ingest` (without --fixture) hit real
sources and are intentionally left to manual use / the smoke test script,
not this suite -- see docs/SOURCE_INTELLIGENCE.md.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from echo.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "ECHO_DATABASE_PATH": str(tmp_path / "cli_test.db"),
        "ECHO_CONFIG_DIR": str(PROJECT_ROOT / "config"),
        "ECHO_FIXTURES_DIR": str(PROJECT_ROOT / "tests" / "fixtures" / "sources"),
    }


def test_cli_init_creates_database(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert (tmp_path / "cli_test.db").exists()


def test_cli_sources_list_shows_registered_sources(tmp_path: Path) -> None:
    result = runner.invoke(app, ["sources", "list"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "nvidia_blog" in result.stdout
    assert "dummy_fixture" in result.stdout


def test_cli_ingest_fixture_is_network_free_and_stores_items(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert runner.invoke(app, ["init"], env=env).exit_code == 0

    result = runner.invoke(app, ["ingest", "--fixture"], env=env)

    assert result.exit_code == 0
    assert "dummy_fixture" in result.stdout
    assert "Total stored: 4" in result.stdout  # 5 fixture items, 1 exact duplicate removed


def test_cli_trends_detect_after_fixture_ingest(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)
    runner.invoke(app, ["ingest", "--fixture"], env=env)

    result = runner.invoke(app, ["trends", "detect"], env=env)

    assert result.exit_code == 0
    assert "Detected" in result.stdout
    assert "trend candidate" in result.stdout


def test_cli_trends_detect_without_ingest_fails_cleanly(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    result = runner.invoke(app, ["trends", "detect"], env=env)

    assert result.exit_code == 1
    assert "echo ingest" in result.stdout.lower()


def test_cli_trends_list_after_detect(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)
    runner.invoke(app, ["ingest", "--fixture"], env=env)
    runner.invoke(app, ["trends", "detect"], env=env)

    result = runner.invoke(app, ["trends", "list"], env=env)

    assert result.exit_code == 0
    assert "trend candidate" in result.stdout


def test_cli_trends_list_empty_before_any_detect(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    result = runner.invoke(app, ["trends", "list"], env=env)

    assert result.exit_code == 0
    assert "No trend candidates" in result.stdout


def test_cli_trends_detect_reports_skipped_count_on_repeat(tmp_path: Path) -> None:
    """Pre-Commit Hardening: running `echo trends detect` a second time
    over the same stored SourceItems must not grow the `trends` table --
    the CLI reports the skipped (already-known, low-novelty) count instead."""
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)
    runner.invoke(app, ["ingest", "--fixture"], env=env)

    first = runner.invoke(app, ["trends", "detect"], env=env)
    assert first.exit_code == 0
    assert first.exception is None

    from echo.storage.repository import EchoRepository

    repo = EchoRepository(Path(env["ECHO_DATABASE_PATH"]))
    first_count = len(repo.list_trends())
    assert first_count > 0

    second = runner.invoke(app, ["trends", "detect"], env=env)

    assert second.exit_code == 0
    assert second.exception is None  # no UNIQUE errors / crash
    assert "skipped" in second.stdout.lower()
    assert len(repo.list_trends()) == first_count  # unchanged, no unbounded growth


def test_cli_step1_commands_still_work_unmodified(tmp_path: Path) -> None:
    """Regression guard: STEP 2 additions must not break STEP 1 commands."""
    env = _env(tmp_path)
    runner.invoke(app, ["init"], env=env)

    demo_result = runner.invoke(app, ["demo"], env=env)
    assert demo_result.exit_code == 0

    review_result = runner.invoke(app, ["review"], env=env)
    assert review_result.exit_code == 0
