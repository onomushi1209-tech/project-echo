"""Loads SourceConfig objects from config/sources/*.yaml.

This is the only place that reads source registry YAML files. It never
bakes in knowledge of which sources exist for which vertical -- the caller
supplies the vertical id, exactly like echo.verticals.registry.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from echo.config.settings import get_settings
from echo.source.config import SourceConfig


class SourceRegistryNotFoundError(FileNotFoundError):
    pass


class SourceRegistryError(ValueError):
    pass


def load_source_registry(vertical: str, config_dir: Path | None = None) -> list[SourceConfig]:
    """Load and validate ``config/sources/{vertical}.yaml``."""
    base_dir = config_dir if config_dir is not None else get_settings().config_dir
    path = base_dir / "sources" / f"{vertical}.yaml"
    if not path.is_file():
        raise SourceRegistryNotFoundError(f"no source registry found at {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    entries = raw.get("sources", [])
    if not isinstance(entries, list):
        raise SourceRegistryError(f"'sources' in {path} must be a list")

    try:
        configs = [SourceConfig.model_validate(entry) for entry in entries]
    except ValidationError as exc:
        raise SourceRegistryError(f"invalid source registry at {path}: {exc}") from exc

    mismatched = [c.id for c in configs if c.vertical != vertical]
    if mismatched:
        raise SourceRegistryError(
            f"{path} declares sources for a different vertical than requested "
            f"('{vertical}'): {mismatched}"
        )

    duplicate_ids = {c.id for c in configs if [x.id for x in configs].count(c.id) > 1}
    if duplicate_ids:
        raise SourceRegistryError(f"duplicate source id(s) in {path}: {sorted(duplicate_ids)}")

    return configs


def enabled_sources(vertical: str, config_dir: Path | None = None) -> list[SourceConfig]:
    """Convenience filter: only sources ready for ingestion right now."""
    return [s for s in load_source_registry(vertical, config_dir) if s.enabled]
