"""VerticalConfig: the schema every ``config/verticals/*.yaml`` file must satisfy.

This is the only contract between Echo Core and a vertical's configuration.
Core code must depend on this model -- never on a specific vertical id.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from echo.models.enums import ContentType


class VerticalConfig(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    content_types: list[ContentType] = Field(min_length=1)
    primary_language: str = Field(min_length=2, max_length=8)
    human_review_required: bool = True

    # STEP 2: optional per-topic keyword/alias lists used for deterministic
    # relevance scoring (echo.trend.relevance). Defaults to {} so STEP 1
    # vertical configs without this key keep validating unchanged. Keys
    # must be a subset of `topics`, enforced below.
    topic_keywords: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _topic_keywords_keys_are_known_topics(self) -> VerticalConfig:
        unknown = sorted(set(self.topic_keywords) - set(self.topics))
        if unknown:
            raise ValueError(
                f"topic_keywords key(s) {unknown} are not in `topics` {sorted(self.topics)} "
                f"-- topic_keywords keys must be a subset of topics"
            )
        return self
