"""Echo AI vertical: STEP 1 ships only offline dummy fixtures.

Behavioral configuration (topics, content types, review policy) lives in
``config/verticals/ai.yaml`` -- see echo.verticals.registry.load_vertical_config.
"""

from echo.verticals.ai.dummy_data import sample_sources

__all__ = ["sample_sources"]
