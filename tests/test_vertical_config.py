from __future__ import annotations

from pathlib import Path

import pytest

from echo.models.enums import ContentType
from echo.verticals.registry import VerticalNotFoundError, load_vertical_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_load_ai_vertical_config() -> None:
    config = load_vertical_config("ai", config_dir=CONFIG_DIR)

    assert config.id == "ai"
    assert config.name == "Echo AI"
    assert "llm" in config.topics
    assert "ai_agents" in config.topics
    assert ContentType.EXPLAIN in config.content_types
    assert ContentType.BREAKING in config.content_types
    assert config.primary_language == "en"
    assert config.human_review_required is True


def test_load_missing_vertical_raises() -> None:
    with pytest.raises(VerticalNotFoundError):
        load_vertical_config("does-not-exist", config_dir=CONFIG_DIR)
