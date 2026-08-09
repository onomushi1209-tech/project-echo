"""Project Echo -- AI Media Operating System.

``echo.core`` contains vertical-agnostic pipeline logic. Vertical-specific
behavior (topics, prompts, content rules) must live under ``echo.verticals``
and ``config/verticals/*.yaml`` -- never hard-coded into core.
"""

__version__ = "0.1.0"
