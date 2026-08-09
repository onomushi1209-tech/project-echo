"""VerticalConfig: the schema every ``config/verticals/*.yaml`` file must satisfy.

This is the only contract between Echo Core and a vertical's configuration.
Core code must depend on this model -- never on a specific vertical id.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from echo.models.enums import ContentType


class VerticalConfig(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    content_types: list[ContentType] = Field(min_length=1)
    primary_language: str = Field(min_length=2, max_length=8)
    human_review_required: bool = True
