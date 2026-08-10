from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from echo.models.enums import ContentType
from echo.verticals.base import VerticalConfig
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


# -- topic_keywords keys must be a subset of topics (Pre-Commit Hardening) ---


def _vertical(**overrides) -> VerticalConfig:
    fields = dict(
        id="x",
        name="X",
        topics=["llm", "robotics"],
        content_types=[ContentType.EXPLAIN],
        primary_language="en",
    )
    fields.update(overrides)
    return VerticalConfig(**fields)


def test_valid_topic_keywords_pass_validation() -> None:
    config = _vertical(topic_keywords={"llm": ["LLM"], "robotics": ["robot"]})
    assert config.topic_keywords["llm"] == ["LLM"]


def test_topic_keywords_defaults_to_empty_and_passes() -> None:
    config = _vertical()
    assert config.topic_keywords == {}


def test_unknown_topic_keywords_key_rejected() -> None:
    with pytest.raises(ValidationError):
        _vertical(topics=["llm"], topic_keywords={"llm": ["LLM"], "robotics": ["robot"]})
