"""Loads VerticalConfig objects from config/verticals/*.yaml.

This is the only place that reads vertical YAML files. It never bakes in
knowledge of which verticals exist -- the caller supplies the id.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from echo.config.settings import get_settings
from echo.verticals.base import VerticalConfig


class VerticalNotFoundError(FileNotFoundError):
    pass


class VerticalConfigError(ValueError):
    pass


def load_vertical_config(vertical_id: str, config_dir: Path | None = None) -> VerticalConfig:
    """Load and validate ``config/verticals/{vertical_id}.yaml``."""
    base_dir = config_dir if config_dir is not None else get_settings().config_dir
    path = base_dir / "verticals" / f"{vertical_id}.yaml"
    if not path.is_file():
        raise VerticalNotFoundError(f"no vertical config found at {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    try:
        return VerticalConfig.model_validate(raw)
    except ValidationError as exc:
        raise VerticalConfigError(f"invalid vertical config at {path}: {exc}") from exc


def list_available_verticals(config_dir: Path | None = None) -> list[str]:
    base_dir = config_dir if config_dir is not None else get_settings().config_dir
    verticals_dir = base_dir / "verticals"
    if not verticals_dir.is_dir():
        return []
    return sorted(p.stem for p in verticals_dir.glob("*.yaml"))
