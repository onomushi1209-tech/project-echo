from __future__ import annotations

import pytest
from pydantic import ValidationError

from echo.models.enums import ReliabilityTier, SourceType
from echo.source.config import SourceConfig
from echo.source.reliability import reliability_score


def _config(**overrides) -> SourceConfig:
    fields = dict(
        id="test_source",
        name="Test Source",
        url="https://example.com/feed",
        source_type=SourceType.RSS,
        vertical="ai",
        reliability_tier=ReliabilityTier.A,
    )
    fields.update(overrides)
    return SourceConfig(**fields)


def test_source_config_valid_minimal() -> None:
    config = _config()
    assert config.enabled is True
    assert config.language == "en"
    assert config.polling_interval == 60
    assert config.primary_source is False


def test_source_config_rejects_invalid_url() -> None:
    with pytest.raises(ValidationError):
        _config(url="not-a-url")


def test_source_config_rejects_non_positive_polling_interval() -> None:
    with pytest.raises(ValidationError):
        _config(polling_interval=0)


def test_source_config_accepts_all_source_types() -> None:
    for source_type in SourceType:
        assert _config(source_type=source_type).source_type == source_type


def test_reliability_score_ordering() -> None:
    assert reliability_score(ReliabilityTier.A) > reliability_score(ReliabilityTier.B)
    assert reliability_score(ReliabilityTier.B) > reliability_score(ReliabilityTier.C)


def test_reliability_score_within_unit_range() -> None:
    for tier in ReliabilityTier:
        score = reliability_score(tier)
        assert 0.0 <= score <= 1.0
