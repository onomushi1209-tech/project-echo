from __future__ import annotations

from pathlib import Path

import pytest

from echo.source.registry import (
    SourceRegistryError,
    SourceRegistryNotFoundError,
    enabled_sources,
    load_source_registry,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def test_load_ai_source_registry() -> None:
    sources = load_source_registry("ai", config_dir=CONFIG_DIR)
    ids = {s.id for s in sources}
    assert "nvidia_blog" in ids
    assert "openai_news" in ids
    assert "dummy_fixture" in ids


def test_enabled_sources_excludes_disabled_entries() -> None:
    enabled = enabled_sources("ai", config_dir=CONFIG_DIR)
    enabled_ids = {s.id for s in enabled}
    assert "nvidia_blog" in enabled_ids
    assert "microsoft_research" not in enabled_ids
    assert "google_deepmind_blog" not in enabled_ids
    assert "anthropic_news" not in enabled_ids


def test_load_missing_vertical_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceRegistryNotFoundError):
        load_source_registry("does-not-exist", config_dir=tmp_path)


def test_registry_rejects_vertical_mismatch(tmp_path: Path) -> None:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "ai.yaml").write_text(
        """
vertical: ai
sources:
  - id: wrong_vertical_source
    name: "Wrong"
    url: "https://example.com/feed"
    source_type: rss
    vertical: tech
    reliability_tier: tier_a
""",
        encoding="utf-8",
    )
    with pytest.raises(SourceRegistryError):
        load_source_registry("ai", config_dir=tmp_path)


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "ai.yaml").write_text(
        """
vertical: ai
sources:
  - id: dup
    name: "First"
    url: "https://example.com/first"
    source_type: rss
    vertical: ai
    reliability_tier: tier_a
  - id: dup
    name: "Second"
    url: "https://example.com/second"
    source_type: rss
    vertical: ai
    reliability_tier: tier_b
""",
        encoding="utf-8",
    )
    with pytest.raises(SourceRegistryError):
        load_source_registry("ai", config_dir=tmp_path)


def test_registry_rejects_invalid_entry(tmp_path: Path) -> None:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "ai.yaml").write_text(
        """
vertical: ai
sources:
  - id: bad
    name: "Bad"
    url: "not-a-url"
    source_type: rss
    vertical: ai
    reliability_tier: tier_a
""",
        encoding="utf-8",
    )
    with pytest.raises(SourceRegistryError):
        load_source_registry("ai", config_dir=tmp_path)
