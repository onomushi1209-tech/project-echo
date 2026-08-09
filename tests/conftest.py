from __future__ import annotations

from pathlib import Path

import pytest

from echo.storage.repository import EchoRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "echo_test.db"


@pytest.fixture
def repository(db_path: Path) -> EchoRepository:
    repo = EchoRepository(db_path)
    repo.initialize()
    return repo
