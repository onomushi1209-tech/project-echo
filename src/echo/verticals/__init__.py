"""Vertical registry: how Echo Core discovers vertical-specific config.

Concrete verticals (e.g. ``echo.verticals.ai``) provide only dummy data /
fixtures in STEP 1 -- their behavioral config lives in
``config/verticals/*.yaml`` and is loaded through ``registry.py``.
"""

from echo.verticals.base import VerticalConfig
from echo.verticals.registry import (
    VerticalConfigError,
    VerticalNotFoundError,
    list_available_verticals,
    load_vertical_config,
)

__all__ = [
    "VerticalConfig",
    "VerticalConfigError",
    "VerticalNotFoundError",
    "list_available_verticals",
    "load_vertical_config",
]
